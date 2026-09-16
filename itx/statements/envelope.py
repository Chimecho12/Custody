"""공통 봉투: 발행자 서명 진술.

RFC 9943 §6 의 요구(보호 헤더에 iss·sub 필수, kid 필수)를 JSON 필드로 옮겼다.
`sub` 는 요청 식별자다. 세 당사자의 진술이 같은 sub 를 가져야 대조 대상이 된다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from itx.crypto import KeyPair, canonical_json, sha256_hex, verify

CT_CONTRACT = "application/vnd.itx.contract+json"
CT_RELAY = "application/vnd.itx.relay+json"
CT_RECEIPT = "application/vnd.itx.receipt+json"
CT_OBSERVATION = "application/vnd.itx.observation+json"
CT_MANIFEST = "application/vnd.itx.manifest+json"
CT_VERDICT = "application/vnd.itx.verdict+json"
CT_POLICY = "application/vnd.itx.policy+json"

ALL_CONTENT_TYPES = (
    CT_CONTRACT, CT_RELAY, CT_RECEIPT, CT_OBSERVATION, CT_MANIFEST, CT_VERDICT, CT_POLICY,
)


@dataclass
class SignedStatement:
    iss: str
    sub: str
    content_type: str
    kid: str
    issued_at: int  # 발행자 자기 주장 시각 (시뮬레이션 ms). 등록 시각과 구별한다.
    payload: dict[str, Any] = field(default_factory=dict)
    signature: str = ""  # hex

    # -- 서명 대상 ---------------------------------------------------------
    def to_be_signed(self) -> bytes:
        return canonical_json(
            {
                "iss": self.iss,
                "sub": self.sub,
                "content_type": self.content_type,
                "kid": self.kid,
                "issued_at": self.issued_at,
                "payload": self.payload,
            }
        )

    @property
    def statement_hash(self) -> str:
        """서명 대상 바이트의 SHA-256. 판정 진술의 evidence_refs 가 가리키는 값."""
        return sha256_hex(self.to_be_signed())

    def verify_with(self, public_key: bytes) -> bool:
        if not self.signature:
            return False
        try:
            sig = bytes.fromhex(self.signature)
        except ValueError:
            return False
        return verify(public_key, self.to_be_signed(), sig)

    # -- 직렬화 --------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "iss": self.iss,
            "sub": self.sub,
            "content_type": self.content_type,
            "kid": self.kid,
            "issued_at": self.issued_at,
            "payload": self.payload,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SignedStatement:
        return cls(
            iss=d["iss"],
            sub=d["sub"],
            content_type=d["content_type"],
            kid=d["kid"],
            issued_at=int(d["issued_at"]),
            payload=dict(d["payload"]),
            signature=d.get("signature", ""),
        )

    def leaf_bytes(self) -> bytes:
        """투명성 로그의 리프가 되는 바이트. 서명은 포함하고 등록 영수증은 포함하지 않는다
        (RFC 9943 §6.3: 미보호 헤더는 순서 포함 전 비어 있어야 한다)."""
        return canonical_json(self.to_dict())


def issue(
    key: KeyPair,
    *,
    iss: str,
    sub: str,
    content_type: str,
    payload: dict[str, Any],
    issued_at: int,
) -> SignedStatement:
    stmt = SignedStatement(
        iss=iss, sub=sub, content_type=content_type, kid=key.kid, issued_at=issued_at, payload=payload
    )
    stmt.signature = key.sign(stmt.to_be_signed()).hex()
    return stmt
