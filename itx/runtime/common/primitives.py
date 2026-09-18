"""Runtime profile constants, canonical input and commitment helpers."""
from __future__ import annotations

import json
import time

from itx.crypto import HAS_CRYPTOGRAPHY, canonical_json, commit_hex, content_hash_hex
from itx.statements import CT_CONTRACT, CT_OBSERVATION, CT_RECEIPT, CT_RELAY, CT_VERDICT

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
