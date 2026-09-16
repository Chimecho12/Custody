from __future__ import annotations

import datetime
import ipaddress
import json
import os
import queue
import secrets
import subprocess
import sys
import threading
from pathlib import Path

from .common import ISS, MODEL_HASH, MODEL_ID, KeyPair, now_ms, require_crypto, seal, write_private


def create_deployment(root, *, lab=True, hosts=None):
    """Provision an evaluation deployment. Distribute role directories separately.

    The provisioner controls all initial keys: this is NOT independent governance.
    Windows key files are DPAPI-bound; remote operators must provision on their own
    account and exchange public identities for an independent pilot.
    """
    require_crypto()
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    root = Path(root).resolve()
    if (root / "U" / "config.json").exists():
        return root
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(root.iterdir()):
        raise ValueError("새 배포에는 빈 폴더를 사용하세요. 기존 키를 덮어쓰지 않습니다.")
    created = now_ms()
    keys = {r: KeyPair.from_seed(f"{r.lower()}-{secrets.token_hex(6)}", secrets.token_bytes(32)) for r in ISS}
    identities = {r: {"iss": ISS[r], "kid": k.kid, "public_key": k.public_hex} for r, k in keys.items()}
    hosts = hosts or dict.fromkeys("RMT", "127.0.0.1")
    endpoints = {r: f"https://{hosts[r]}:{port}" for r, port in zip("TMR", (8741, 8742, 8743), strict=True)}
    current = datetime.datetime.now(datetime.timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "itx evaluation deployment CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(current - datetime.timedelta(minutes=5))
          .not_valid_after(current + datetime.timedelta(days=90))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .sign(ca_key, hashes.SHA256()))
    for role, key in keys.items():
        directory = root / role
        directory.mkdir(mode=0o700)
        write_private(directory / "identity.key", seal(key.seed))
        (directory / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
        config = {"version": 1, "role": role, "lab": lab, "created_at": created,
                  "policy_expires_at": created + 90 * 86400000,
                  "log_id": "network-" + keys["T"].kid, "identities": identities,
                  "endpoints": endpoints, "ca_file": str(directory / "ca.pem"),
                  "model_id": MODEL_ID, "model_hashes": {MODEL_ID: MODEL_HASH},
                  "model_kind": "deterministic_mock", "pre_exec": False,
                  "strict_timeout_ms": 2500, "queue_capacity": 256,
                  "governance": "single_operator", "bind": "127.0.0.1", "port": 0 if lab else 8740 + "TMR".find(role) + 1}
        if role in "RMT":
            tls_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            sans = [x509.DNSName("localhost")]
            for host in {hosts[role], "127.0.0.1"}:
                try:
                    sans.append(x509.IPAddress(ipaddress.ip_address(host)))
                except ValueError:
                    sans.append(x509.DNSName(host))
            cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, role)]))
                    .issuer_name(ca_name).public_key(tls_key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(current - datetime.timedelta(minutes=5)).not_valid_after(current + datetime.timedelta(days=90))
                    .add_extension(x509.SubjectAlternativeName(sans), critical=False)
                    .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                    .sign(ca_key, hashes.SHA256()))
            write_private(directory / "tls.key", tls_key.private_bytes(serialization.Encoding.PEM,
                          serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            (directory / "tls.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            config.update(tls_cert=str(directory / "tls.pem"), tls_key=str(directory / "tls.key"))
        (directory / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    return root


class Lab:
    def __init__(self, root):
        self.root = create_deployment(root)
        self.children = {}
        self.endpoints = {}
        self.lock = threading.RLock()

    def start(self):
        with self.lock:
            try:
                for role in "TMR":
                    self.start_role(role)
            except Exception:
                self.close()
                raise
        return str(self.root / "U" / "config.json")

    def start_role(self, role):
        with self.lock:
            if role in self.children and self.children[role].poll() is None:
                return
            self._update()
            config_path = self.root / role / "config.json"
            if getattr(sys, "frozen", False):
                command = [sys.executable, "service", "--config", str(config_path), "--parent-pipe"]
            else:
                command = [sys.executable, "-B", "-m", "itx.runtime.service", "--config", str(config_path), "--parent-pipe"]
            stderr = open(self.root / role / "service.stderr.log", "ab")  # noqa: SIM115 — 자식이 상속한 뒤 바로 닫는다
            env = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1")
            if getattr(sys, "frozen", False):
                env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
            child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
                                     creationflags=0x08000000 if os.name == "nt" else 0,
                                     env=env, cwd=str(Path(__file__).resolve().parents[2]) if not getattr(sys, "frozen", False) else None)
            stderr.close()
            messages = queue.Queue()
            threading.Thread(target=lambda: messages.put(child.stdout.readline()), daemon=True).start()
            try:
                line = messages.get(timeout=40)
                ready = json.loads(line)
                if not ready.get("ready"):
                    raise ValueError("service did not become ready")
            except Exception as error:
                child.kill()
                child.wait(timeout=5)
                raise RuntimeError(f"{role} 서비스를 시작하지 못했습니다. service.stderr.log를 확인하세요.") from error
            self.children[role] = child
            self.endpoints[role] = f"https://127.0.0.1:{ready['port']}"
            self._update()

    def _update(self):
        for role in ISS:
            path = self.root / role / "config.json"
            config = json.loads(path.read_text(encoding="utf-8"))
            config["endpoints"].update(self.endpoints)
            path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    def stop_role(self, role):
        with self.lock:
            child = self.children.pop(role, None)
            if child:
                child.stdin.close()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=3)
                child.stdout.close()

    def restart_t(self):
        # Keep T's bound port so running R and M can reconnect with their cached configuration.
        path = self.root / "T" / "config.json"
        config = json.loads(path.read_text())
        if "T" in self.endpoints:
            config["port"] = int(self.endpoints["T"].rsplit(":", 1)[1])
            path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        self.start_role("T")

    def status(self):
        return {r: {"running": r in self.children and self.children[r].poll() is None,
                    "endpoint": self.endpoints.get(r)} for r in "RMT"}

    def close(self):
        for role in "RMT":
            self.stop_role(role)
