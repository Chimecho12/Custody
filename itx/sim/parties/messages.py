"""Wire messages and salted body commitments."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from itx.crypto import canonical_json, commit_hex, content_hash_hex
from itx.statements import SignedStatement


def _commit(salt: str | None, obj: Any) -> str | None:
    if salt is None:
        return None
    return commit_hex(salt, content_hash_hex(canonical_json(obj)))


@dataclass
class WireRequest:
    sub: str
    attempt_id: str
    nonce: str | None
    salt: str | None
    body: dict[str, Any]
    requested_model: str


@dataclass
class WireResponse:
    sub: str
    attempt_id: str
    body: dict[str, Any] | None
    inline_receipt: SignedStatement | None
    inline_relay: SignedStatement | None
    error: str | None = None
