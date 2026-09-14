from __future__ import annotations

import ctypes
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from itx.crypto import KeyPair, HAS_CRYPTOGRAPHY, canonical_json, content_hash_hex, commit_hex
from itx.statements import (SignedStatement, issue, validate_payload, ALL_CONTENT_TYPES,
                            CT_CONTRACT, CT_RELAY, CT_RECEIPT, CT_OBSERVATION, CT_VERDICT)
from itx.statements.schemas import policy_payload

MAX_WIRE = 2 * 1024 * 1024
MAX_PROMPT = 16000
MAX_RESPONSE = 128000
ISS = {r: f"urn:itx:party:{r.lower()}" for r in "URMT"}
TYPES = {"U": [CT_CONTRACT, CT_OBSERVATION], "R": [CT_RELAY], "M": [CT_RECEIPT], "T": [CT_VERDICT]}
MODEL_ID = "itx-reference-v1"
MODEL_HASH = content_hash_hex(b"itx deterministic text reference model v1")


def now_ms():
    return time.time_ns() // 1_000_000


def require_crypto():
    if not HAS_CRYPTOGRAPHY:
        raise RuntimeError("실제 통신 실행에는 cryptography가 필요합니다. 순수 Python 서명으로 대체하지 않습니다.")


def json_loads(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError("duplicate JSON key")
            result[k] = v
        return result
    value = json.loads(raw, object_pairs_hook=pairs)
    canonical_json(value)  # rejects floats, non-ASCII keys, NaN
    return value


def digest(body, salt):
    if not isinstance(salt, str) or len(salt) != 64:
        raise ValueError("invalid salt")
    bytes.fromhex(salt)
    return commit_hex(salt, content_hash_hex(canonical_json(body)))


def seal(data: bytes) -> bytes:
    return _dpapi(data, True) if os.name == "nt" else b"POSIX\0" + data


def unseal(data: bytes) -> bytes:
    if os.name == "nt":
        return _dpapi(data, False)
    if not data.startswith(b"POSIX\0"):
        raise ValueError("secret belongs to another OS account")
    return data[6:]


def _dpapi(data, encrypt):
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, dest = Blob(len(data), buffer), Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(dest)):
        raise OSError(ctypes.get_last_error(), "OS secret protection failed")
    try:
        return ctypes.string_at(dest.pbData, dest.cbData)
    finally:
        kernel.LocalFree(dest.pbData)


def write_private(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


class ProcessLock:
    """OS-owned lock: automatically released even when the process is killed."""
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(path, "a+b")
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("같은 데이터 폴더를 사용하는 itx 프로세스가 실행 중입니다.") from None

    def close(self):
        self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def load_config(path):
    require_crypto()
    path = Path(path).resolve()
    config = json_loads(path.read_bytes())
    if config.get("version") != 1 or config.get("role") not in (*ISS, "W"):
        raise ValueError("지원하지 않는 연결 설정입니다.")
    config["config_path"] = str(path)
    config["directory"] = str(path.parent)
    for field in ("ca_file", "tls_cert", "tls_key", "tls_password_file", "deployment_file"):
        if field in config:
            config[field] = str((path.parent / config[field]).resolve())
    config["ca_files"] = {r: str((path.parent / p).resolve()) for r, p in config.get("ca_files", {}).items()}
    for role in "URMT":
        info = config["identities"][role]
        if info["iss"] != ISS[role] or len(bytes.fromhex(info["public_key"])) != 32:
            raise ValueError("잘못된 신뢰 키 설정입니다.")
    if len({config["identities"][r]["kid"] for r in ISS}) != 4 or len({config["identities"][r]["public_key"] for r in ISS}) != 4:
        raise ValueError("역할별 키는 서로 달라야 합니다.")
    if type(config.get("strict_timeout_ms")) is not int or not 100 <= config["strict_timeout_ms"] <= 10000:
        raise ValueError("strict 대기 시간은 100~10,000 ms 정수여야 합니다.")
    if type(config.get("policy_expires_at")) is not int or type(config.get("created_at")) is not int:
        raise ValueError("정책 시각은 정수여야 합니다.")
    if config["policy_expires_at"] <= config["created_at"] or type(config.get("lab")) is not bool:
        raise ValueError("정책 기간 또는 실험 구분이 잘못되었습니다.")
    if config.get("deployment_file"):
        from .enrollment import verify_deployment, configuration
        from .packages import read_document
        bundle = read_document(config["deployment_file"])
        verify_deployment(bundle)
        if any(config.get(k) != v for k, v in configuration(bundle).items()):
            raise ValueError("local configuration differs from the endorsed deployment")
    return config


def key_for(config):
    role = config["role"]
    seed = unseal((Path(config["directory"]) / "identity.key").read_bytes())
    key = KeyPair.from_seed(config["identities"][role]["kid"], seed)
    if key.public_hex != config["identities"][role]["public_key"]:
        raise ValueError("local key does not match pinned identity")
    return key


def policy_for(config):
    identities = config["identities"]
    policy = policy_payload(version=config.get("epoch", 1), ts_id=config["log_id"], ts_iss=ISS["T"],
                          allowed_content_types=list(ALL_CONTENT_TYPES),
                          sub_pattern=r"^urn:itx:(req|policy):[0-9a-zA-Z:-]+$",
                          trusted_keys={i["kid"]: {"iss": i["iss"], "public_key": i["public_key"]}
                                        for r, i in identities.items() if r in "URM"},
                          issuer_content_types={ISS[r]: TYPES[r] for r in "URM"})
    if config.get("deployment_hash"):
        policy["deployment_hash"] = config["deployment_hash"]
    return policy


def signed(config, key, ct, sub, payload):
    return issue(key, iss=ISS[config["role"]], sub=sub, content_type=ct,
                 payload=payload, issued_at=now_ms())


def authenticate(config, data, role, ct, sub=None):
    if not isinstance(data, dict) or set(data) != {"iss", "sub", "content_type", "kid", "issued_at", "payload", "signature"}:
        raise ValueError("invalid statement envelope")
    if type(data["issued_at"]) is not int or not isinstance(data["payload"], dict):
        raise ValueError("invalid statement types")
    s = SignedStatement.from_dict(data)
    info = config["identities"][role]
    if (s.iss != info["iss"] or s.kid != info["kid"] or s.content_type != ct
            or ct not in TYPES[role] or (sub is not None and s.sub != sub)):
        raise ValueError("statement issuer, role, type or request binding is invalid")
    if not s.verify_with(bytes.fromhex(info["public_key"])):
        raise ValueError("statement signature is invalid")
    if validate_payload(ct, s.payload):
        raise ValueError("statement schema is invalid")
    return s


class Store:
    """Single-process serialized SQLite writes; sensitive payloads are OS protected."""
    def __init__(self, directory):
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path / "state.sqlite", check_same_thread=False)
        if os.name != "nt":
            os.chmod(path / "state.sqlite", 0o600)
        self.db.executescript("""
          PRAGMA journal_mode=WAL;
          PRAGMA synchronous=FULL;
          CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, value BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS journal (seq INTEGER PRIMARY KEY, hash TEXT UNIQUE, value BLOB NOT NULL);
        """)

    def get(self, key, default=None):
        with self.lock:
            row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            return json_loads(unseal(row[0])) if row else default

    def put(self, key, value):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, seal(canonical_json(value))))

    def claim(self, key, value):
        with self.lock, self.db:
            cur = self.db.execute("INSERT OR IGNORE INTO kv VALUES (?,?)", (key, seal(canonical_json(value))))
            return cur.rowcount == 1

    def items(self, prefix):
        with self.lock:
            rows = self.db.execute("SELECT key,value FROM kv WHERE key LIKE ? ORDER BY key DESC", (prefix + "%",)).fetchall()
            return [(k, json_loads(unseal(v))) for k, v in rows]

    def count(self, prefix):
        with self.lock:
            return self.db.execute("SELECT count(*) FROM kv WHERE key LIKE ?", (prefix + "%",)).fetchone()[0]

    def enqueue(self, item, capacity=256):
        ident = content_hash_hex(canonical_json(item))
        with self.lock, self.db:
            if self.db.execute("SELECT 1 FROM outbox WHERE id=?", (ident,)).fetchone():
                return
            if self.db.execute("SELECT count(*) FROM outbox").fetchone()[0] >= capacity:
                raise RuntimeError("증거 큐가 가득 찼습니다. 새 요청을 보류합니다.")
            self.db.execute("INSERT INTO outbox VALUES (?,?)", (ident, seal(canonical_json(item))))

    def pending(self):
        with self.lock:
            return [(i, json_loads(unseal(v))) for i, v in self.db.execute("SELECT id,value FROM outbox ORDER BY rowid")]

    def ack(self, ident):
        with self.lock, self.db:
            self.db.execute("DELETE FROM outbox WHERE id=?", (ident,))

    def close(self):
        self.db.close()
