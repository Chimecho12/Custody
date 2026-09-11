"""승인 가능한 변환 레지스트리.

05 검토서 §4.2: 변환 식별자와 두 해시만으로는 "약속한 변환만 수행했다"를 증명할 수 없다.
첫 버전은 두 경우만 검증한다.
1. 무변환(identity): 입력·출력 커밋이 같아야 한다.
2. 공개된 결정적 변환: 검사자(또는 사용자)가 결과를 재계산한다. 변환 정의의 해시를 고정한다.

비공개 변환(예: 중개자의 비밀 시스템 프롬프트 삽입)은 '선언 확인·관계 미검증' 으로만 남는다.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable

from itx.crypto import sha256_hex

IDENTITY = "identity"
PUBLIC_FORMATTER_V1 = "public-formatter-v1"


def identity(obj: Any) -> Any:
    return obj


def public_formatter_v1(request: dict[str, Any]) -> dict[str, Any]:
    """공개된 결정적 변환의 예. 고정 시스템 프롬프트를 붙인다. 누구나 재계산할 수 있다."""
    out = dict(request)
    out["system"] = "You are a concise assistant. Answer in Korean."
    out["formatter"] = PUBLIC_FORMATTER_V1
    return out


REQUEST_TRANSFORMS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    IDENTITY: identity,
    PUBLIC_FORMATTER_V1: public_formatter_v1,
}

RESPONSE_TRANSFORMS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    IDENTITY: identity,
}


def is_recomputable_request_transform(name: str) -> bool:
    return name in REQUEST_TRANSFORMS


def transform_definition_hash(name: str) -> str | None:
    """검사에 쓴 변환 정의(소스)의 해시. 판정에 함께 기록한다."""
    fn = REQUEST_TRANSFORMS.get(name) or RESPONSE_TRANSFORMS.get(name)
    if fn is None:
        return None
    return sha256_hex(inspect.getsource(fn).encode("utf-8"))
