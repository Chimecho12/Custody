"""SHA-256 해시와 솔트 커밋.

설계 원칙 (05 검토서 §4.6): 공개 로그에는 비솔트 해시를 올리지 않는다.
당사자 진술에 실리는 값은 모두 `commit = H(salt || H(canonical(content)))` 형태다.
솔트는 사용자가 요청마다 생성해 경로 안 당사자(R, M)와 제3자(T)에게만 전달하고
로그에는 올리지 않는다. 따라서 로그만 보는 외부인은 후보 요청을 사전 대입해
원문을 복원할 수 없다.
"""
from __future__ import annotations

import hashlib


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash_hex(canonical_bytes: bytes) -> str:
    """정규화된 바이트의 해시. 솔트 없음. 로그에 직접 올리지 않는다."""
    return sha256_hex(canonical_bytes)


def commit(salt: bytes, content_hash: bytes) -> bytes:
    """솔트 커밋: H(salt || content_hash)."""
    if len(salt) != 32:
        raise ValueError("salt must be 32 bytes")
    if len(content_hash) != 32:
        raise ValueError("content_hash must be 32 bytes")
    return sha256(salt + content_hash)


def commit_hex(salt_hex: str, content_hash_hex_: str) -> str:
    return commit(bytes.fromhex(salt_hex), bytes.fromhex(content_hash_hex_)).hex()
