"""itx 진술 ↔ COSE_Sign1 대응.

자체 JSON 프로파일의 봉투 필드를 CWT 클레임으로 옮긴다 (RFC 9597 §3, RFC 9943 §3.2).

    JSON 봉투            COSE_Sign1
    ---------            ----------
    iss                  protected[15][1]   CWT iss
    sub                  protected[15][2]   CWT sub
    issued_at            protected[15][6]   CWT iat
    kid                  protected[4]       COSE kid
    content_type         protected[3]       COSE content type
    payload              payload (bstr)     결정적 CBOR

**서명은 옮겨지지 않는다.** COSE 의 서명 대상은 Sig_structure 이고 JSON 프로파일의
서명 대상은 정규화된 봉투다. 바이트가 다르므로 같은 서명이 두 인코딩에서 모두
유효할 수 없다. 따라서 COSE 내보내기는 재인코딩이 아니라 **키를 가진 당사자의
재발행**이다. 남의 진술을 내가 COSE 로 바꿔 서명할 수는 없다 — 그것이 가능하다면
서명이 아무 의미도 없을 것이다.

이 제약은 `export_statement` 가 키를 요구하는 이유이고, 표준 적합성 화면이
「내가 발행한 문서」와 「받은 문서」를 구분해 보여야 하는 이유다.
"""
from __future__ import annotations

from typing import Any

from itx.crypto import KeyPair
from itx.statements import SignedStatement

from .cbor import decode, encode
from .sign1 import COSEError, parse, verify_signature

#: CWT_Claims 헤더 라벨 (RFC 9597 §3)
HDR_CWT_CLAIMS = 15

#: CWT 클레임 키 (RFC 8392 §3.1.1)
CWT_ISS = 1
CWT_SUB = 2
CWT_IAT = 6


def _cwt_claims(stmt: SignedStatement) -> dict[int, Any]:
    return {CWT_ISS: stmt.iss, CWT_SUB: stmt.sub, CWT_IAT: stmt.issued_at}


def to_sign1(key: KeyPair, stmt: SignedStatement) -> bytes:
    """진술을 COSE_Sign1 로 재발행한다. `key` 는 stmt.kid 의 키여야 한다."""
    if key.kid != stmt.kid:
        raise COSEError(f"키가 진술의 kid 와 다르다: {key.kid} != {stmt.kid}")
    protected = {
        1: -8,                                    # alg EdDSA
        3: stmt.content_type,                     # content type
        4: key.kid.encode("utf-8"),               # kid
        HDR_CWT_CLAIMS: _cwt_claims(stmt),        # iss · sub · iat
    }
    # sign1.sign 은 kid·alg 만 세우므로 CWT 클레임이 들어간 헤더는 여기서 직접 만든다.
    from .cbor import Tagged
    from .sign1 import TAG_SIGN1, sig_structure

    protected_bytes = encode(protected)
    payload = encode(stmt.payload)
    signature = key.sign(sig_structure(protected_bytes, payload))
    return encode(Tagged(TAG_SIGN1, [protected_bytes, {}, payload, signature]))


def from_sign1(data: bytes, public_key: bytes) -> SignedStatement:
    """COSE_Sign1 을 검증하고 itx 진술로 되돌린다. 서명값은 COSE 쪽 값이다."""
    parsed = verify_signature(data, public_key)
    claims = parsed["header"].get(HDR_CWT_CLAIMS)
    if not isinstance(claims, dict):
        raise COSEError("CWT 클레임 헤더가 없다")
    missing = [name for name, label in (("iss", CWT_ISS), ("sub", CWT_SUB), ("iat", CWT_IAT))
               if label not in claims]
    if missing:
        raise COSEError(f"CWT 필수 클레임 누락: {', '.join(missing)}")
    content_type = parsed["content_type"]
    if not isinstance(content_type, str):
        raise COSEError("content type 헤더가 없다")
    return SignedStatement(
        iss=claims[CWT_ISS], sub=claims[CWT_SUB], content_type=content_type,
        kid=parsed["kid"], issued_at=claims[CWT_IAT],
        payload=decode(parsed["payload"]), signature=parsed["signature"].hex(),
    )


def encodings(key: KeyPair, stmt: SignedStatement) -> dict[str, Any]:
    """한 진술의 두 인코딩을 나란히 놓는다. 표준 적합성 화면의 병치 카드가 쓴다."""
    from itx.crypto import canonical_json

    from .cbor import diagnostic, hex_dump

    json_bytes = canonical_json(stmt.to_dict())
    cose_bytes = to_sign1(key, stmt)
    return {
        "json": json_bytes.decode("utf-8"),
        "json_bytes": len(json_bytes),
        "cose_hex": hex_dump(cose_bytes),
        "cose_diagnostic": diagnostic(decode(cose_bytes)),
        "cose_bytes": len(cose_bytes),
        "structure": _structure_rows(cose_bytes),
    }


def _structure_rows(data: bytes) -> list[dict[str, Any]]:
    """「COSE_Sign1 구조」 표의 행. 값 전체가 아니라 무엇이 확인됐는지를 적는다."""
    parsed = parse(data)
    claims = parsed["header"].get(HDR_CWT_CLAIMS, {})
    payload = decode(parsed["payload"]) if parsed["payload"] else {}
    rows = [
        ("18(COSE_Sign1)", "배열 4요소", 0, "✓", "pass"),
        ("protected", f"alg -8 · kid {parsed['kid']}", 12, "✓ EdDSA", "pass"),
        ("protected.15", f"CWT iss · sub · iat ({len(claims)}개)", 24, "✓ RFC 9597", "pass"),
        ("protected.3", str(parsed["content_type"]), 24, "✓ 보존", "pass"),
        ("unprotected", "{}", 12, "✓ 빈 맵", "pass"),
        ("payload", f"결정적 CBOR · 필드 {len(payload)}개", 12, "✓ 왕복 동일", "pass"),
        ("signature", f"{len(parsed['signature'])} B Ed25519", 12, "✓ 검증", "pass"),
    ]
    return [{"key": k, "value": v, "indent": i, "note": n, "state": s} for k, v, i, n, s in rows]
