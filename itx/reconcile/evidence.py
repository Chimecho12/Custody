"""대조 입력 자료 구조."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from itx.statements import SignedStatement


@dataclass
class PrivateEvidence:
    """사용자가 제3자에게만 인증 채널로 넘기는 증거 묶음. 로그에 올리지 않는다.

    - salt: 요청별 32바이트 솔트 (hex). 로그의 커밋을 원문 해시와 연결하는 열쇠.
    - request_hash: H(canonical(request)) (hex, 비솔트). T 만 안다.
    - response_hash: 사용자가 실제 받은 응답의 H(canonical(response)).
    - expected_request_commits: 계약이 허용한 공개 결정적 변환마다 사용자가 미리 계산한
      commit(salt, H(canonical(transform(request)))). 원문 없이도 E4 를 재계산할 수 있게 한다.
    """

    salt: str
    request_hash: str
    response_hash: str | None = None
    expected_request_commits: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "salt": self.salt,
            "request_hash": self.request_hash,
            "response_hash": self.response_hash,
            "expected_request_commits": dict(self.expected_request_commits),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PrivateEvidence:
        return cls(
            salt=d["salt"],
            request_hash=d["request_hash"],
            response_hash=d.get("response_hash"),
            expected_request_commits=dict(d.get("expected_request_commits", {})),
        )


@dataclass
class StatementRef:
    """판정이 근거로 삼은 진술의 고정 참조. URL 이 아니라 해시·인덱스로 고정한다."""

    content_type: str
    iss: str
    kid: str
    statement_hash: str
    log_index: int | None
    registered_at: int | None
    signature_valid: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_type": self.content_type,
            "iss": self.iss,
            "kid": self.kid,
            "statement_hash": self.statement_hash,
            "log_index": self.log_index,
            "registered_at": self.registered_at,
            "signature_valid": self.signature_valid,
        }


@dataclass
class EvidenceSet:
    sub: str
    contract: SignedStatement | None = None
    relay: SignedStatement | None = None
    receipt: SignedStatement | None = None
    observation: SignedStatement | None = None
    manifest: SignedStatement | None = None
    private: PrivateEvidence | None = None
    reference_model_hashes: dict[str, str] = field(default_factory=dict)
    refs: list[StatementRef] = field(default_factory=list)
    invalid_signatures: list[StatementRef] = field(default_factory=list)
    #: 서명은 유효하지만 발행자가 그 유형의 진술을 낼 권한이 없는 진술. 증거로 쓰지 않는다.
    unauthorized_issuers: list[StatementRef] = field(default_factory=list)
    receipt_source: str = "registered"  # registered | presented_to_user | none
    now: int = 0

    @property
    def present_parties(self) -> list[str]:
        out = []
        if self.contract is not None or self.observation is not None:
            out.append("U")
        if self.relay is not None:
            out.append("R")
        if self.receipt is not None:
            out.append("M")
        return out

    @property
    def cooperation_set(self) -> str:
        return "+".join(self.present_parties) if self.present_parties else "none"

    # 편의 접근자 -----------------------------------------------------------
    @property
    def c(self) -> dict[str, Any] | None:
        return self.contract.payload if self.contract else None

    @property
    def r(self) -> dict[str, Any] | None:
        return self.relay.payload if self.relay else None

    @property
    def m(self) -> dict[str, Any] | None:
        return self.receipt.payload if self.receipt else None

    @property
    def o(self) -> dict[str, Any] | None:
        return self.observation.payload if self.observation else None
