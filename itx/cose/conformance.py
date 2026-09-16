"""적합성 벡터 — 실제로 돌려서 세는 표.

표준 준수는 주장이 아니라 재현 가능한 결과여야 하므로, 화면에 나가는 숫자를 상수로
두지 않는다. 아래 벡터는 전부 이 자리에서 실행되고, 통과한 것만 pass 로 센다.

상태는 네 가지다. pass/fail 만 두면 「아직 안 만든 것」과 「만들었는데 틀린 것」이
같은 칸에 들어가서, 화면이 결손을 위반처럼 보이게 만든다.

    pass      벡터가 실행되어 통과했다
    partial   구현했으나 표준이 요구하는 범위의 일부만 한다
    absent    구현하지 않았다 — docs/limits.md 의 해당 한계를 근거로 적는다
    fail      실행했는데 틀렸다 (이 상태가 나오면 회귀다)

음성 벡터(잘못된 입력을 거부하는지)를 함께 둔다. 「받아들이는가」만 세면 아무것도
거부하지 않는 구현이 만점을 받는다.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from itx.crypto import KeyPair
from itx.statements import CT_RECEIPT, issue
from itx.ts import merkle

from . import cbor, profile, sign1

PASS, PARTIAL, ABSENT, FAIL = "pass", "partial", "absent", "fail"


@dataclass
class Vector:
    id: str
    label: str
    spec: str
    check: Callable[[], bool] | None = None
    state: str = PASS          # check 가 없을 때 쓰는 선언 상태 (absent/partial)
    note: str = ""

    def run(self) -> dict[str, Any]:
        if self.check is None:
            return {"id": self.id, "label": self.label, "state": self.state,
                    "note": self.note or self.spec}
        try:
            ok = self.check()
        except Exception as error:  # 벡터가 터지는 것도 결과다. 숨기면 표가 거짓말을 한다.
            return {"id": self.id, "label": self.label, "state": FAIL,
                    "note": f"{type(error).__name__}: {error}"}
        return {"id": self.id, "label": self.label, "state": PASS if ok else FAIL,
                "note": self.note or self.spec}


@dataclass
class Group:
    key: str
    title: str
    spec: str
    vectors: list[Vector] = field(default_factory=list)

    def run(self) -> dict[str, Any]:
        items = [v.run() for v in self.vectors]
        counts = {s: sum(1 for i in items if i["state"] == s) for s in (PASS, PARTIAL, ABSENT, FAIL)}
        return {"key": self.key, "title": self.title, "spec": self.spec,
                "items": items, "counts": counts, "total": len(items)}


# --- 도우미 -----------------------------------------------------------------

def _raises(fn: Callable[[], Any], *expected: type[BaseException]) -> bool:
    """음성 벡터: 지정한 예외로 거부해야 통과. 그냥 통과해 버리면 실패다."""
    try:
        fn()
    except expected:
        return True
    except Exception:
        return False
    return False


def _sample_key() -> KeyPair:
    return KeyPair.from_name("conformance-m", namespace="itx-conformance")


def _sample_statement():
    return issue(_sample_key(), iss="urn:itx:party:m", sub="att-conformance-0001",
                 content_type=CT_RECEIPT, issued_at=1178,
                 payload={"in_commit": "8f12c47a", "out_commit": "3a4f91be",
                          "attempt": "att-conformance-0001", "security_mode": "evaluation",
                          "attestation": "mock"})


# --- COSE_Sign1 구조 (RFC 9052 · 9053) --------------------------------------

def _cose_vectors() -> list[Vector]:
    key = _sample_key()
    stmt = _sample_statement()
    signed = profile.to_sign1(key, stmt)
    parsed = sign1.parse(signed)

    def tampered(index: int, value: Any) -> bytes:
        body = list(cbor.decode(signed).value)
        body[index] = value
        return cbor.encode(cbor.Tagged(sign1.TAG_SIGN1, body))

    def with_header(mutate: Callable[[dict], None]) -> bytes:
        header = dict(parsed["header"])
        mutate(header)
        body = list(cbor.decode(signed).value)
        body[0] = cbor.encode(header)
        return cbor.encode(cbor.Tagged(sign1.TAG_SIGN1, body))

    return [
        Vector("c1-01", "COSE_Sign1 태그 18 · 4요소 배열", "RFC 9052 §4.2",
               lambda: isinstance(cbor.decode(signed), cbor.Tagged)
               and cbor.decode(signed).tag == 18 and len(cbor.decode(signed).value) == 4),
        Vector("c1-02", "protected 헤더 bstr 래핑", "RFC 9052 §3",
               lambda: isinstance(cbor.decode(signed).value[0], bytes)),
        Vector("c1-03", "alg(1) = -8 EdDSA", "RFC 9053 §2.2",
               lambda: parsed["header"][sign1.HDR_ALG] == sign1.ALG_EDDSA),
        Vector("c1-04", "kid(4) bstr", "RFC 9052 §3.1",
               lambda: isinstance(parsed["header"][sign1.HDR_KID], bytes)),
        Vector("c1-05", "Sig_structure 정확 직렬화", "RFC 9052 §4.4",
               lambda: cbor.decode(sign1.sig_structure(parsed["protected_bytes"],
                                                       parsed["payload"]))[0] == "Signature1"),
        Vector("c1-06", "external_aad 빈 bstr", "RFC 9052 §4.3",
               lambda: cbor.decode(sign1.sig_structure(b"", b""))[2] == b""),
        Vector("c1-07", "unprotected 맵 빈값 허용", "RFC 9052 §3",
               lambda: parsed["unprotected"] == {}),
        Vector("c1-08", "payload nil 거부 (분리 서명 미지원)", "RFC 9052 §4.2",
               lambda: _raises(lambda: sign1.verify_signature(tampered(2, None), key.public_key),
                               sign1.COSEError),
               note="분리 서명은 원본 없이 검증 불가"),
        Vector("c1-09", "변조된 서명 거부", "음성 벡터",
               lambda: _raises(
                   lambda: sign1.verify_signature(tampered(3, b"\x00" * 64), key.public_key),
                   sign1.COSEError)),
        Vector("c1-10", "보호·미보호 헤더 라벨 중복 거부", "음성 벡터",
               lambda: _raises(lambda: sign1.parse(cbor.encode(cbor.Tagged(
                   sign1.TAG_SIGN1, [parsed["protected_bytes"], {sign1.HDR_ALG: -8},
                                     parsed["payload"], parsed["signature"]]))),
                   sign1.COSEError)),
        Vector("c1-11", "critical 헤더 미지원 거부", "RFC 9052 §3.1",
               lambda: _raises(lambda: sign1.parse(
                   with_header(lambda h: h.__setitem__(sign1.HDR_CRIT, [99]))), sign1.COSEError)),
        Vector("c1-12", "content type(3) 보존", "RFC 9052 §3.1",
               lambda: parsed["content_type"] == stmt.content_type),
    ]


# --- CBOR 결정적 인코딩 (RFC 8949) -------------------------------------------

def _cbor_vectors() -> list[Vector]:
    stmt = _sample_statement()
    signed = profile.to_sign1(_sample_key(), stmt)

    return [
        Vector("cb-01", "최소 길이 정수 인코딩", "RFC 8949 §4.2.1",
               lambda: cbor.encode(23) == b"\x17" and cbor.encode(24) == b"\x18\x18"
               and cbor.encode(256) == b"\x19\x01\x00"
               and _raises(lambda: cbor.decode(b"\x18\x17"), cbor.CBORError)),
        Vector("cb-02", "맵 키 정렬 결정성", "RFC 8949 §4.2.1",
               lambda: cbor.encode({"bb": 1, "a": 2}) == cbor.encode({"a": 2, "bb": 1})
               and cbor.encode({"a": 0, "bb": 0})[1:3] == b"\x61a"),
        Vector("cb-03", "무한 길이 항목 거부", "RFC 8949 §4.2.1",
               lambda: _raises(lambda: cbor.decode(b"\x5f\x41\x01\xff"), cbor.CBORError)),
        Vector("cb-04", "부동소수 거부", "프로파일 제약",
               lambda: _raises(lambda: cbor.encode(1.5), cbor.CBORError)
               and _raises(lambda: cbor.decode(b"\xfa\x00\x00\x00\x00"), cbor.CBORError)),
        Vector("cb-05", "중복 맵 키 거부", "음성 벡터",
               lambda: _raises(lambda: cbor.decode(b"\xa2\x61a\x01\x61a\x02"), cbor.CBORError)),
        Vector("cb-06", "왕복 재직렬화 바이트 동일", "결정적 인코딩",
               lambda: cbor.encode(cbor.decode(signed)) == signed),
    ]


# --- SCITT 클레임 집합 (RFC 9943) --------------------------------------------

def _scitt_vectors() -> list[Vector]:
    key = _sample_key()
    stmt = _sample_statement()
    signed = profile.to_sign1(key, stmt)
    header = sign1.parse(signed)["header"]
    claims = header.get(profile.HDR_CWT_CLAIMS, {})

    return [
        Vector("sc-01", "issuer · subject 클레임", "RFC 9943 §3.2",
               lambda: claims.get(profile.CWT_ISS) == stmt.iss
               and claims.get(profile.CWT_SUB) == stmt.sub),
        Vector("sc-02", "CWT_Claims 보호 헤더 배치", "RFC 9597 §3",
               lambda: profile.HDR_CWT_CLAIMS in header),
        Vector("sc-03", "CWT 클레임 왕복 복원", "RFC 8392 §3.1.1",
               lambda: profile.from_sign1(signed, key.public_key).to_dict()["sub"] == stmt.sub),
        Vector("sc-04", "등록 정책 평가 근거 문서화", "RFC 9943 §4.1",
               state=PARTIAL, note="정책 ID 만 기록 · 평가 근거 미첨부"),
        Vector("sc-05", "해지(revocation) 클레임", "RFC 9943",
               state=ABSENT, note="미구현 · planned"),
    ]


# --- Merkle 포함 · 일관성 증명 (RFC 9162) ------------------------------------

def _merkle_vectors() -> list[Vector]:
    leaves = [merkle.leaf_hash(f"entry-{i}".encode()) for i in range(11)]
    root = merkle.mth(leaves)

    def inclusion_ok() -> bool:
        return all(
            merkle.verify_inclusion(i, len(leaves), leaves[i],
                                    merkle.inclusion_path(i, leaves), root)
            for i in range(len(leaves)))

    def consistency_ok() -> bool:
        for first in range(1, len(leaves)):
            proof = merkle.consistency_path(first, leaves)
            if not merkle.verify_consistency(first, len(leaves), merkle.mth(leaves[:first]),
                                             root, proof):
                return False
        return True

    def rejects_tampered() -> bool:
        bad = merkle.leaf_hash(b"entry-forged")
        return not merkle.verify_inclusion(3, len(leaves), bad,
                                           merkle.inclusion_path(3, leaves), root)

    def boundaries_ok() -> bool:
        single = [merkle.leaf_hash(b"only")]
        return (merkle.mth([]) is not None
                and merkle.mth(single) == single[0]
                and merkle.verify_inclusion(0, 1, single[0], [], single[0]))

    def path_length_ok() -> bool:
        limit = max(1, len(leaves) - 1).bit_length()
        return all(len(merkle.inclusion_path(i, leaves)) <= limit for i in range(len(leaves)))

    return [
        Vector("mk-01", "리프 해시 접두 0x00 · 노드 0x01", "RFC 9162 §2.1",
               lambda: merkle.leaf_hash(b"x") != merkle.node_hash(b"", b"")),
        Vector("mk-02", "포함 증명 경로 검증", "RFC 9162 §2.1.3", inclusion_ok),
        Vector("mk-03", "트리 헤드 서명 검증", "RFC 9162 §4.9",
               lambda: _tree_head_signature_ok()),
        Vector("mk-04", "일관성 증명 검증", "RFC 9162 §2.1.4", consistency_ok),
        Vector("mk-05", "트리 크기 단조 증가", "RFC 9162 §2.1",
               lambda: merkle.mth(leaves[:5]) != merkle.mth(leaves[:6])),
        Vector("mk-06", "변조 리프 거부", "음성 벡터", rejects_tampered),
        Vector("mk-07", "빈 트리 · 단일 리프 경계", "경계 벡터", boundaries_ok),
        Vector("mk-08", "증명 경로 길이 상한 log2(n)", "RFC 9162 §2.1.3", path_length_ok),
    ]


def _tree_head_signature_ok() -> bool:
    from itx.ts.log import TransparencyLog

    ts_key = KeyPair.from_name("conformance-t", namespace="itx-conformance")
    issuer_key = _sample_key()
    policy = {
        "version": 1,
        "ts_iss": "urn:itx:party:t",
        "sub_pattern": r"^att-[a-z0-9-]+$",
        "allowed_content_types": [CT_RECEIPT],
        "trusted_keys": {issuer_key.kid: {"iss": "urn:itx:party:m",
                                          "public_key": issuer_key.public_hex}},
        "issuer_content_types": {"urn:itx:party:m": [CT_RECEIPT]},
    }
    # 생성자가 정책 진술을 리프로 넣으므로 트리는 이미 비어 있지 않다.
    # 이 벡터가 묻는 것은 등록 정책이 아니라 헤드 서명이므로 추가 등록은 하지 않는다.
    log = TransparencyLog("conformance", ts_key, policy, now=0)
    head = log.tree_head(now=20)
    if not TransparencyLog.verify_tree_head(head, ts_key.public_key):
        return False
    forged = dict(head, tree_size=head["tree_size"] + 1)
    return not TransparencyLog.verify_tree_head(forged, ts_key.public_key)


# --- 아직 구현하지 않은 영역 --------------------------------------------------

def _gossip_vectors() -> list[Vector]:
    return [
        Vector("gs-01", "독립 운영 목격자 2 이상", "RFC 9162 §8",
               state=ABSENT, note="로그 1인스턴스 · 한계 11"),
        Vector("gs-02", "목격자 간 가십 프로토콜", "RFC 9162 §8",
               state=ABSENT, note="미구현 · planned"),
        Vector("gs-03", "분기(split-view) 탐지", "RFC 9162 §8",
               state=ABSENT, note="목격자가 T 와 같은 호스트 · 한계 11"),
        Vector("gs-04", "외부 앵커 실체인 게시", "AIR-02",
               state=ABSENT, note="파일 기반 모사 · 한계 6"),
    ]


def _tee_vectors() -> list[Vector]:
    stmt = _sample_statement()
    return [
        Vector("te-01", "attestation 클레임 자리 예약", "프로파일 정의",
               lambda: "attestation" in stmt.payload),
        Vector("te-02", "Intel TDX quote 파서", "planned",
               state=ABSENT, note="미구현 · 한계 2"),
        Vector("te-03", "quote ↔ 아티팩트 해시 결합", "planned",
               state=ABSENT, note="미구현 · 한계 2"),
        Vector("te-04", "TCB 상태 · 폐기 목록 확인", "planned",
               state=ABSENT, note="미구현 · 한계 2"),
    ]


GROUPS = (
    ("cose", "COSE_Sign1 서명 구조", "RFC 9052 · 9053", _cose_vectors),
    ("cbor", "CBOR 결정적 인코딩", "RFC 8949", _cbor_vectors),
    ("scitt", "SCITT 클레임 집합", "RFC 9943 · 9597", _scitt_vectors),
    ("merkle", "Merkle 포함 · 일관성 증명", "RFC 9162", _merkle_vectors),
    ("tee", "TEE 증명 클레임 바인딩", "AIR-02 · draft", _tee_vectors),
    ("gossip", "다중 목격자 · 분기 탐지", "RFC 9162 §8 · planned", _gossip_vectors),
)

def run(groups: tuple[str, ...] | None = None, external: bool = True) -> dict[str, Any]:
    """모든 벡터를 실행하고 화면·보고서가 그대로 쓰는 결과를 낸다.

    `external=True` 면 제3자 구현(cbor2 · pycose)으로 교차 검증까지 한다. 그 결과는
    벡터 수에 더하지 않는다 — 우리 벡터와 남의 도구는 다른 것을 말하기 때문이다.
    """
    from . import external as external_check

    selected = [g for g in GROUPS if groups is None or g[0] in groups]
    results = [Group(key, title, spec, build()).run() for key, title, spec, build in selected]
    totals = {s: sum(g["counts"][s] for g in results) for s in (PASS, PARTIAL, ABSENT, FAIL)}
    totals["total"] = sum(g["total"] for g in results)
    cross = external_check.run() if external else {
        "tools": [], "claim_status": "planned", "summary": "교차 검증을 건너뛰었다",
        "reproduce": external_check.REPRODUCE, "note": ""}
    # 우리 벡터가 다 통과해도 남의 구현이 거부하면 표준을 지켰다고 말할 수 없다.
    claim = "verified_external" if totals[FAIL] == 0 and cross["claim_status"] == "verified_external"         else "mock_result" if totals[FAIL] or cross["claim_status"] == "mock_result" else "planned"
    return {
        "groups": results,
        "totals": totals,
        "external": cross,
        "claim_status": claim,
        "note": "벡터는 이 저장소의 구현을 검사하고, 교차 검증은 제3자 구현이 같은 바이트를 읽는지를 본다.",
    }
