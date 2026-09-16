"""결정적 CBOR 인코딩 (RFC 8949 §4.2).

`itx.crypto.canonical` 이 JSON 에 대해 하는 일을 CBOR 에 대해 한다. 두 인코딩이
같은 제약을 공유하는 것이 중요하다 — 부동소수 금지, 키 정렬, 최소 길이. 그래야
같은 진술이 두 직렬화에서 같은 내용을 뜻한다고 말할 수 있다.

RFC 8949 §4.2.1 의 결정적 인코딩 요건 중 이 모듈이 지키는 것:

- 정수·길이는 표현 가능한 가장 짧은 형태로 (§4.2.1 첫째 항).
- 맵 키는 **인코딩된 바이트의 사전식 순서**로 정렬 (§4.2.1 둘째 항).
  JSON 쪽의 코드포인트 정렬과 결과가 다를 수 있다. 짧은 키가 먼저 오기 때문이다.
- 무한 길이(indefinite-length) 항목을 만들지도 받지도 않는다 (§4.2.1 셋째 항).
- 부동소수를 쓰지 않는다 (§4.2.2 의 축소 규칙을 구현하는 대신 아예 금지한다).

디코더를 함께 두는 이유는 왕복 재직렬화가 바이트 단위로 같은지를 검사하기
위해서다. 그 검사가 곧 적합성 벡터 cb-06 이다.
"""
from __future__ import annotations

from typing import Any

#: CBOR 주 타입 (RFC 8949 §3.1)
_UINT, _NINT, _BSTR, _TSTR, _ARRAY, _MAP, _TAG, _SIMPLE = range(8)


class CBORError(ValueError):
    """인코딩·디코딩이 결정적 프로파일을 벗어났을 때."""


class Tagged:
    """태그가 붙은 값 (RFC 8949 §3.4). COSE_Sign1 의 태그 18 에 쓴다."""

    __slots__ = ("tag", "value")

    def __init__(self, tag: int, value: Any):
        self.tag = tag
        self.value = value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Tagged) and self.tag == other.tag and self.value == other.value

    def __repr__(self) -> str:
        return f"Tagged({self.tag}, {self.value!r})"


def _head(major: int, value: int) -> bytes:
    """주 타입과 인자를 가장 짧은 형태로 쓴다 (§4.2.1)."""
    if value < 0:
        raise CBORError("negative argument")
    prefix = major << 5
    if value < 24:
        return bytes([prefix | value])
    for extra, limit in ((24, 0x100), (25, 0x10000), (26, 0x100000000), (27, 0x10000000000000000)):
        if value < limit:
            width = 1 << (extra - 24)
            return bytes([prefix | extra]) + value.to_bytes(width, "big")
    raise CBORError("argument does not fit in 64 bits")


def encode(obj: Any) -> bytes:
    """결정적 CBOR 바이트. 같은 객체는 항상 같은 바이트가 된다."""
    if obj is None:
        return b"\xf6"
    if obj is True:
        return b"\xf5"
    if obj is False:
        return b"\xf4"
    if isinstance(obj, float):
        # §4.2.2 의 축소 규칙 대신 금지를 택했다. 진술에 실수가 실릴 이유가 없다.
        raise CBORError("float not allowed in the itx deterministic profile")
    if isinstance(obj, int):
        return _head(_UINT, obj) if obj >= 0 else _head(_NINT, -obj - 1)
    if isinstance(obj, (bytes, bytearray)):
        return _head(_BSTR, len(obj)) + bytes(obj)
    if isinstance(obj, str):
        raw = obj.encode("utf-8")
        return _head(_TSTR, len(raw)) + raw
    if isinstance(obj, (list, tuple)):
        return _head(_ARRAY, len(obj)) + b"".join(encode(v) for v in obj)
    if isinstance(obj, dict):
        # 키를 먼저 인코딩한 뒤 그 바이트로 정렬한다 (§4.2.1). 값의 인코딩은 순서에 영향을 주지 않는다.
        items = []
        for key, value in obj.items():
            if not isinstance(key, (int, str, bytes, bytearray)):
                raise CBORError(f"unsupported map key type {type(key).__name__}")
            items.append((encode(key), value))
        if len({k for k, _ in items}) != len(items):
            raise CBORError("duplicate map key")
        items.sort(key=lambda pair: pair[0])
        return _head(_MAP, len(items)) + b"".join(k + encode(v) for k, v in items)
    if isinstance(obj, Tagged):
        return _head(_TAG, obj.tag) + encode(obj.value)
    raise CBORError(f"unsupported type {type(obj).__name__}")


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise CBORError("truncated input")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def argument(self, initial: int) -> int:
        """인자를 읽고, 최소 길이 인코딩이 아니면 거부한다 (벡터 cb-01)."""
        info = initial & 0x1F
        if info < 24:
            return info
        if info == 31:
            raise CBORError("indefinite length is not allowed")
        if info > 27:
            raise CBORError(f"reserved additional information {info}")
        width = 1 << (info - 24)
        value = int.from_bytes(self.take(width), "big")
        minimal = _head(initial >> 5, value)
        if len(minimal) != width + 1:
            raise CBORError("argument is not minimally encoded")
        return value

    def item(self) -> Any:
        initial = self.take(1)[0]
        major = initial >> 5
        if major == _SIMPLE:
            info = initial & 0x1F
            if info == 20:
                return False
            if info == 21:
                return True
            if info == 22:
                return None
            if info in (25, 26, 27):
                raise CBORError("float not allowed in the itx deterministic profile")
            raise CBORError(f"unsupported simple value {info}")
        argument = self.argument(initial)
        if major == _UINT:
            return argument
        if major == _NINT:
            return -argument - 1
        if major == _BSTR:
            return self.take(argument)
        if major == _TSTR:
            return self.take(argument).decode("utf-8")
        if major == _ARRAY:
            return [self.item() for _ in range(argument)]
        if major == _MAP:
            out: dict[Any, Any] = {}
            previous: bytes | None = None
            for _ in range(argument):
                start = self.pos
                key = self.item()
                encoded = self.data[start:self.pos]
                if isinstance(key, (bytes, bytearray)):
                    key = bytes(key)
                if key in out:
                    raise CBORError("duplicate map key")  # 벡터 cb-05
                if previous is not None and encoded <= previous:
                    raise CBORError("map keys are not in deterministic order")  # 벡터 cb-02
                previous = encoded
                out[key] = self.item()
            return out
        if major == _TAG:
            return Tagged(argument, self.item())
        raise CBORError(f"unsupported major type {major}")


def decode(data: bytes) -> Any:
    """결정적 프로파일을 지키는 CBOR 만 받는다. 나머지는 CBORError."""
    reader = _Reader(data)
    value = reader.item()
    if reader.pos != len(data):
        raise CBORError("trailing bytes after top-level item")
    return value


def diagnostic(obj: Any, indent: int = 0) -> str:
    """CBOR diagnostic notation (RFC 8949 §8). 화면에 바이트 대신 구조를 보일 때 쓴다."""
    pad = " " * indent
    if isinstance(obj, Tagged):
        return f"{obj.tag}({diagnostic(obj.value, indent)})"
    if isinstance(obj, (bytes, bytearray)):
        return f"h'{bytes(obj).hex()}'"
    if isinstance(obj, str):
        return '"' + obj.replace('\\', '\\\\').replace('"', '\\"') + '"'
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if obj is None:
        return "null"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, (list, tuple)):
        if not obj:
            return "[]"
        inner = ",\n".join(f"{pad}  {diagnostic(v, indent + 2)}" for v in obj)
        return f"[\n{inner}\n{pad}]"
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        pairs = sorted(obj.items(), key=lambda kv: encode(kv[0]))
        inner = ",\n".join(
            f"{pad}  {diagnostic(k, indent + 2)}: {diagnostic(v, indent + 2)}" for k, v in pairs
        )
        return f"{{\n{inner}\n{pad}}}"
    raise CBORError(f"unsupported type {type(obj).__name__}")


def hex_dump(data: bytes, width: int = 8) -> str:
    """화면에 그대로 붙일 수 있는 16진 덤프. 한 줄 width 바이트."""
    lines = []
    for start in range(0, len(data), width):
        lines.append(" ".join(f"{b:02x}" for b in data[start:start + width]))
    return "\n".join(lines)
