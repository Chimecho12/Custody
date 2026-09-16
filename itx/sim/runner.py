"""시나리오 실행기. 결과를 JSON 직렬화 가능한 dict 로 돌려준다."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from itx import CHECKER_VERSION, __version__
from itx.audit import replay_audit
from itx.crypto import BACKEND, KeyPair
from itx.metrics import aggregate, attempt_metrics
from itx.statements import CT_RELAY, issue
from itx.ts import CheckpointAnchor

from .context import SimContext
from .model import DEFAULT_MODELS, reference_hashes
from .parties import ModelOperator, Relay, ThirdParty, User
from .scenarios import COOPERATION_SETS, Q1_SCENARIO_IDS, SCENARIOS, Scenario, scenario_by_id

MODES = ("observe", "protect", "strict")


def _keys(seed: int) -> dict[str, KeyPair]:
    ns = f"itx-sim-{seed}"
    return {
        "U": KeyPair.from_name("user-1", ns),
        "R": KeyPair.from_name("relay-1", ns),
        "M": KeyPair.from_name("model-operator-1", ns),
        "T": KeyPair.from_name("third-party-1", ns),
    }


def run_scenario(scenario: Scenario, mode: str, seed: int = 42,
                 cooperation: str = "U+R+M") -> dict[str, Any]:
    """시나리오 하나를 한 모드로 실행한다. cooperation 은 Q1 매트릭스용 협조 집합."""
    ctx = SimContext(seed)
    keys = _keys(seed)
    ref = reference_hashes(DEFAULT_MODELS)
    party_keys = {
        "U": ("urn:itx:party:user", keys["U"]),
        "R": ("urn:itx:party:relay", keys["R"]),
        "M": ("urn:itx:party:model-operator", keys["M"]),
    }
    T = ThirdParty(ctx, keys["T"], party_keys, ref, CheckpointAnchor(), misjudge=scenario.ts_misjudge,
                   down=scenario.ts_down, extra_delay_ms=scenario.ts_extra_delay_ms)
    coop = set(cooperation.split("+"))
    M = ModelOperator(ctx, keys["M"], DEFAULT_MODELS, T,
                      issue_receipts=scenario.model_issue_receipts and "M" in coop,
                      pre_exec_enforce=scenario.model_pre_exec_enforce, queue_capacity=scenario.queue_capacity,
                      collude=scenario.model_collude)
    first_behavior = replace(scenario.relay, omit_statement=scenario.relay.omit_statement or "R" not in coop,
                             queue_capacity=scenario.queue_capacity)
    R = Relay(ctx, keys["R"], M, T, first_behavior)
    U = User(ctx, keys["U"], R, T, mode, ref, {keys["M"].kid: keys["M"].public_key},
             queue_capacity=scenario.queue_capacity)
    expected_parties = tuple(p for p in scenario.expected_parties if p in coop)

    ctx.record("sim", "start", scenario=scenario.id, mode=mode, seed=seed, cooperation=cooperation)
    if scenario.ts_down:
        ctx.record("T", "service_down", reason="scenario")

    for i in range(scenario.attempts):
        if i > 0 and scenario.relay_second is not None:
            R.behavior = replace(scenario.relay_second, omit_statement=scenario.relay_second.omit_statement or "R" not in coop,
                                 queue_capacity=scenario.queue_capacity)
            R.queue.capacity = scenario.queue_capacity
        U.request(scenario.text, scenario.requested_model, scenario.allowed_models, scenario.fallback_policy,
                  scenario.allowed_request_transforms, expected_parties=expected_parties)
        ctx.advance(100)

    # 세션 종료 ---------------------------------------------------------------
    if scenario.ts_down and scenario.ts_recover_before_close:
        ctx.advance(500)
        T.set_down(False)
        for q in (U.queue, R.queue, M.queue):
            q.flush(T)
    U.close_session()
    ctx.advance(T.service.total_delay_ms + 10)  # 마지막 등록이 보이도록
    final_verdicts: dict[str, dict[str, Any]] = {}
    for a in U.attempts:
        stmt = T.finalize(a.sub, a.expected_parties, ctx.now())
        final_verdicts[a.sub] = stmt.payload

    omitted_indexes = None
    if scenario.ts_omit_request_before_anchor:
        # 앵커·감사 이전에 T 가 첫 요청의 항목을 전부 빼고 로그를 다시 꾸민다 (S18). 트리와 헤드는 다시
        # 계산되므로 스스로는 깨지지 않고, 그 요청의 판정도 사라져 재실행할 것도 없다.
        target = U.attempts[0].sub
        omitted_indexes = T.log.drop_sub(target)
        ctx.record("T", "log_entries_omitted", target, indexes=omitted_indexes, note="운영자가 요청 항목을 누락하고 재서명 (모사)")
    anchor_rec = T.checkpoint(ctx.now())

    tampered_index = None
    if scenario.ts_tamper_after_anchor:
        # 앵커 이후 과거 항목 재작성: 첫 중계 진술을 '무변환·정상' 으로 보이는 위조 진술로 바꾼다.
        for e in T.log.entries:
            if e.statement.content_type == CT_RELAY:
                tampered_index = e.index
                fake_payload = dict(e.statement.payload)
                fake_payload["relay_seq"] = 999
                fake = issue(keys["R"], iss=e.statement.iss, sub=e.statement.sub, content_type=CT_RELAY,
                             payload=fake_payload, issued_at=e.statement.issued_at)
                T.log.tamper_entry(e.index, fake)
                ctx.record("T", "log_tampered", e.statement.sub, index=e.index, note="운영자가 과거 항목을 교체 (모사)")
                break

    export = T.log.export(ctx.now())
    private_by_sub = {s: p.to_dict() for s, p in T.private.items()}
    # 감사자는 U·R·M 이 각자 보관한 등록 영수증을 받아 '약속된 항목이 지금도 로그에 있는가' 를 같이 검사한다.
    # R·M 이 영수증을 내지 않으면 그들이 제출한 항목의 누락은 보이지 않는다 (by_holder 가 그 범위를 적는다).
    held_receipts = U.queue.held + R.queue.held + M.queue.held
    audit = replay_audit(export, T.anchor.records, private_by_sub, T.expected_parties, ref, held_receipts=held_receipts)
    ctx.record("auditor", "replay_audit", ok=audit["ok"], mismatches=len(audit["verdict_mismatches"]),
               anchors_ok=all(a["ok"] for a in audit["anchors"]), receipts_missing=len(audit["held_receipts"]["missing"]))
    audit_without_receipts = None
    if scenario.ts_omit_request_before_anchor:
        # 대조군: 영수증을 버린 감사자. 같은 내보내기가 어떻게 읽히는지 나란히 남긴다.
        without = replay_audit(export, T.anchor.records, private_by_sub, T.expected_parties, ref)
        audit_without_receipts = {"ok": without["ok"], "subs_checked": without["subs_checked"],
                                  "tree_recomputed_matches_head": without["tree_recomputed_matches_head"],
                                  "head_signature_valid": without["head_signature_valid"],
                                  "anchors_ok": all(a["ok"] for a in without["anchors"])}

    attempts_out = []
    for idx, a in enumerate(U.attempts):
        truth = R.ground_truth.get(a.attempt_id, {})
        fv = final_verdicts[a.sub]
        gt = dict(scenario.ground_truth)
        if scenario.attack_attempts is not None:
            gt["attack_present"] = idx in scenario.attack_attempts
        m = attempt_metrics(gt, a.gate, fv, a.sent_at, a.received_at)
        attempts_out.append({
            "sub": a.sub, "attempt_id": a.attempt_id, "sent_at": a.sent_at, "received_at": a.received_at,
            "ground_truth": gt,
            "error": a.error, "response_body": a.response_body,
            "contract": a.contract.to_dict(),
            "observation": a.observation.to_dict() if a.observation else None,
            "inline_receipt": a.inline_receipt.to_dict() if a.inline_receipt else None,
            "inline_relay": a.inline_relay.to_dict() if a.inline_relay else None,
            "gate": a.gate,
            "live_verdict": a.live_verdict,
            "final_verdict": fv,
            "ground_truth_view": truth,  # 시뮬레이터만 아는 사실. 증거가 아니다.
            "registered": [
                {"index": e.index, "content_type": e.statement.content_type, "iss": e.statement.iss,
                 "registered_at": e.registered_at, "statement_hash": e.statement.statement_hash}
                for e in T.log.statements_for(a.sub)
            ],
            "metrics": m,
        })

    return {
        "run": {"scenario_id": scenario.id, "mode": mode, "seed": seed, "cooperation": cooperation,
                "itx_version": __version__, "checker_version": CHECKER_VERSION, "crypto_backend": BACKEND,
                "claim_status": "mock_result"},
        "scenario": scenario.to_dict(),
        "attempts": attempts_out,
        "timeline": ctx.timeline.events,
        "ts": {
            **T.self_audit(),
            "down_during_run": scenario.ts_down, "extra_delay_ms": scenario.ts_extra_delay_ms,
            "queue_drops": {"U": U.queue.dropped, "R": R.queue.dropped, "M": M.queue.dropped},
            "anchor_record": anchor_rec, "tampered_index": tampered_index, "omitted_indexes": omitted_indexes,
            "held_receipts": len(held_receipts),
            "held_receipts_by_holder": {"U": len(U.queue.held), "R": len(R.queue.held), "M": len(M.queue.held)},
        },
        "audit": audit,
        "audit_without_held_receipts": audit_without_receipts,
        "log_export": export,
        "held_receipts": held_receipts,  # U·R·M 이 보관한 등록 영수증 (holder 표기). 내보내기와 함께 감사 재현용으로 남긴다
    }


def run_q1_matrix(seed: int = 42, mode: str = "protect") -> list[dict[str, Any]]:
    """Q1 탐지 가능성: 위반 시나리오 × 협조 집합."""
    rows = []
    for sid in Q1_SCENARIO_IDS:
        sc = scenario_by_id(sid)
        for coop in COOPERATION_SETS:
            r = run_scenario(sc, mode, seed, cooperation=coop)
            last = r["attempts"][-1]
            fv = last["final_verdict"]
            rows.append({
                "scenario_id": sid, "title": sc.title, "cooperation": coop,
                "verification_status": fv["verification_status"], "completeness": fv["completeness"],
                "codes": sorted({d["code"] for d in fv["discrepancies"] if d["severity"] != "observation"}),
                "gate_action": last["gate"]["action"],
                "attack_present": last["ground_truth"]["attack_present"],
                "detected": fv["verification_status"] == "failed",
                "attribution": sorted({d["attribution"] for d in fv["discrepancies"] if d["severity"] == "violation"}),
            })
    return rows


def _contribution_cell(r: dict[str, Any], has_t: bool) -> dict[str, Any]:
    a = r["attempts"][-1]
    m = a["metrics"]
    refused = any(e["kind"] == "refused" and e["actor"] == "M" for e in r["timeline"])
    return {
        "gate_action": a["gate"]["action"], "blocked_before_use": m["blocked_before_use"],
        "harm_exposed": m["harm_exposed"], "served": m["served"], "decision_wait_ms": m["decision_wait_ms"],
        "model_refused_before_execution": refused,
        # T 가 없으면 아래 셋은 존재하지 않는다. 0 이나 False 가 아니라 None 이다 — 없는 것을 있는 척하지 않는다.
        "detected_by_verdict": m["detected_by_verdict"] if has_t else None,
        "completeness": a["final_verdict"]["completeness"] if has_t else None,
        "audit_finding": (not r["audit"]["ok"]) if has_t else None,
    }


def run_t_contribution(seed: int = 42) -> list[dict[str, Any]]:
    """Q1 보조 실험: 'T 가 실제로 무엇을 더해 주는가'.

    같은 사건을 (a) T 없이 U 로컬 검증만(protect, T 정지·미복구), (b) U+T protect, (c) U+T strict 로 돌려
    나란히 놓는다. 사용 전 차단은 U 의 로컬 검증이 맡으므로 (a)와 (b)의 방어 결과는 같아야 정상이다.
    T 가 더하는 것은 그 밖의 것 — M 의 실행 전 거부(계약을 T 에서 조회, S17), 서명·등록된 탐지 기록,
    감사 발견(S13·S14·S18), 증거 완전성 — 이고, 이 표가 비어 있으면 '제3자가 필요하다' 는 주장은 근거가 없다.
    """
    rows = []
    for sc in SCENARIOS:
        local = run_scenario(replace(sc, ts_down=True, ts_recover_before_close=False), "protect", seed)
        protect = run_scenario(sc, "protect", seed)
        strict = run_scenario(sc, "strict", seed)
        a, b, c = _contribution_cell(local, False), _contribution_cell(protect, True), _contribution_cell(strict, True)
        adds = []
        if b["model_refused_before_execution"] and not a["model_refused_before_execution"]:
            adds.append("pre_execution_refusal")
        if b["detected_by_verdict"]:
            adds.append("signed_detection_record")
        if b["audit_finding"]:
            adds.append("audit_finding")
        if b["completeness"] == "complete":
            adds.append("complete_evidence")
        if c["blocked_before_use"] and not a["blocked_before_use"]:
            adds.append("strict_block")
        rows.append({
            "scenario_id": sc.id, "title": sc.title, "category": sc.category,
            "attack_present": bool(protect["attempts"][-1]["ground_truth"]["attack_present"]),
            "local_only": a, "with_t_protect": b, "with_t_strict": c,
            "same_defense_without_t": a["blocked_before_use"] == b["blocked_before_use"] and a["harm_exposed"] == b["harm_exposed"],
            "t_adds": adds,
        })
    return rows


def summarize_t_contribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    attacks = [r for r in rows if r["attack_present"]]
    return {
        "scenarios": len(rows),
        "defense_same_without_t": sum(r["same_defense_without_t"] for r in rows),
        "attacks_blocked_local_only": sum(r["local_only"]["blocked_before_use"] for r in attacks),
        "attacks_blocked_with_t_protect": sum(r["with_t_protect"]["blocked_before_use"] for r in attacks),
        "attack_attempts": len(attacks),
        "pre_execution_refusal": [r["scenario_id"] for r in rows if "pre_execution_refusal" in r["t_adds"]],
        "signed_detection_record": [r["scenario_id"] for r in rows if "signed_detection_record" in r["t_adds"]],
        "audit_finding": [r["scenario_id"] for r in rows if "audit_finding" in r["t_adds"]],
        "strict_block": [r["scenario_id"] for r in rows if "strict_block" in r["t_adds"]],
        "note": "사용 전 차단은 U 로컬 검증의 몫이다. T 는 실행 전 거부·서명된 탐지 기록·감사 발견·완전성을 더한다. 모의 결과(mock_result).",
    }


def run_all(out_dir: Path, seed: int = 42, modes: tuple[str, ...] = MODES) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for sc in SCENARIOS:
        for mode in modes:
            results.append(run_scenario(sc, mode, seed))
    q1 = run_q1_matrix(seed)
    contribution = run_t_contribution(seed)
    summary = aggregate(results)
    bundle = {
        "generated_with": {"itx_version": __version__, "checker_version": CHECKER_VERSION, "seed": seed,
                           "crypto_backend": BACKEND, "claim_status": "mock_result",
                           "note": "결정적 모형 모델·시뮬레이션 시계 기반. 실제 네트워크·LLM 성능이 아니다."},
        "scenarios": [s.to_dict() for s in SCENARIOS],
        "results": [{k: v for k, v in r.items() if k not in ("log_export", "held_receipts")} for r in results],
        "q1_matrix": q1,
        "t_contribution": contribution,
        "t_contribution_summary": summarize_t_contribution(contribution),
        "summary": summary,
    }
    (out_dir / "results.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps({"summary": summary, "q1_matrix": q1, "t_contribution": contribution,
                                                       "t_contribution_summary": bundle["t_contribution_summary"]},
                                                      ensure_ascii=False, indent=1), encoding="utf-8")
    # S01 의 로그 전체를 감사 재생용 예시로 남긴다.
    for r in results:
        if r["run"]["scenario_id"] == "S01" and r["run"]["mode"] == "protect":
            (out_dir / "log-export-S01.json").write_text(json.dumps(r["log_export"], ensure_ascii=False, indent=1), encoding="utf-8")
            (out_dir / "anchors-S01.json").write_text(json.dumps(r["ts"]["anchors"], ensure_ascii=False, indent=1), encoding="utf-8")
            (out_dir / "receipts-S01.json").write_text(json.dumps(r["held_receipts"], ensure_ascii=False, indent=1), encoding="utf-8")
    return bundle
