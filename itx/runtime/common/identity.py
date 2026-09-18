"""Pinned signing identities, registration policy and statement authentication."""
from __future__ import annotations

from pathlib import Path

from itx.crypto import KeyPair
from itx.statements import ALL_CONTENT_TYPES, SignedStatement, issue, validate_payload
from itx.statements.schemas import policy_payload

from .primitives import ISS, TYPES, now_ms
from .protection import unseal


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
