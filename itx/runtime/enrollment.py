"""Independent local key generation and unanimously endorsed immutable deployment epochs.

Only signed public cards/endorsements travel between operators. The first deployment
fingerprint still needs an out-of-band check; signatures do not prove legal independence.
"""
from __future__ import annotations

import datetime
import ipaddress
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from itx.crypto import KeyPair, canonical_json, verify

from .auditing import fingerprint, trust_from_config, verify_head
from .common import MODEL_HASH, MODEL_ID, now_ms, seal, unseal, write_private
from .packages import read_document, write_document

ROLES = "URMTW"


def endpoint_url(endpoint):
    u = urlsplit(endpoint)
    if (u.scheme != "https" or not u.hostname or u.username or u.password
            or u.path not in ("", "/") or u.query or u.fragment or not u.port):
        raise ValueError("endpoint must be an HTTPS host and explicit port, without path or credentials")
    return u


def prepare_operator(directory, role, endpoint=None):
    if role not in tuple(ROLES):
        raise ValueError("role must be U, R, M, T or W")
    if role != "U":
        endpoint_url(endpoint)
    elif endpoint:
        raise ValueError("U has no listening endpoint")
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise ValueError("new operator identity requires an empty directory")
    key = KeyPair.from_seed(role.lower() + "-" + secrets.token_hex(8), secrets.token_bytes(32))
    write_private(directory / "operator.key", seal(key.seed))
    created = now_ms()
    body = {"profile": "itx-operator-card/1", "role": role, "iss": "urn:itx:party:" + role.lower(),
            "kid": key.kid, "public_key": key.public_hex, "endpoint": endpoint,
            "created_at": created, "expires_at": created + 90 * 86400000,
            "tls_ca": None, "tls_certificate": None}
    if role != "U":
        current = datetime.datetime.now(datetime.timezone.utc)
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        tls_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "itx " + key.kid)])
        ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(current - datetime.timedelta(minutes=5))
              .not_valid_after(current + datetime.timedelta(days=90))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .sign(ca_key, hashes.SHA256()))
        host = endpoint_url(endpoint).hostname
        try:
            san = x509.IPAddress(ipaddress.ip_address(host))
        except ValueError:
            san = x509.DNSName(host)
        service_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "itx service " + key.kid)])
        cert = (x509.CertificateBuilder().subject_name(service_name).issuer_name(name).public_key(tls_key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(current - datetime.timedelta(minutes=5))
                .not_valid_after(current + datetime.timedelta(days=90))
                .add_extension(x509.SubjectAlternativeName([san]), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .sign(ca_key, hashes.SHA256()))
        body.update(tls_ca=ca.public_bytes(serialization.Encoding.PEM).decode(),
                    tls_certificate=cert.public_bytes(serialization.Encoding.PEM).decode())
        password = secrets.token_hex(32).encode()
        write_private(directory / "tls.password", seal(password))
        write_private(directory / "tls.key", tls_key.private_bytes(serialization.Encoding.PEM,
                      serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(password)))
        write_private(directory / "tls.pem", body["tls_certificate"].encode())
    card = {"body": body, "signature": key.sign(canonical_json(body)).hex()}
    write_document(directory / "operator.json", card)
    return {"card": str(directory / "operator.json"), "fingerprint": fingerprint(card), "role": role}


def verify_card(card):
    body = card["body"]
    role = body["role"]
    if (body["profile"] != "itx-operator-card/1" or role not in tuple(ROLES)
            or body["iss"] != "urn:itx:party:" + role.lower()
            or not verify(bytes.fromhex(body["public_key"]), canonical_json(body), bytes.fromhex(card["signature"]))):
        raise ValueError("invalid operator card")
    if (type(body["created_at"]) is not int or type(body["expires_at"]) is not int
            or body["created_at"] >= body["expires_at"]):
        raise ValueError("invalid operator identity lifetime")
    if role != "U":
        host = endpoint_url(body["endpoint"]).hostname
        ca = x509.load_pem_x509_certificate(body["tls_ca"].encode())
        cert = x509.load_pem_x509_certificate(body["tls_certificate"].encode())
        cert.verify_directly_issued_by(ca)
        ca.verify_directly_issued_by(ca)
        if not ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            raise ValueError("operator CA lacks CA authority")
        if cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            raise ValueError("service certificate must be a leaf")
        sans = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        try:
            matches = ipaddress.ip_address(host) in sans.get_values_for_type(x509.IPAddress)
        except ValueError:
            matches = host.lower() in [v.lower() for v in sans.get_values_for_type(x509.DNSName)]
        if not matches or ExtendedKeyUsageOID.SERVER_AUTH not in cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value:
            raise ValueError("service certificate does not authorize this endpoint")
        for certificate in (ca, cert):
            if (int(certificate.not_valid_before_utc.timestamp() * 1000) > body["created_at"]
                    or int(certificate.not_valid_after_utc.timestamp() * 1000) + 1000 < body["expires_at"]):
                raise ValueError("operator identity outlives its TLS certificate")
    elif any(body.get(k) is not None for k in ("endpoint", "tls_ca", "tls_certificate")):
        raise ValueError("U cannot declare a service TLS endpoint")
    return body


def operator_key(directory):
    directory = Path(directory)
    card = read_document(directory / "operator.json")
    body = verify_card(card)
    key = KeyPair.from_seed(body["kid"], unseal((directory / "operator.key").read_bytes()))
    if key.public_hex != body["public_key"]:
        raise ValueError("local operator key does not match public card")
    return card, key


def propose(cards, *, previous=None, checkpoint=None, model_id=MODEL_ID, model_hash=MODEL_HASH,
            model_kind="deterministic_mock", model_name=None, pre_exec=False):
    members = {}
    for card in cards:
        b = verify_card(card)
        if b["role"] in members:
            raise ValueError("duplicate role")
        if b["expires_at"] <= now_ms():
            raise ValueError("operator card expired")
        members[b["role"]] = card
    if not set("URMT") <= set(members):
        raise ValueError("U, R, M and T must participate")
    if len({c["body"]["public_key"] for c in members.values()}) != len(members):
        raise ValueError("each role must have its own signing key")
    if len(model_hash) != 64 or len(bytes.fromhex(model_hash)) != 32 or model_kind not in ("deterministic_mock", "ollama"):
        raise ValueError("invalid model agreement")
    if model_kind == "ollama" and not model_name:
        raise ValueError("Ollama model name is required")
    if model_kind == "ollama" and (model_hash == MODEL_HASH or model_id == MODEL_ID):
        raise ValueError("an actual-model deployment needs its own model ID and declared artifact hash")
    previous_hash, epoch, deployment_id = None, 1, secrets.token_hex(12)
    if previous:
        verify_deployment(previous)
        previous_hash = fingerprint(previous["proposal"])
        epoch = previous["proposal"]["epoch"] + 1
        deployment_id = previous["proposal"]["deployment_id"]
        if not checkpoint:
            raise ValueError("successor epoch requires the previous T checkpoint")
        verify_head(checkpoint, trust_from_config(configuration(previous)))
    elif checkpoint:
        raise ValueError("checkpoint requires a previous deployment")
    return {"profile": "itx-deployment/1", "deployment_id": deployment_id, "epoch": epoch,
            "previous_hash": previous_hash, "previous_checkpoint": checkpoint,
            "created_at": now_ms(), "expires_at": min(c["body"]["expires_at"] for c in members.values()),
            "cards": members, "model_id": model_id, "model_hash": model_hash, "model_kind": model_kind,
            "model_name": model_name, "pre_exec": bool(pre_exec), "strict_timeout_ms": 2500,
            "max_log_entries": 100000, "retention_days": 30}


def endorse(directory, proposal, expected_fingerprint, previous_config=None):
    if fingerprint(proposal) != expected_fingerprint:
        raise ValueError("proposal fingerprint differs from the reviewed deployment")
    card, key = operator_key(directory)
    role = card["body"]["role"]
    if proposal["cards"].get(role) != card:
        raise ValueError("proposal does not contain this operator's exact public card")
    message = {"profile": "itx-deployment-endorsement/1", "role": role, "deployment_hash": expected_fingerprint}
    result = {"body": message, "signature": key.sign(canonical_json(message)).hex(), "previous_signature": None}
    if proposal["previous_hash"]:
        if not previous_config:
            raise ValueError("key rotation requires the locally pinned previous configuration")
        from .common import key_for, load_config
        cfg = load_config(previous_config)
        if cfg["role"] != role or cfg.get("deployment_hash") != proposal["previous_hash"]:
            raise ValueError("previous role or pinned deployment does not match")
        result["previous_signature"] = key_for(cfg).sign(canonical_json(message)).hex()
    return result


def assemble(proposal, endorsements, previous=None):
    bundle = {"proposal": proposal, "endorsements": endorsements, "previous": previous}
    verify_deployment(bundle)
    return bundle


def verify_deployment(bundle, depth=0):
    if depth > 32:
        raise ValueError("deployment history is too deep")
    p = bundle["proposal"]
    if p["profile"] != "itx-deployment/1" or type(p["epoch"]) is not int or p["epoch"] < 1:
        raise ValueError("invalid deployment profile")
    if not set("URMT") <= set(p["cards"]) <= set(ROLES):
        raise ValueError("invalid deployment roles")
    if (type(p["created_at"]) is not int or type(p["expires_at"]) is not int or p["created_at"] >= p["expires_at"]
            or type(p["pre_exec"]) is not bool or not 100 <= p["strict_timeout_ms"] <= 10000
            or not 1 <= p["max_log_entries"] <= 100000 or not 1 <= p["retention_days"] <= 3650):
        raise ValueError("invalid deployment lifetime or limits")
    for role, card in p["cards"].items():
        if verify_card(card)["role"] != role:
            raise ValueError("role substitution")
        if p["expires_at"] > card["body"]["expires_at"]:
            raise ValueError("deployment outlives an operator identity")
    if len({c["body"]["public_key"] for c in p["cards"].values()}) != len(p["cards"]):
        raise ValueError("roles share a signing key")
    service_cards = [c["body"] for r, c in p["cards"].items() if r != "U"]
    if len({c["tls_ca"] for c in service_cards}) != len(service_cards):
        raise ValueError("services must use separately scoped TLS authorities")
    if (not isinstance(p["model_id"], str) or not p["model_id"] or len(bytes.fromhex(p["model_hash"])) != 32
            or p["model_kind"] not in ("deterministic_mock", "ollama")
            or (p["model_kind"] == "ollama" and (not p["model_name"] or p["model_id"] == MODEL_ID or p["model_hash"] == MODEL_HASH))):
        raise ValueError("invalid endorsed model agreement")
    previous = bundle["previous"]
    if previous:
        verify_deployment(previous, depth + 1)
        old = previous["proposal"]
        if (p["previous_hash"] != fingerprint(old) or p["epoch"] != old["epoch"] + 1
                or p["deployment_id"] != old["deployment_id"] or set(p["cards"]) != set(old["cards"])):
            raise ValueError("broken deployment history")
        verify_head(p["previous_checkpoint"], trust_from_config(configuration(previous)))
    elif p["previous_hash"] or p["epoch"] != 1:
        raise ValueError("missing previous deployment")
    received = {}
    for endorsement in bundle["endorsements"]:
        role = endorsement["body"]["role"]
        expected = {"profile": "itx-deployment-endorsement/1", "role": role, "deployment_hash": fingerprint(p)}
        if role in received or role not in p["cards"] or endorsement["body"] != expected:
            raise ValueError("invalid or duplicate endorsement")
        encoded = canonical_json(expected)
        if not verify(bytes.fromhex(p["cards"][role]["body"]["public_key"]), encoded, bytes.fromhex(endorsement["signature"])):
            raise ValueError("invalid new-key endorsement")
        if previous and not verify(bytes.fromhex(previous["proposal"]["cards"][role]["body"]["public_key"]),
                                   encoded, bytes.fromhex(endorsement["previous_signature"] or "00")):
            raise ValueError("rotation not authorized by the previous key")
        received[role] = True
    if set(received) != set(p["cards"]):
        raise ValueError("every operator must endorse the deployment")
    return fingerprint(p)


def configuration(bundle):
    p = bundle["proposal"]
    history, current = [], bundle
    while current:
        cp = current["proposal"]
        history.append({"epoch": cp["epoch"], "deployment_hash": fingerprint(cp),
                        "previous_hash": cp["previous_hash"], "previous_checkpoint": cp["previous_checkpoint"]})
        current = current["previous"]
    return {"version": 1, "lab": False, "created_at": p["created_at"], "policy_expires_at": p["expires_at"],
            "log_id": f"epoch-{p['deployment_id']}-{p['epoch']}", "epoch": p["epoch"],
            "deployment_hash": fingerprint(p), "deployment_history": history,
            "identities": {r: {k: c["body"][k] for k in ("iss", "kid", "public_key")} for r, c in p["cards"].items()},
            "endpoints": {r: c["body"]["endpoint"] for r, c in p["cards"].items() if r != "U"},
            "model_id": p["model_id"], "model_hashes": {p["model_id"]: p["model_hash"]},
            "model_kind": p["model_kind"], "model_name": p["model_name"], "pre_exec": p["pre_exec"],
            "strict_timeout_ms": p["strict_timeout_ms"], "queue_capacity": 256,
            "max_log_entries": p["max_log_entries"], "retention_days": p["retention_days"],
            "governance": "separately_provisioned_keys"}


def activate(directory, bundle, expected_fingerprint, *, bind="127.0.0.1", model_endpoint=None, previous_config=None):
    directory = Path(directory).resolve()
    actual = verify_deployment(bundle)
    if actual != expected_fingerprint:
        raise ValueError("deployment fingerprint differs from the independently reviewed value")
    card, key = operator_key(directory)
    role = card["body"]["role"]
    if bundle["proposal"]["cards"].get(role) != card or bundle["proposal"]["expires_at"] <= now_ms():
        raise ValueError("deployment is expired or does not bind this local operator")
    if role == "M" and bundle["proposal"]["model_kind"] == "ollama" and not model_endpoint:
        raise ValueError("M must configure its local Ollama endpoint")
    old_config = None
    if bundle["proposal"]["previous_hash"]:
        from .common import load_config
        if not previous_config:
            raise ValueError("rotation activation requires the local previous configuration")
        old_config = load_config(previous_config)
        if old_config["role"] != role or old_config.get("deployment_hash") != bundle["proposal"]["previous_hash"]:
            raise ValueError("previous local role or deployment does not match")
    active_path = directory / "active.json"
    if active_path.exists():
        active = read_document(active_path)
        if active["deployment_hash"] == actual:
            return {**active, "unchanged": True}
        if active["deployment_hash"] != bundle["proposal"]["previous_hash"]:
            raise ValueError("cannot silently replace an established deployment lineage")
    target = directory / "epochs" / actual
    if target.exists():
        raise ValueError("epoch directory already exists; inspect the interrupted activation")
    target.mkdir(parents=True)
    cfg = {**configuration(bundle), "role": role, "bind": bind,
           "port": endpoint_url(card["body"]["endpoint"]).port if role != "U" else 0,
           "ca_file": "ca-T.pem", "ca_files": {}, "deployment_file": "deployment.json"}
    for peer, item in bundle["proposal"]["cards"].items():
        if peer != "U":
            cfg["ca_files"][peer] = f"ca-{peer}.pem"
            write_private(target / f"ca-{peer}.pem", item["body"]["tls_ca"].encode())
    write_private(target / "identity.key", seal(key.seed))
    if role != "U":
        for name in ("tls.key", "tls.password", "tls.pem"):
            write_private(target / name, (directory / name).read_bytes())
        cfg.update(tls_cert="tls.pem", tls_key="tls.key", tls_password_file="tls.password")
    if role == "M" and cfg["model_kind"] == "ollama":
        if not model_endpoint:
            raise ValueError("M must configure its local Ollama endpoint")
        cfg["model_endpoint"] = model_endpoint
    write_document(target / "deployment.json", bundle)
    write_document(target / "config.json", cfg)
    if old_config:
        from .common import key_for
        old_key = key_for(old_config)
        body = {"profile": "itx-retirement/1", "deployment_hash": old_config["deployment_hash"],
                "role": role, "successor_hash": actual, "retired_at": now_ms()}
        retirement = Path(old_config["directory"]) / "retirement.json"
        if retirement.exists():
            if read_document(retirement)["body"]["successor_hash"] != actual:
                raise ValueError("previous epoch was already retired to another successor")
        else:
            write_document(retirement, {"body": body, "signature": old_key.sign(canonical_json(body)).hex()})
    result = {"deployment_hash": actual, "config_path": str(target / "config.json"), "epoch": cfg["epoch"]}
    tmp = directory / "active.tmp"
    if tmp.exists():
        raise ValueError("unfinished activation metadata exists")
    write_document(tmp, result)
    tmp.replace(active_path)
    return result


def assert_active(config):
    if (Path(config["directory"]) / "retirement.json").exists():
        # Existence is enough to fail closed. No invalid retirement record re-enables traffic.
        raise ValueError("이전 배포 세대가 폐기되었습니다. 승인된 새 설정으로 전환하세요.")
