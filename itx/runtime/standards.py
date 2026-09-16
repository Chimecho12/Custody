"""「표준 적합성」 화면이 쓰는 값.

두 부분이다.

1. **적합성 벡터** — `itx.cose.conformance` 가 실제로 돌려서 센 결과.
2. **인코딩 병치** — 같은 진술을 자체 JSON 프로파일과 COSE_Sign1 으로 나란히.

병치에는 제약이 하나 있고, 그 제약이 이 화면에서 가장 할 말이 많은 부분이다.
COSE 의 서명 대상은 Sig_structure 이므로 **발행자만 자기 진술을 COSE 로 재발행할
수 있다.** U 의 설정으로 도는 이 앱은 U 문서만 진짜 서명이 붙은 .cose 로 낼 수
있고, R·M·T 문서는 JSON 쪽만 보인다. 이것은 결함이 아니라 서명의 성질이다 —
남의 진술을 내가 다시 서명할 수 있다면 서명이 아무 의미도 없을 것이다.
"""
from __future__ import annotations

from typing import Any

from itx.cose import conformance, profile
from itx.statements import SignedStatement

#: 화면 왼쪽 문서 목록의 순서와 이름.
DOCUMENTS = (
    ("U", "U 요청 진술", "request statement · CWT", "u-req"),
    ("R", "R 중계 진술", "relay statement · CWT", "r-relay"),
    ("M", "M 응답 영수증", "execution receipt · CWT", "m-exec"),
    ("T", "T 등록 영수증", "registration receipt · Merkle", "t-reg"),
)

#: 각 문서가 어느 벡터 묶음의 적용을 받는가.
GROUPS_FOR = {
    "U": ("cose", "cbor", "scitt"),
    "R": ("cose", "cbor", "scitt"),
    "M": ("cose", "cbor", "scitt", "tee"),
    "T": ("cose", "cbor", "merkle", "scitt", "gossip"),
}


#: 발행자 iss 접미사 → 역할.
_ROLE_OF_ISS = {f"urn:itx:party:{r.lower()}": r for r in "URMTW"}


def statements_for(export: dict[str, Any], sub: str) -> dict[str, SignedStatement]:
    """T 원장 내보내기에서 한 요청의 당사자별 진술을 모은다.

    사건 기록(public record)에는 T 판정만 실려 있다. U·R·M 진술은 원장에 등록된
    것이므로 여기서 꺼낸다. 같은 역할이 여러 번 등록했으면 마지막 것을 쓴다.
    """
    found: dict[str, SignedStatement] = {}
    for entry in export.get("entries", []):
        raw = entry.get("statement") or {}
        if raw.get("sub") != sub:
            continue
        role = _ROLE_OF_ISS.get(raw.get("iss", ""))
        if role:
            found[role] = SignedStatement.from_dict(raw)
    return found


def document_view(role: str, name: str, sub: str, file_stem: str,
                  statement: SignedStatement | None, key: Any | None) -> dict[str, Any]:
    """문서 하나의 병치 카드. 키가 없으면 COSE 쪽은 결손으로 남는다."""
    view: dict[str, Any] = {
        "role": role, "name": name, "sub": sub,
        "file": f"{file_stem}.cose", "export_name": f"{file_stem}.cose",
    }
    if statement is None:
        view.update(available=False, reason="이 요청에 해당 진술이 없습니다 (결손).",
                    json="", json_bytes=0, cose_hex="", cose_diagnostic="",
                    cose_bytes=0, structure=[])
        return view
    from itx.crypto import canonical_json

    json_bytes = canonical_json(statement.to_dict())
    view.update(available=True, json=json_bytes.decode("utf-8"), json_bytes=len(json_bytes))
    if key is None or key.kid != statement.kid:
        view.update(
            reissuable=False,
            reason=("이 진술의 서명 키는 이 기계에 없습니다. COSE_Sign1 의 서명 대상은 "
                    "Sig_structure 이므로, 발행자만 자기 진술을 COSE 로 재발행할 수 있습니다."),
            cose_hex="", cose_diagnostic="", cose_bytes=0, structure=[])
        return view
    both = profile.encodings(key, statement)
    view.update(reissuable=True, reason="", **{k: v for k, v in both.items() if k != "json"})
    return view


def build(export: dict[str, Any] | None, key: Any | None, sub: str = "—") -> dict[str, Any]:
    """화면이 그대로 쓰는 값 묶음. `export` 는 T 원장 내보내기다."""
    report = conformance.run()
    by_key = {g["key"]: g for g in report["groups"]}
    found = statements_for(export or {}, sub) if sub and sub != "—" else {}
    documents = []
    for role, name, subtitle, stem in DOCUMENTS:
        statement = found.get(role)
        view = document_view(role, name, sub, f"{stem}-{sub}", statement, key)
        groups = [by_key[g] for g in GROUPS_FOR[role] if g in by_key]
        counts = {s: sum(g["counts"][s] for g in groups)
                  for s in ("pass", "partial", "absent", "fail")}
        view.update(subtitle=subtitle, groups=groups, counts=counts,
                    total=sum(g["total"] for g in groups))
        documents.append(view)
    return {
        "documents": documents,
        "totals": report["totals"],
        "external": report["external"],
        "claim_status": report["claim_status"],
        "note": report["note"],
    }
