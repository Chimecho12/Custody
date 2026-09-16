"""CBOR · COSE_Sign1 — 자체 JSON 프로파일과 같은 내용을 표준 바이너리로 낸다.

한계 13 이 말하는 「구조를 JSON 으로 옮긴 자체 프로파일」의 반대편이다. 이 패키지가
있어도 표준 준수를 주장하지는 않는다. 주장하는 것은 `conformance.run()` 이 실제로
통과시킨 벡터의 수뿐이고, 외부 도구 검증은 여전히 미실행으로 남는다.
"""
from .cbor import CBORError, Tagged, decode, diagnostic, encode, hex_dump
from .conformance import run as run_conformance
from .profile import encodings, from_sign1, to_sign1
from .sign1 import ALG_EDDSA, TAG_SIGN1, COSEError, parse, sig_structure, sign, verify_signature

__all__ = [
    "ALG_EDDSA",
    "TAG_SIGN1",
    "CBORError",
    "COSEError",
    "Tagged",
    "decode",
    "diagnostic",
    "encode",
    "encodings",
    "from_sign1",
    "hex_dump",
    "parse",
    "run_conformance",
    "sig_structure",
    "sign",
    "to_sign1",
    "verify_signature",
]
