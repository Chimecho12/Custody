"""Read-only standards views and COSE export workflow."""
from pathlib import Path

from .. import standards


def standards_operation(output_path, op, args, agent):
    """표준 적합성 · 키 인벤토리 · COSE 내보내기.

    셋 다 판정을 바꾸지 않는다. 이미 내려진 판정을 무엇이 뒷받침하는지 보여줄 뿐이다.
    """
    from itx import keys as keystore

    from ..common import key_for

    if op == "key_inventory":
        return keystore.build(agent.config)

    sub = args.get("sub") or "—"
    # 당사자 진술은 사건 기록이 아니라 T 원장에 있다. 판정만 들어 있는 기록으로는 부족하다.
    export = agent.audit_export() if sub != "—" else None
    key = key_for(agent.config)
    if op == "standards":
        return standards.build(export, key, sub)

    # cose_export: 이 기계가 서명할 수 있는 문서만 .cose 로 낸다.
    from itx.cose import to_sign1
    view = standards.build(export, key, sub)
    found = standards.statements_for(export or {}, sub)
    written = []
    for document in view["documents"]:
        statement = found.get(document["role"])
        if not document.get("reissuable") or statement is None:
            continue
        path = output_path(document["export_name"].removesuffix(".cose"), ".cose")
        path.write_bytes(to_sign1(key, statement))
        written.append({"role": document["role"], "path": str(path),
                        "bytes": path.stat().st_size})
    readme = output_path("verify-cose", ".txt")
    readme.write_text(_verification_readme(view, written), encoding="utf-8")
    return {"written": written, "readme": str(readme),
            "skipped": [d["role"] for d in view["documents"] if not d.get("reissuable")]}


def _verification_readme(view, written) -> str:
    """내보낸 .cose 와 함께 나가는 검증 안내. 명령이 배지 열 개보다 강하다."""
    lines = [
        "itx COSE_Sign1 내보내기",
        "",
        "이 파일들은 RFC 9052 COSE_Sign1 (alg -8 EdDSA) 이고, 클레임은 RFC 9597 형식으로",
        "보호 헤더 라벨 15 에 들어 있습니다. 아래 명령은 이 저장소가 실행하지 않았습니다 —",
        "직접 돌린 결과만 근거로 삼으십시오.",
        "",
        "내보낸 문서",
    ]
    lines += [f"  {w['role']}  {Path(w['path']).name}  ({w['bytes']} B)" for w in written] or ["  없음"]
    skipped = [d["role"] for d in view["documents"] if not d.get("reissuable")]
    if skipped:
        lines += ["", "내보내지 못한 문서: " + ", ".join(skipped),
                  "  COSE 의 서명 대상은 Sig_structure 이므로 발행자만 자기 진술을 재발행할 수 있습니다."]
    cross = view.get("external", {})
    lines += ["", "제3자 구현 교차 검증 — " + cross.get("summary", "결과 없음"),
              f"  재현: {cross.get('reproduce', '')}"]
    for tool in cross.get("tools", []):
        lines.append(f"  {tool['tool']} {tool['version']}: {tool['state']} — {tool['note']}")
        lines += [f"      [{c['state']}] {c['label']}" for c in tool.get("checks", [])]
    if cross.get("note"):
        lines += ["", "  " + cross["note"]]
    lines += ["", f"이 저장소의 적합성 벡터: pass {view['totals']['pass']} / "
                  f"partial {view['totals']['partial']} / absent {view['totals']['absent']} / "
                  f"fail {view['totals']['fail']}"]
    return "\n".join(lines) + "\n"
