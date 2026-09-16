"""Signed audit packages and optional recipient encryption using standard primitives."""
from __future__ import annotations

import base64
import json
import secrets
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from itx.crypto import canonical_json, verify

from .auditing import MAX_AUDIT_BYTES, fingerprint, verify_export
from .common import json_loads, now_ms, seal, unseal, write_private


def read_document(path):
    path = Path(path)
    if path.stat().st_size > MAX_AUDIT_BYTES * 2:
        raise ValueError("document exceeds the local size limit")
    return json_loads(path.read_bytes())


def write_document(path, value):
    path = Path(path)
    write_private(path, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))
    return str(path.resolve())


def create_recipient(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise ValueError("recipient identity needs an empty directory")
    key = X25519PrivateKey.generate()
    public = {"profile": "itx-audit-recipient/1", "public_key": key.public_key().public_bytes_raw().hex()}
    write_private(directory / "recipient.key", seal(key.private_bytes_raw()))
    write_document(directory / "recipient.json", public)
    return {"path": str((directory / "recipient.json").resolve()), "fingerprint": fingerprint(public)}


def _derive(shared):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"itx-audit-package/1").derive(shared)


def encrypt_package(value, recipient, expected_fingerprint):
    if fingerprint(recipient) != expected_fingerprint or recipient.get("profile") != "itx-audit-recipient/1":
        raise ValueError("auditor recipient fingerprint does not match")
    public = X25519PublicKey.from_public_bytes(bytes.fromhex(recipient["public_key"]))
    ephemeral = X25519PrivateKey.generate()
    header = {"profile": "itx-audit-encrypted/1", "recipient": recipient["public_key"],
              "ephemeral": ephemeral.public_key().public_bytes_raw().hex(), "nonce": secrets.token_bytes(12).hex()}
    ciphertext = AESGCM(_derive(ephemeral.exchange(public))).encrypt(bytes.fromhex(header["nonce"]),
                  canonical_json(value), canonical_json(header))
    return {**header, "ciphertext": base64.b64encode(ciphertext).decode("ascii")}


def decrypt_package(envelope, recipient_directory):
    if set(envelope) != {"profile", "recipient", "ephemeral", "nonce", "ciphertext"}:
        raise ValueError("invalid encrypted package")
    key = X25519PrivateKey.from_private_bytes(unseal((Path(recipient_directory) / "recipient.key").read_bytes()))
    if key.public_key().public_bytes_raw().hex() != envelope["recipient"]:
        raise ValueError("this package is for a different auditor")
    header = {k: v for k, v in envelope.items() if k != "ciphertext"}
    shared = key.exchange(X25519PublicKey.from_public_bytes(bytes.fromhex(envelope["ephemeral"])))
    plaintext = AESGCM(_derive(shared)).decrypt(bytes.fromhex(envelope["nonce"]),
        base64.b64decode(envelope["ciphertext"], validate=True), canonical_json(header))
    return json_loads(plaintext)


def build_package(agent, include_private=False):
    export = agent.audit_export()
    private, versions = agent.private_evidence() if include_private else ({}, {})
    old = agent.store.get("checkpoint")
    body = {"profile": "itx-audit-package/1", "created_at": now_ms(), "log_export": export,
            "trust_fingerprint": fingerprint(agent.trust()), "private_by_sub": private,
            "private_by_hash": versions, "private_included": include_private,
            "anchors": [] if old is None else [{"tree_size": old["tree_size"], "root_hash": old["root_hash"], "anchored_at": old["time"]}],
            "witness_receipts": [v for _, v in agent.store.items("witness:")],
            "deployment_history": agent.config.get("deployment_history", []),
            "deployment_bundle": read_document(agent.config["deployment_file"]) if agent.config.get("deployment_file") else None}
    return {"body": body, "u_signature": agent.key.sign(canonical_json(body)).hex()}


def verify_package(value, trust, expected_fingerprint, recipient_directory=None):
    if fingerprint(trust) != expected_fingerprint or trust.get("profile") != "itx-audit-trust/1":
        raise ValueError("independently supplied trust fingerprint does not match")
    if value.get("profile") == "itx-audit-encrypted/1":
        if not recipient_directory:
            raise ValueError("auditor decryption identity required")
        value = decrypt_package(value, recipient_directory)
    if set(value) != {"body", "u_signature"} or value["body"].get("profile") != "itx-audit-package/1":
        raise ValueError("invalid audit package")
    body = value["body"]
    if (body["trust_fingerprint"] != expected_fingerprint
            or not verify(bytes.fromhex(trust["identities"]["U"]["public_key"]), canonical_json(body), bytes.fromhex(value["u_signature"]))):
        raise ValueError("audit package signature or trust binding is invalid")
    epochs = 0
    if trust.get("deployment_hash"):
        from .auditing import trust_from_config
        from .enrollment import configuration, verify_deployment
        bundle = body.get("deployment_bundle")
        if not bundle or verify_deployment(bundle) != trust["deployment_hash"]:
            raise ValueError("missing or invalid independently pinned deployment agreement")
        config = configuration(bundle)
        if fingerprint(trust_from_config(config)) != expected_fingerprint or body["deployment_history"] != config["deployment_history"]:
            raise ValueError("deployment history differs from the pinned audit trust")
        epochs = len(config["deployment_history"])
    report = verify_export(body["log_export"], trust, anchors=body["anchors"],
                           private=body["private_by_sub"], private_by_hash=body["private_by_hash"])
    if body.get("witness_receipts"):
        from .witness import verify_witness_receipt
        tree = __import__('itx.ts', fromlist=['MerkleTree']).MerkleTree()
        from itx.statements import SignedStatement
        for e in body["log_export"]["entries"]:
            tree.append(SignedStatement.from_dict(e["statement"]).leaf_bytes())
        for receipt in body["witness_receipts"]:
            verify_witness_receipt(receipt, trust)
            head = receipt["body"]["head"]
            if head["tree_size"] > tree.size or tree.root_at(head["tree_size"]).hex() != head["root_hash"]:
                raise ValueError("witness checkpoint contradicts the exported log")
    report.update(package_signature_valid=True, private_included=body["private_included"],
                  deployment_epochs_verified=epochs,
                  witness_receipts_checked=len(body.get("witness_receipts", [])))
    return report
