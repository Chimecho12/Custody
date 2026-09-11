"""서명된 진술(statement) 계층.

RFC 9943(SCITT) 의 Signed Statement 구조를 JSON 으로 옮긴 프로젝트 로컬 프로파일이다.
보호 헤더에 해당하는 iss/sub/content_type/kid/issued_at 와 페이로드를 함께 서명한다.
COSE_Sign1 로의 변환은 어댑터 지점으로 남긴다 (docs/limits.md).
"""
from .envelope import (
    SignedStatement,
    issue,
    CT_CONTRACT,
    CT_RELAY,
    CT_RECEIPT,
    CT_OBSERVATION,
    CT_MANIFEST,
    CT_VERDICT,
    CT_POLICY,
    ALL_CONTENT_TYPES,
)
from .schemas import validate_payload, REQUIRED_FIELDS

__all__ = [
    "SignedStatement", "issue", "validate_payload", "REQUIRED_FIELDS",
    "CT_CONTRACT", "CT_RELAY", "CT_RECEIPT", "CT_OBSERVATION",
    "CT_MANIFEST", "CT_VERDICT", "CT_POLICY", "ALL_CONTENT_TYPES",
]
