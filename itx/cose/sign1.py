"""COSE_Sign1 (RFC 9052 §4.2) — Ed25519 서명.

자체 JSON 프로파일과 **같은 내용**을 표준 바이너리로 낸다. 목적은 표준 준수 주장이
아니라, 이 저장소 밖의 도구가 같은 증거를 읽을 수 있게 하는 것이다. 무엇이 실제로
검증됐는지는 `itx.cose.conformance` 의 벡터가 센다.

구조 (RFC 9052 §4.2):

    COSE_Sign1 = [
        protected   : bstr,     ; 인코딩된 헤더 맵을 bstr 로 감싼다
        unprotected : header_map,
        payload     : bstr / nil,
        signature   : bstr
    ]

서명 대상은 메시지가 아니라 Sig_structure 다 (§4.4):

    Sig_structure = ["Signature1", protected, external_aad, payload]

이 구분이 중요하다. 같은 payload 라도 헤더가 다르면 서명이 달라지므로,
alg 를 바꿔치기하는 공격이 서명 검증에서 걸린다.
"""
from __future__ import annotations

from typing import Any

from itx.crypto import KeyPair, verify

from .cbor import CBORError, Tagged, decode, encode

#: COSE_Sign1 태그 (RFC 9052 §2)
TAG_SIGN1 = 18

#: 공통 헤더 라벨 (RFC 9052 §3.1)
HDR_ALG = 1
HDR_CRIT = 2
HDR_CONTENT_TYPE = 3
HDR_KID = 4

#: EdDSA (RFC 9053 §2.2). Ed25519 는 이 alg 아래 곡선으로 구분한다.
ALG_EDDSA = -8

#: 서명 컨텍스트 문자열 (RFC 9052 §4.4)
_CONTEXT = "Signature1"


class COSEError(ValueError):
    """COSE_Sign1 구조가 프로파일을 벗어났을 때."""


def sig_structure(protected: bytes, payload: bytes, external_aad: bytes = b"") -> bytes:
    """서명·검증이 실제로 다루는 바이트 (RFC 9052 §4.4).

    external_aad 는 이 프로파일에서 항상 빈 bstr 이다 (벡터 c1-06). 값을 쓰게 되면
    검증자도 같은 값을 알아야 하는데, 진술은 파일 하나로 전달되므로 그럴 경로가 없다.
    """
    return encode([_CONTEXT, protected, external_aad, payload])


def protected_header(kid: str, content_type: str | None = None) -> dict[int, Any]:
    """보호 헤더 맵. alg 와 kid 는 항상 보호되어야 한다 (바꿔치기 방지)."""
    header: dict[int, Any] = {HDR_ALG: ALG_EDDSA, HDR_KID: kid.encode("utf-8")}
    if content_type is not None:
        header[HDR_CONTENT_TYPE] = content_type
    return header


def sign(key: KeyPair, payload: bytes, *, content_type: str | None = None,
         external_aad: bytes = b"") -> bytes:
    """payload 바이트를 COSE_Sign1 로 감싸 서명한다. 태그 18 이 붙은 바이트를 낸다."""
    protected = encode(protected_header(key.kid, content_type))
    signature = key.sign(sig_structure(protected, payload, external_aad))
    return encode(Tagged(TAG_SIGN1, [protected, {}, payload, signature]))


def parse(data: bytes) -> dict[str, Any]:
    """구조만 읽는다. 서명 검증은 하지 않는다 — 구조 위반과 서명 실패를 구분하기 위해서다."""
    try:
        item = decode(data)
    except CBORError as error:
        raise COSEError(f"CBOR 디코딩 실패: {error}") from error

    if not isinstance(item, Tagged) or item.tag != TAG_SIGN1:
        raise COSEError("COSE_Sign1 태그 18 이 아니다")  # 벡터 c1-01
    body = item.value
    if not isinstance(body, list) or len(body) != 4:
        raise COSEError("COSE_Sign1 은 4요소 배열이어야 한다")  # 벡터 c1-01

    protected_bytes, unprotected, payload, signature = body
    if not isinstance(protected_bytes, bytes):
        raise COSEError("protected 헤더는 bstr 로 감싸야 한다")  # 벡터 c1-02
    if not isinstance(unprotected, dict):
        raise COSEError("unprotected 헤더는 맵이어야 한다")
    if payload is not None and not isinstance(payload, bytes):
        raise COSEError("payload 는 bstr 또는 nil 이어야 한다")  # 벡터 c1-08
    if not isinstance(signature, bytes):
        raise COSEError("signature 는 bstr 이어야 한다")

    try:
        header = decode(protected_bytes) if protected_bytes else {}
    except CBORError as error:
        raise COSEError(f"protected 헤더 디코딩 실패: {error}") from error
    if not isinstance(header, dict):
        raise COSEError("protected 헤더는 맵이어야 한다")

    overlap = set(header) & set(unprotected)
    if overlap:
        raise COSEError(f"보호·미보호 헤더에 같은 라벨이 있다: {sorted(overlap)}")  # 벡터 c1-10
    if HDR_CRIT in header:
        # critical 헤더를 이해하지 못하면 거부해야 한다 (RFC 9052 §3.1). 이 프로파일은 아무것도 이해하지 않는다.
        raise COSEError("critical 헤더를 지원하지 않는다")  # 벡터 c1-11
    if header.get(HDR_ALG) != ALG_EDDSA:
        raise COSEError(f"alg 는 EdDSA({ALG_EDDSA}) 여야 한다")  # 벡터 c1-03
    kid = header.get(HDR_KID)
    if not isinstance(kid, bytes):
        raise COSEError("kid 는 bstr 이어야 한다")  # 벡터 c1-04

    return {
        "protected_bytes": protected_bytes,
        "header": header,
        "unprotected": unprotected,
        "payload": payload,
        "signature": signature,
        "kid": kid.decode("utf-8"),
        "content_type": header.get(HDR_CONTENT_TYPE),
    }


def verify_signature(data: bytes, public_key: bytes, *, external_aad: bytes = b"") -> dict[str, Any]:
    """구조를 읽고 서명까지 검증한다. 실패하면 COSEError."""
    parsed = parse(data)
    if parsed["payload"] is None:
        raise COSEError("분리 서명(payload nil)은 원본 없이 검증할 수 없다")
    signed = sig_structure(parsed["protected_bytes"], parsed["payload"], external_aad)
    if not verify(public_key, signed, parsed["signature"]):
        raise COSEError("서명 검증 실패")  # 벡터 c1-09
    return parsed


def structure_rows(data: bytes) -> list[dict[str, Any]]:
    """화면의 「COSE_Sign1 구조」 표에 그대로 넣을 행. 값이 아니라 결론을 읽게 한다."""
    parsed = parse(data)
    header = parsed["header"]
    labels = {HDR_ALG: "alg", HDR_CONTENT_TYPE: "content type", HDR_KID: "kid"}
    named = ", ".join(f"{labels.get(k, k)}: {v.decode() if isinstance(v, bytes) else v}"
                      for k, v in sorted(header.items()))
    rows = [
        {"key": "18(COSE_Sign1)", "value": "배열 4요소", "indent": 0, "note": "✓", "state": "pass"},
        {"key": "protected", "value": f"{{{named}}}", "indent": 12,
         "note": "✓ alg EdDSA", "state": "pass"},
        {"key": "unprotected", "value": "{}" if not parsed["unprotected"] else "비어 있지 않음",
         "indent": 12, "note": "✓" if not parsed["unprotected"] else "!",
         "state": "pass" if not parsed["unprotected"] else "partial"},
    ]
    payload = parsed["payload"]
    claims = decode(payload) if payload else {}
    if isinstance(claims, dict):
        rows.append({"key": "payload", "value": f"CWT 클레임 {len(claims)}개", "indent": 12,
                     "note": "✓ 결정적", "state": "pass"})
    rows.append({"key": "signature", "value": f"{len(parsed['signature'])} B Ed25519", "indent": 12,
                 "note": "✓ 검증", "state": "pass"})
    return rows
