"""시나리오 실행기. 결과를 JSON 직렬화 가능한 dict 로 돌려준다."""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from itx import __version__, CHECKER_VERSION
from itx.crypto import KeyPair, BACKEND
from itx.statements import CT_VERDICT, CT_RELAY, SignedStatement, issue
from itx.statements.schemas import relay_payload
from itx.ts import CheckpointAnchor
from itx.audit import replay_audit
from itx.metrics import attempt_metrics, aggregate
from .context import SimContext
from .model import DEFAULT_MODELS, reference_hashes
from .parties import User, Relay, RelayBehavior, ModelOperator, ThirdParty
from .scenarios import Scenario, SCENARIOS, Q1_SCENARIO_IDS, COOPERATION_SETS, scenario_by_id

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
        for q, who in ((U.queue, "U"), (R.queue, "R"), (M.queue, "M")):
            q.flush(T)
    U.close_session()
    ctx.advance(T.service.total_delay_ms + 10)  # 마지막 등록이 보이도록
    final_verdicts: dict[str, dict[str, Any]] = {}
    for a in U.attempts:
        stmt = T.finalize(a.sub, a.expected_parties, ctx.now())
        final_verdicts[a.sub] = stmt.payload
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
    audit = replay_audit(export, T.anchor.records, {s: p.to_dict() for s, p in T.private.items()},
                         T.expected_parties, ref)
    ctx.record("auditor", "replay_audit", ok=audit["ok"], mismatches=len(audit["verdict_mismatches"]),
               anchors_ok=all(a["ok"] for a in audit["anchors"]))

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
            "anchor_record": anchor_rec, "tampered_index": tampered_index,
        },
        "audit": audit,
        "log_export": export,
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


def run_all(out_dir: Path, seed: int = 42, modes: tuple[str, ...] = MODES) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for sc in SCENARIOS:
        for mode in modes:
            results.append(run_scenario(sc, mode, seed))
    q1 = run_q1_matrix(seed)
    summary = aggregate(results)
    bundle = {
        "generated_with": {"itx_version": __version__, "checker_version": CHECKER_VERSION, "seed": seed,
                           "crypto_backend": BACKEND, "claim_status": "mock_result",
                           "note": "결정적 모형 모델·시뮬레이션 시계 기반. 실제 네트워크·LLM 성능이 아니다."},
        "scenarios": [s.to_dict() for s in SCENARIOS],
        "results": [{k: v for k, v in r.items() if k != "log_export"} for r in results],
        "q1_matrix": q1,
        "summary": summary,
    }
    (out_dir / "results.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps({"summary": summary, "q1_matrix": q1}, ensure_ascii=False, indent=1), encoding="utf-8")
    # S01 의 로그 전체를 감사 재생용 예시로 남긴다.
    for r in results:
        if r["run"]["scenario_id"] == "S01" and r["run"]["mode"] == "protect":
            (out_dir / "log-export-S01.json").write_text(json.dumps(r["log_export"], ensure_ascii=False, indent=1), encoding="utf-8")
            (out_dir / "anchors-S01.json").write_text(json.dumps(r["ts"]["anchors"], ensure_ascii=False, indent=1), encoding="utf-8")
    return bundle
