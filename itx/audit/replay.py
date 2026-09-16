"""독립 판정 재실행 (05 검토서 §5: 'T 가 틀리거나 침해되어도 드러나게').

입력: T 의 로그 내보내기(진술 전체 + 헤드), 외부 앵커 기록, 권한 있는 감사자가 받은 사용자
비공개 증거 묶음. 출력: 트리 재계산 일치 여부, 헤드 서명, 앵커 일치, T 판정과 재실행 판정의 차이.

T 의 코드를 신뢰하지 않는다. 같은 검사기 버전·정책 해시로 다시 계산해 비교한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from itx import CHECKER_VERSION
from itx.crypto import canonical_json, verify
from itx.reconcile import PrivateEvidence, ReconciliationEngine
from itx.reconcile.engine import REQUIRED_FOR_PASS
from itx.statements import CT_POLICY, CT_VERDICT, SignedStatement
from itx.ts import CheckpointAnchor, MerkleTree, RegistrationReceipt, TransparencyLog, leaf_hash
from itx.ts.log import TS_CONTENT_TYPES


@dataclass
class _Entry:
    index: int
    registered_at: int
    statement: SignedStatement


_PRIVATE_ONLY_EQUATIONS = ("E1", "E4")     # 사용자 비공개 증거(솔트) 없이는 평가 불가
_PRIVATE_ONLY_CODES = ("D-USER-SELF", "D-REQ-UNAPPROVED")


def _verdict_signature(v: dict[str, Any], ignore_equations: tuple[str, ...] = ()) -> dict[str, Any]:
    eqs = {k: e["result"] for k, e in v["equations"].items() if k not in ignore_equations}
    codes = sorted(d["code"] for d in v["discrepancies"]
                   if not (ignore_equations and d["code"] in _PRIVATE_ONLY_CODES))
    status = v["verification_status"]
    public_required = tuple(k for k in REQUIRED_FOR_PASS if k not in ignore_equations)
    if ignore_equations and status == "passed":
        # 비공개 증거가 필요한 등식을 뺀 비교에서는 '나머지 필수 등식이 모두 pass' 인지로만 본다.
        status = "passed_excluding_private"
    elif ignore_equations and status == "insufficient_evidence" and all(
        eqs.get(k) == "pass" for k in public_required
    ):
        status = "passed_excluding_private"
    return {
        "verification_status": status,
        "completeness": v["completeness"],
        "codes": codes,
        "equations": eqs,
        # 검증의 출처. 같은 결론이라도 다른 정책·다른 검사기·다른 증거로 얻은 결론이면
        # 그것은 재현이 아니다. 이 값들을 비교하지 않으면 T 는 "무엇으로 검증했는가" 를
        # 자유롭게 적을 수 있고 재실행은 그것을 보지 못한다.
        "policy_hash": v.get("policy_hash"),
        "checker_version": v.get("checker_version"),
        "trust_keys_version": v.get("trust_keys_version"),
        "evidence": sorted(r.get("statement_hash") for r in v.get("evidence_refs", [])),
    }


def _verdict_envelope_problem(stmt: SignedStatement, export: dict[str, Any], ts_pub: bytes) -> str | None:
    """판정 진술의 봉투를 인증한다. 증거 진술은 대조 엔진이 서명을 검사하지만 판정 진술은
    어디서도 검사되지 않았다 — 서명 없는(또는 다른 당사자가 서명한) 판정을 'T 의 판정' 으로
    읽으면, 재실행은 자기가 만든 값과 출처 불명의 값을 비교하게 된다."""
    if stmt.iss != export["ts_iss"]:
        return f"판정 발행자가 로그의 TS 가 아님: {stmt.iss}"
    if stmt.kid != export["ts_kid"]:
        return f"판정 kid 가 로그의 TS 키가 아님: {stmt.kid}"
    if not stmt.verify_with(ts_pub):
        return "판정 서명이 TS 키로 검증되지 않음"
    return None


def verify_held_receipts(tree: MerkleTree, entries: list[_Entry], held: list[dict[str, Any]],
                         ts_pub: bytes, log_id: str) -> dict[str, Any]:
    """제출자가 보관한 등록 영수증을 현재 내보내기와 대조한다 (RFC 9162 §11.3 의 '포함 검사').

    T 가 항목을 빼고 트리·헤드를 다시 서명하면 트리는 스스로 일관되고 재실행할 판정도 사라진다.
    그때 누락을 드러내는 것은 로그 안의 무엇도 아니고, T 가 등록 시점에 서명해 준 영수증뿐이다.
    영수증은 두 가지를 말한다 — (1) 이 잎이 이 자리에 있었다, (2) 그 시점의 루트가 이것이었다.
    (1) 은 잎 대조로, (2) 는 체크포인트 일관성으로 검사한다. 영수증이 없으면 이 검사는 성립하지
    않으므로 '보관 0건' 을 '누락 0건' 과 구별해 적는다."""
    missing: list[dict[str, Any]] = []
    unverifiable: list[dict[str, Any]] = []
    included = 0
    checkpoints: dict[int, dict[str, Any]] = {}
    # 보관자별 집계. U 만 영수증을 내면 R·M 이 제출한 항목의 누락은 보이지 않는다 — 누가 얼마나
    # 냈는지가 곧 이 검사의 범위다.
    by_holder: dict[str, dict[str, int]] = {}
    for item in held:
        holder = item.get("holder") or "U"
        tally = by_holder.setdefault(holder, {"held": 0, "included": 0, "missing": 0, "unverifiable": 0})
        tally["held"] += 1
        try:
            rc = RegistrationReceipt.from_dict(item["receipt"])
        except (KeyError, TypeError):
            tally["unverifiable"] += 1
            unverifiable.append({**{k: item.get(k) for k in ("sub", "content_type")}, "holder": holder, "reason": "영수증 형식 오류"})
            continue
        ident = {"sub": item.get("sub"), "content_type": item.get("content_type"), "holder": holder,
                 "leaf_index": rc.leaf_index, "leaf_hash": rc.leaf_hash, "registered_at": rc.registered_at}
        if rc.log_id != log_id or not verify(ts_pub, rc.signed_bytes(), bytes.fromhex(rc.signature or "00")):
            tally["unverifiable"] += 1
            unverifiable.append({**ident, "reason": "영수증 서명이 T 키로 검증되지 않거나 다른 로그의 영수증"})
            continue
        checkpoints.setdefault(rc.tree_size, {"tree_size": rc.tree_size, "root_hash": rc.root_hash, "anchored_at": rc.registered_at})
        entry = entries[rc.leaf_index] if 0 <= rc.leaf_index < len(entries) else None
        if entry is not None and leaf_hash(entry.statement.leaf_bytes()).hex() == rc.leaf_hash:
            included += 1
            tally["included"] += 1
            continue
        tally["missing"] += 1
        # 잎이 다른 자리에 있으면 '재배열' 이다 — 앞선 항목이 빠졌다는 뜻이므로 역시 약속 위반이다.
        elsewhere = next((e.index for e in entries if leaf_hash(e.statement.leaf_bytes()).hex() == rc.leaf_hash), None)
        if elsewhere is not None:
            missing.append({**ident, "reason": "잎은 남아 있으나 자리가 바뀜 (앞선 항목 누락 후 재배열)", "found_at": elsewhere})
        elif entry is None:
            missing.append({**ident, "reason": "영수증의 잎 위치가 현재 로그 밖에 있음 (항목 삭제 또는 꼬리 절단)"})
        else:
            missing.append({**ident, "reason": "그 자리의 잎이 영수증의 잎과 다름 (항목 교체 또는 누락)",
                            "found_sub": entry.statement.sub, "found_content_type": entry.statement.content_type})
    checkpoint_results = CheckpointAnchor.verify_tree(tree, sorted(checkpoints.values(), key=lambda c: c["tree_size"]))
    return {
        "held": len(held),
        "included": included,
        "missing": missing,
        "unverifiable": unverifiable,
        "receipt_checkpoints": checkpoint_results,
        "by_holder": by_holder,
        "ok": not missing and all(c["ok"] for c in checkpoint_results),
        "scope": "none" if not held else ("all_parties" if {"U", "R", "M"} <= set(by_holder) else "submitter_receipts"),
    }


def replay_audit(
    export: dict[str, Any],
    anchor_records: list[dict[str, Any]],
    private_by_sub: dict[str, dict[str, Any]],
    expected_parties_by_sub: dict[str, list[str]],
    reference_model_hashes: dict[str, str],
    private_by_hash: dict[str, dict[str, Any]] | None = None,
    held_receipts: list[dict[str, Any]] | None = None,
    *,
    tsa_ca_file: Path | str | None = None,
    tsa_token_dir: Path | str | None = None,
    tsa_openssl: str = "openssl",
) -> dict[str, Any]:
    """TSA 앵커가 있으면 감사자가 제공한 tsa_ca_file과 tsa_token_dir로 재검증한다.

    해당 입력이 없거나 토큰 검증에 실패하면 TSA 앵커를 통과시키지 않는다.
    기존 파일 목격자 기록은 별도의 TSA 설정 없이 계속 검증할 수 있다.
    """
    entries = [_Entry(e["index"], e["registered_at"], SignedStatement.from_dict(e["statement"])) for e in export["entries"]]
    ts_pub = bytes.fromhex(export["ts_public_key"])

    # 1. 트리 재계산 -----------------------------------------------------------
    tree = MerkleTree()
    for e in entries:
        tree.append(e.statement.leaf_bytes())
    head = export["head"]
    tree_ok = (tree.root().hex() == head["root_hash"] and tree.size == head["tree_size"]
               and all(e.index == position for position, e in enumerate(entries)))
    head_sig_ok = TransparencyLog.verify_tree_head(head, ts_pub)

    # 2. 정책(0번 진술)에서 신뢰 키를 얻는다 ----------------------------------------
    policy_entry = next((e for e in entries if e.statement.content_type == CT_POLICY), None)
    problems: list[str] = []
    if policy_entry is None:
        problems.append("정책 진술(0번)이 없음")
        trusted: dict[str, tuple[str, bytes]] = {}
        policy_hash = ""
        keys_version = ""
    else:
        pol = policy_entry.statement.payload
        trusted = {kid: (info["iss"], bytes.fromhex(info["public_key"])) for kid, info in pol["trusted_keys"].items()}
        trusted[export["ts_kid"]] = (export["ts_iss"], ts_pub)
        if not policy_entry.statement.verify_with(ts_pub):
            problems.append("정책 진술 서명이 TS 키로 검증되지 않음")
        policy_hash = policy_entry.statement.statement_hash
        keys_version = f"{export['log_id']}/keys-v{pol['version']}"
        if policy_hash != export.get("policy_hash"):
            problems.append("내보내기의 policy_hash 가 0번 진술 해시와 다름")

    # 3. 앵커 --------------------------------------------------------------------
    anchors = CheckpointAnchor.verify_tree(tree, anchor_records, tsa_ca_file=tsa_ca_file,
                                          tsa_token_dir=tsa_token_dir, tsa_openssl=tsa_openssl)

    # 3b. 보관 영수증 포함 검사 -------------------------------------------------------
    # 앵커는 '과거를 바꿨는가' 를 보고, 영수증은 '약속한 항목이 지금도 있는가' 를 본다. 첫 감사에는
    # 앵커가 없으므로 영수증이 유일한 외부 기준점이다.
    receipts = verify_held_receipts(tree, entries, held_receipts or [], ts_pub, export["log_id"])

    # 4. 판정 재실행 -------------------------------------------------------------
    issuer_content_types: dict[str, tuple[str, ...]] = {}
    if policy_entry is not None:
        issuer_content_types = {iss: tuple(cts) for iss, cts in pol["issuer_content_types"].items()}
    issuer_content_types[export["ts_iss"]] = TS_CONTENT_TYPES
    engine = ReconciliationEngine(trusted, reference_model_hashes, policy_hash, keys_version,
                                  issuer_content_types)
    subs = sorted({e.statement.sub for e in entries if e.statement.content_type not in (CT_VERDICT, CT_POLICY)
                   and not e.statement.sub.startswith("urn:itx:req:session:")})
    mismatches = []
    checked = []
    compared_without: set[str] = set()
    unauthenticated_verdicts: list[dict[str, Any]] = []
    for sub in subs:
        evidence_entries = [e for e in entries if e.statement.sub == sub and e.statement.content_type != CT_VERDICT]
        t_verdicts = []
        for e in entries:
            if e.statement.sub != sub or e.statement.content_type != CT_VERDICT:
                continue
            bad = _verdict_envelope_problem(e.statement, export, ts_pub)
            if bad is not None:
                unauthenticated_verdicts.append(
                    {"sub": sub, "log_index": e.index, "iss": e.statement.iss,
                     "kid": e.statement.kid, "problem": bad})
                continue
            t_verdicts.append(e)
        expected = expected_parties_by_sub.get(sub, ["U", "R", "M"])
        comparisons = []
        for verdict_entry in t_verdicts or [None]:
            last = verdict_entry.statement.payload if verdict_entry else None
            priv = private_by_sub.get(sub)
            if last and last.get("private_evidence_hash"):
                from itx.crypto import content_hash_hex
                expected_hash = last["private_evidence_hash"]
                candidate = (private_by_hash or {}).get(expected_hash, priv)
                priv = candidate if candidate and content_hash_hex(canonical_json(candidate)) == expected_hash else None
            ignore = () if priv else _PRIVATE_ONLY_EQUATIONS
            compared_without.update(ignore)
            cutoff = verdict_entry.index if verdict_entry else len(entries)
            snapshot = [e for e in evidence_entries if e.index < cutoff]
            verdict_time = verdict_entry.statement.issued_at if verdict_entry else head["time"]
            ev = engine.gather(sub, snapshot, PrivateEvidence.from_dict(priv) if priv else None, now=verdict_time)
            mine = engine.reconcile(ev, expected)
            item = {"log_index": verdict_entry.index if verdict_entry else None,
                    "recomputed": _verdict_signature(mine, ignore),
                    "t_verdict": _verdict_signature(last, ignore) if last else None,
                    "compared_without": list(ignore), "evidence_cutoff_index": cutoff,
                    "evidence_after_verdict": sum(e.index > cutoff for e in evidence_entries)}
            item["match"] = last is not None and item["t_verdict"] == item["recomputed"]
            comparisons.append(item)
        # Keep one result per request for existing report consumers, but fail if ANY
        # authenticated historical verdict was wrong, even when a later one is correct.
        record = {"sub": sub, **comparisons[-1], "t_verdict_count": len(t_verdicts),
                  "historical_verdicts": comparisons, "match": all(v["match"] for v in comparisons)}
        if not t_verdicts:
            record["note"] = "T 가 이 요청에 대한 (인증되는) 판정을 등록하지 않음"
        if not record["match"]:
            mismatches.append(record)
        checked.append(record)

    ok = (tree_ok and head_sig_ok and not problems and all(a["ok"] for a in anchors)
          and not mismatches and not unauthenticated_verdicts and receipts["ok"])
    return {
        "ok": ok,
        "tree_recomputed_matches_head": tree_ok,
        "head_signature_valid": head_sig_ok,
        "policy_problems": problems,
        "anchors": anchors,
        "held_receipts": receipts,
        "subs_checked": len(checked),
        "compared_without": sorted(compared_without),
        "verdicts_checked": checked,
        "verdict_mismatches": mismatches,
        "unauthenticated_verdicts": unauthenticated_verdicts,
        "auditor_checker_version": CHECKER_VERSION,
        "audit_scope": "all_authenticated_verdicts",
        "verdict_count": sum(r["t_verdict_count"] for r in checked),
        "note": "감사자는 T 의 코드를 믿지 않고 같은 검사기 버전으로 재계산했다. 사용자 비공개 증거는 권한 있는 감사자에게만 제공된다.",
    }
