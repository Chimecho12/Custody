"""JSON 정규화 (RFC 8785 JCS 와 호환되는 부분집합).

- 키는 정렬, 공백 없음, 비ASCII 는 그대로 UTF-8.
- 부동소수점은 허용하지 않는다 (JCS 의 숫자 직렬화 규칙을 구현하지 않았으므로
  결정성을 위해 정수·문자열·불·null·리스트·객체만 허용).
- 바이너리 값은 소문자 16진 문자열로 표현한다.

키 정렬은 Python 의 코드포인트 순서이며, JCS 는 UTF-16 코드 유닛 순서다.
BMP 밖 문자를 키로 쓰지 않는 한 두 순서는 같다. 이 프로파일은 키를 ASCII 로 제한한다.
"""
from __future__ import annotations

import json
from typing import Any


class CanonicalizationError(ValueError):
    pass


def _check(obj: Any, path: str) -> None:
    if obj is None or isinstance(obj, (bool, int, str)):
        return
    if isinstance(obj, float):
        raise CanonicalizationError(f"float not allowed at {path}")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise CanonicalizationError(f"non-string key at {path}")
            if not k.isascii():
                raise CanonicalizationError(f"non-ascii key {k!r} at {path}")
            _check(v, f"{path}.{k}")
        return
    if isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _check(v, f"{path}[{i}]")
        return
    raise CanonicalizationError(f"unsupported type {type(obj).__name__} at {path}")


def canonical_json(obj: Any) -> bytes:
    """결정적 직렬화. 같은 객체는 항상 같은 바이트가 된다."""
    _check(obj, "$")
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
