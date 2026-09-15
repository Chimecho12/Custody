"""RFC 3161 TSA 앵커: SHA-256 Merkle 루트를 외부 시각에 고정한다.

요청/메타데이터의 DER 처리는 표준 라이브러리로, CMS 서명·인증서 체인·TSA 용도
검증은 OpenSSL의 ``ts -verify``로 수행한다. ca_file은 호출자가 별도로 신뢰한
PEM CA 묶음이어야 한다. 응답에 실린 인증서를 신뢰 루트로 승격하지 않는다.

.tsr에는 원본 TimeStampResp를 보관한다. 독립 감사에는 JSON 앵커 기록, 토큰 디렉터리,
별도로 신뢰한 CA 파일이 필요하며 네트워크 재접속은 하지 않는다. 인증서 유효기간은
서명된 genTime 기준으로 검사한다. CRL/OCSP 및 장기 보존 증거 갱신은 별도 정책이다.
TSA가 서명하는 것은 root_hash이다. log_id·head_time 등 주변 메타데이터는 대상이 아니다.

규격: https://www.rfc-editor.org/rfc/rfc3161.html (§2.4, §3.4)
검증기: https://docs.openssl.org/3.6/man1/openssl-ts/
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
from http.client import HTTPException
import json
import math
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
from typing import Any
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from itx.ts.anchor import CheckpointAnchor

DEFAULT_TSA_URL = "https://freetsa.org/tsr"
MAX_RESPONSE_BYTES = 1024 * 1024
TSA_WITNESS = "rfc3161-tsa"
_SHA256_OID = bytes.fromhex("608648016503040201")
_SIGNED_DATA_OID = bytes.fromhex("2a864886f70d010702")
_TST_INFO_OID = bytes.fromhex("2a864886f70d0109100104")


class TSAError(ValueError):
    """TSA 통신·형식·서명·신뢰 또는 체크포인트 결합 검증 실패."""


def _root_bytes(root_hash: str) -> bytes:
    if not isinstance(root_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", root_hash):
        raise TSAError("root_hash must be a SHA-256 hex digest")
    return bytes.fromhex(root_hash)


def _der(tag: int, value: bytes) -> bytes:
    size = len(value)
    length = bytes([size]) if size < 128 else size.to_bytes((size.bit_length() + 7) // 8, "big")
    if size >= 128:
        length = bytes([0x80 | len(length)]) + length
    return bytes([tag]) + length + value


def _integer(value: int) -> bytes:
    encoded = value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")
    if encoded[0] & 0x80:
        encoded = b"\x00" + encoded
    return _der(0x02, encoded)


def build_timestamp_request(root_hash: str, nonce: int | None = None) -> bytes:
    """root_hash를 재해싱하지 않고 SHA-256 messageImprint로 사용한다."""
    root = _root_bytes(root_hash)
    if nonce is None:
        nonce = secrets.randbits(128) or 1
    if type(nonce) is not int or not 0 < nonce < 2**160:
        raise TSAError("nonce must be a positive integer of at most 160 bits")
    algorithm = _der(0x30, _der(0x06, _SHA256_OID) + _der(0x05, b""))
    imprint = _der(0x30, algorithm + _der(0x04, root))
    return _der(0x30, _integer(1) + imprint + _integer(nonce) + _der(0x01, b"\xff"))


class _Reader:
    """필요한 ASN.1 필드만 읽는, 길이 제한이 있는 strict DER reader."""

    def __init__(self, data: bytes):
        self.data, self.offset = data, 0

    def peek(self) -> int | None:
        return self.data[self.offset] if self.offset < len(self.data) else None

    def read(self, tag: int) -> bytes:
        if self.peek() != tag or self.offset + 2 > len(self.data):
            raise TSAError("unexpected or truncated DER tag")
        start = self.offset + 2
        size = self.data[self.offset + 1]
        if size & 0x80:
            count = size & 0x7F
            if not 1 <= count <= 4 or start + count > len(self.data):
                raise TSAError("invalid DER length")
            if self.data[start] == 0:
                raise TSAError("non-canonical DER length")
            size = int.from_bytes(self.data[start:start + count], "big")
            start += count
            if size < 128:
                raise TSAError("non-canonical DER length")
        end = start + size
        if end > len(self.data):
            raise TSAError("truncated DER value")
        self.offset = end
        return self.data[start:end]

    def integer(self) -> int:
        data = self.read(0x02)
        if (not data or len(data) > 33 or data[0] & 0x80
                or len(data) > 1 and data[0] == 0 and not data[1] & 0x80):
            raise TSAError("invalid non-negative DER integer")
        return int.from_bytes(data, "big")

    def finish(self) -> None:
        if self.peek() is not None:
            raise TSAError("unexpected trailing DER data")


def _single(data: bytes, tag: int) -> bytes:
    reader = _Reader(data)
    value = reader.read(tag)
    reader.finish()
    return value


def _oid(data: bytes) -> str:
    values, value = [], 0
    if not data or len(data) > 128 or data[-1] & 0x80:
        raise TSAError("invalid DER object identifier")
    for byte in data:
        if value == 0 and byte == 0x80:
            raise TSAError("non-canonical DER object identifier")
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            values.append(value)
            value = 0
    first = min(values[0] // 40, 2)
    return ".".join(map(str, [first, values[0] - first * 40, *values[1:]]))


def _parse_response(response: bytes) -> dict[str, Any]:
    """메타데이터 추출만 수행한다. 반환값은 서명 검증 전까지 신뢰하면 안 된다."""
    if not isinstance(response, bytes) or not 0 < len(response) <= MAX_RESPONSE_BYTES:
        raise TSAError("invalid timestamp response size")
    outer = _Reader(_single(response, 0x30))
    status = _Reader(outer.read(0x30))
    code = status.integer()
    if code != 0:  # Task 3은 grantedWithMods(1)도 수용하지 않는다.
        raise TSAError(f"TSA did not grant the request (PKIStatus={code})")
    if status.peek() == 0x30:
        status.read(0x30)  # statusString
    if status.peek() == 0x03:
        raise TSAError("granted response contains failInfo")
    status.finish()
    content = _Reader(outer.read(0x30))
    outer.finish()
    if content.read(0x06) != _SIGNED_DATA_OID:
        raise TSAError("timestamp token must contain CMS SignedData")
    signed = _Reader(_single(content.read(0xA0), 0x30))
    content.finish()
    if signed.integer() != 3:
        raise TSAError("unsupported SignedData version")
    signed.read(0x31)  # digestAlgorithms: OpenSSL이 서명과 함께 검증한다.
    encapsulated = _Reader(signed.read(0x30))
    if encapsulated.read(0x06) != _TST_INFO_OID:
        raise TSAError("timestamp token must encapsulate TSTInfo")
    tst = _Reader(_single(_single(encapsulated.read(0xA0), 0x04), 0x30))
    encapsulated.finish()
    for tag in (0xA0, 0xA1):  # certificates, crls
        if signed.peek() == tag:
            signed.read(tag)
    if not signed.read(0x31):
        raise TSAError("timestamp token has no signer")
    signed.finish()
    if tst.integer() != 1:
        raise TSAError("unsupported TSTInfo version")
    policy = _oid(tst.read(0x06))
    imprint = _Reader(tst.read(0x30))
    algorithm = _Reader(imprint.read(0x30))
    if algorithm.read(0x06) != _SHA256_OID:
        raise TSAError("timestamp messageImprint must use SHA-256")
    if algorithm.peek() is not None and algorithm.read(0x05) != b"":
        raise TSAError("invalid SHA-256 parameters")
    algorithm.finish()
    digest = imprint.read(0x04)
    imprint.finish()
    if len(digest) != 32:
        raise TSAError("timestamp messageImprint must contain 32 bytes")
    serial = tst.integer()
    try:
        gen_time = tst.read(0x18).decode("ascii")
        if not re.fullmatch(r"\d{14}(?:\.\d*[1-9])?Z", gen_time):
            raise ValueError("non-canonical GeneralizedTime")
        whole, _, fraction = gen_time[:-1].partition(".")
        instant = datetime.strptime(whole, "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc, microsecond=int((fraction + "000000")[:6]))
    except (ValueError, UnicodeError) as exc:
        raise TSAError("invalid TSTInfo genTime") from exc
    if tst.peek() == 0x30:
        tst.read(0x30)  # accuracy (서명된 원본에 보존된다)
    if tst.peek() == 0x01 and tst.read(0x01) != b"\xff":
        raise TSAError("invalid DER ordering flag")
    nonce = tst.integer() if tst.peek() == 0x02 else None
    for tag in (0xA0, 0xA1):  # tsa name, extensions
        if tst.peek() == tag:
            tst.read(tag)
    tst.finish()
    elapsed = instant - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return {"root_hash": digest.hex(), "gen_time": gen_time,
            "timestamp_ms": (elapsed.days * 86400 + elapsed.seconds) * 1000 + elapsed.microseconds // 1000,
            "tsa_nonce": format(nonce, "x") if nonce is not None else None,
            "policy_oid": policy, "serial_number": str(serial)}


def _check_timeout(timeout: float) -> None:
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise TSAError("timeout must be finite and positive")


def verify_timestamp_response(
    response: bytes, root_hash: str, *, ca_file: Path | str,
    nonce: int | None = None, openssl: str = "openssl", timeout: float = 10,
) -> dict[str, Any]:
    """DER·imprint·nonce와 CMS 서명/인증서 신뢰를 검증한 메타데이터를 반환한다."""
    _check_timeout(timeout)
    root = _root_bytes(root_hash)
    query = build_timestamp_request(root_hash, nonce) if nonce is not None else None
    info = _parse_response(response)
    if not hmac.compare_digest(bytes.fromhex(info["root_hash"]), root):
        raise TSAError("timestamp messageImprint differs from the checkpoint root")
    if nonce is not None and info["tsa_nonce"] != format(nonce, "x"):
        raise TSAError("timestamp nonce does not match the request")
    if ca_file is None or not Path(ca_file).is_file():
        raise TSAError("an independently trusted TSA CA file is required")
    try:
        with tempfile.TemporaryDirectory(prefix="itx-tsa-verify-") as directory:
            work = Path(directory)
            token_file = work / "response.tsr"
            token_file.write_bytes(response)
            command = [openssl, "ts", "-verify", "-in", str(token_file),
                       "-CAfile", str(Path(ca_file).resolve()),
                       "-attime", str(info["timestamp_ms"] // 1000)]
            if query is not None:
                query_file = work / "request.tsq"
                query_file.write_bytes(query)
                command.extend(["-queryfile", str(query_file)])
            else:
                command.extend(["-digest", root.hex()])
            result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                    timeout=timeout, check=False,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TSAError("OpenSSL timestamp verification could not complete") from exc
    if result.returncode != 0:
        raise TSAError("TSA signature or certificate chain verification failed")
    return info


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_timestamp(
    root_hash: str, *, ca_file: Path | str, tsa_url: str = DEFAULT_TSA_URL,
    timeout: float = 10, openssl: str = "openssl",
) -> tuple[bytes, dict[str, Any]]:
    """TSA에 POST하고 검증된 원본 응답과 메타데이터를 반환한다."""
    _check_timeout(timeout)
    url = urlsplit(tsa_url)
    if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.fragment:
        raise TSAError("tsa_url must be an HTTP(S) URL without credentials or a fragment")
    if ca_file is None or not Path(ca_file).is_file():
        raise TSAError("an independently trusted TSA CA file is required")
    nonce = secrets.randbits(128) or 1
    query = build_timestamp_request(root_hash, nonce)
    request = Request(tsa_url, data=query, method="POST", headers={
        "Content-Type": "application/timestamp-query", "Accept": "application/timestamp-reply"})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=timeout) as reply:
            if reply.status != 200 or reply.headers.get_content_type() != "application/timestamp-reply":
                raise TSAError("unexpected TSA HTTP status or Content-Type")
            response = reply.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, URLError, HTTPException) as exc:
        raise TSAError("TSA HTTP request failed") from exc
    info = verify_timestamp_response(response, root_hash, ca_file=ca_file,
                                     nonce=nonce, openssl=openssl, timeout=timeout)
    return response, info


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tsa-", delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class TSAAnchor(CheckpointAnchor):
    """CheckpointAnchor.anchor(tree_head, now)와 호환되는 실제 TSA 목격자.

    예: TSAAnchor(Path("anchors.json"), ca_file=Path("trusted-tsa-ca.pem"))
    토큰은 기본적으로 JSON 옆의 ``<stem>-tokens/`` 디렉터리에 저장된다.
    """
    kind = TSA_WITNESS

    def __init__(self, path: Path | str, *, ca_file: Path | str,
                 tsa_url: str = DEFAULT_TSA_URL, token_dir: Path | str | None = None,
                 timeout: float = 10, openssl: str = "openssl") -> None:
        super().__init__(Path(path))
        self.ca_file, self.tsa_url = ca_file, tsa_url
        self.timeout, self.openssl = timeout, openssl
        self.token_dir = Path(token_dir) if token_dir is not None else self.path.with_name(self.path.stem + "-tokens")
        if self.path.exists():
            self.records = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self.records, list) or not all(isinstance(rec, dict) for rec in self.records):
                raise TSAError("anchor file must contain a list of records")

    def anchor(self, tree_head: dict[str, Any], now: int) -> dict[str, Any]:
        root_hash = _root_bytes(tree_head["root_hash"]).hex()
        if type(tree_head["tree_size"]) is not int or tree_head["tree_size"] < 0:
            raise TSAError("tree_size must be a non-negative integer")
        record = {"log_id": tree_head["log_id"], "tree_size": tree_head["tree_size"],
                  "root_hash": root_hash, "head_time": tree_head["time"],
                  "ts_kid": tree_head["ts_kid"], "head_signature": tree_head["signature"],
                  "requested_at": now, "witness": self.kind, "tsa_url": self.tsa_url}
        response, info = request_timestamp(root_hash, ca_file=self.ca_file, tsa_url=self.tsa_url,
                                           timeout=self.timeout, openssl=self.openssl)
        filename = hashlib.sha256(response).hexdigest() + ".tsr"
        record.update(info, anchored_at=info["timestamp_ms"], tsr_file=filename)
        _atomic_write(self.token_dir / filename, response)
        records = self.records + [record]
        _atomic_write(self.path, json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8"))
        self.records = records
        return record

    def verify_log(self, log) -> list[dict[str, Any]]:
        return self.verify_tree(log.tree, self.records, tsa_ca_file=self.ca_file,
                                tsa_token_dir=self.token_dir, tsa_openssl=self.openssl)


def verify_tsa_anchor(record: dict[str, Any], *, token_dir: Path | str | None,
                      ca_file: Path | str | None, openssl: str = "openssl") -> dict[str, Any]:
    """외부에서 받은 메타데이터와 저장된 .tsr를 신뢰 CA에 대해 다시 검증한다."""
    try:
        if record.get("witness") != TSA_WITNESS or token_dir is None:
            raise TSAError("TSA witness and token directory are required")
        filename = record["tsr_file"]
        if not isinstance(filename, str) or not re.fullmatch(r"[0-9a-f]{64}\.tsr", filename):
            raise TSAError("invalid TSA token filename")
        directory = Path(token_dir).resolve()
        path = (directory / filename).resolve()
        if path.parent != directory:
            raise TSAError("TSA token is outside the token directory")
        with path.open("rb") as token:
            response = token.read(MAX_RESPONSE_BYTES + 1)
        if hashlib.sha256(response).hexdigest() != filename[:-4]:
            raise TSAError("saved TSA token digest mismatch")
        nonce = record["tsa_nonce"]
        if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{1,40}", nonce) or int(nonce, 16) == 0:
            raise TSAError("invalid saved TSA nonce")
        info = verify_timestamp_response(response, record["root_hash"], ca_file=ca_file,
                                         nonce=int(nonce, 16), openssl=openssl)
        if any(record.get(key) != value for key, value in info.items()) or record["anchored_at"] != info["timestamp_ms"]:
            raise TSAError("TSA checkpoint metadata differs from the signed token")
        return info
    except (OSError, KeyError, TypeError) as exc:
        raise TSAError("TSA checkpoint evidence is missing or unreadable") from exc
