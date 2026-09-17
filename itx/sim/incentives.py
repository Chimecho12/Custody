"""인센티브 원장: "정직하게 참여하면 편익이 비용보다 크고, 부당한 책임을 지지 않는가".

목표 문서의 '모든 노드가 손해보지 않는 구조' 를 그대로 검증할 수는 없다. 대신 검증 가능한 두 질문으로 바꾼다.

1. **부당한 책임 없음 (구조적, 파라미터 무관).** 판정·감사가 어떤 당사자에게 책임을 돌릴 때, 그 당사자가
   시나리오의 실제 가해자인가. 정직한 당사자가 한 번이라도 단정적으로 지목되면 이 구조는 실패다.
   미확정 귀속("R 또는 M")은 책임이 아니라 '미해결' 로 센다 — 누구에게도 손해를 주지 않지만 분쟁도 끝내지 못한다.
2. **정직 참여의 편익 > 비용 (파라미터 의존, 가설).** 비용은 타임라인 사건(서명·등록·추론·판정·대기)의 개수에
   단위 비용을 곱한 것이고, 편익은 피해 회피·책임 면제다. 단위 값은 `IncentiveParams` 에 모아 두었고 근거가
   없다 — 그래서 이 축의 수치는 `claim_status = "hypothesis"` 다. 개수(1번)와 단위(2번)를 섞어 읽지 않도록
   원장은 둘을 따로 낸다.

T 의 경제(수수료·운영비)는 다루지 않는다. T 의 비용만 센다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

PARTIES = ("U", "R", "M", "T")

#: 판정의 위반 코드가 TM1 아래에서 단정적으로 귀속되는 당사자. 감사 재계산 코드에도 같은 표를 쓴다.
_VIOLATION_BLAME: dict[str, str] = {
    "D-REQ-UNAPPROVED": "R", "D-NONCE": "R", "D-RESP-UNAPPROVED": "R", "D-ROUTE-UNAPPROVED": "R",
    "D-ROUTE-UNDECLARED": "R", "D-ATTEMPT-MISMATCH": "R",
}
#: 시나리오의 공격 종류 → 실제 가해자 (시뮬레이터만 아는 사실).
_CULPRIT_BY_KIND: dict[str, frozenset[str]] = {
    "request_modification": frozenset({"R"}), "response_modification": frozenset({"R"}),
    "unapproved_route": frozenset({"R"}), "undeclared_route": frozenset({"R"}), "replay": frozenset({"R"}),
    "collusion": frozenset({"R", "M"}), "prompt_injection": frozenset(), "none": frozenset(),
}


@dataclass(frozen=True)
class IncentiveParams:
    """단위 비용·편익. 근거 없는 자리표시자다 — 값을 바꿔도 1번(부당한 책임) 결과는 변하지 않는다."""
    sign: float = 1.0            # 진술 한 건 서명
    register: float = 0.5        # T 에 한 건 등록 (왕복)
    private: float = 0.5         # 비공개 증거 전달
    inference: float = 10.0      # 모형 모델 실행 한 번 (M)
    verdict: float = 2.0         # 대조·판정 한 번 (T)
    checkpoint: float = 1.0      # 체크포인트 앵커 한 번 (T)
    wait_per_100ms: float = 0.2  # 사용자 결정 대기 (U)
    harm: float = 50.0           # 유해 응답이 업무에 쓰였을 때의 손실 (U)
    liability: float = 20.0      # 단정적으로 책임이 귀속됐을 때의 손실 (해당 당사자)


def culprits_for(scenario: dict[str, Any]) -> set[str]:
    """시나리오 정의에서 실제 가해자 집합을 읽는다. R 의 공격과 T 의 비행은 겹칠 수 있다 (S13)."""
    out = set(_CULPRIT_BY_KIND.get(scenario["ground_truth"].get("attack_kind", "none"), frozenset()))
    if scenario.get("ts_misjudge") or scenario.get("ts_tamper_after_anchor") or scenario.get("ts_omit_request_before_anchor"):
        out.add("T")
    return out


def _count_events(timeline: list[dict[str, Any]], sub: str | None) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {p: {} for p in PARTIES}
    for e in timeline:
        actor = e["actor"]
        if actor not in counts or (sub is not None and e.get("sub") not in (None, sub)):
            continue
        counts[actor][e["kind"]] = counts[actor].get(e["kind"], 0) + 1
    return counts


def _blame(attempt: dict[str, Any], audit: dict[str, Any]) -> tuple[dict[str, list[str]], list[str]]:
    """(단정 귀속 {당사자: [근거]}, 미확정 귀속 [근거]) 를 판정과 감사에서 모은다."""
    definite: dict[str, list[str]] = {}
    unresolved: list[str] = []
    for d in attempt["final_verdict"]["discrepancies"]:
        if d["severity"] != "violation":
            continue
        if "또는" in d["attribution"]:
            unresolved.append(f"{d['code']}: {d['attribution']}")
        elif d["attribution"].split()[0] in PARTIES:
            definite.setdefault(d["attribution"].split()[0], []).append(f"verdict {d['code']}")
    for m in audit.get("verdict_mismatches", []):
        if m["sub"] != attempt["sub"]:
            continue
        definite.setdefault("T", []).append("audit: T 판정이 독립 재계산과 다름")
        for code in m["recomputed"]["codes"]:
            party = _VIOLATION_BLAME.get(code)
            if party:
                definite.setdefault(party, []).append(f"audit recomputed {code}")
    if not all(a["ok"] for a in audit.get("anchors", [])):
        definite.setdefault("T", []).append("audit: 앵커 불일치 (기록 재작성)")
    if audit.get("held_receipts", {}).get("missing"):
        definite.setdefault("T", []).append("audit: 보관 영수증 누락 (기록 누락)")
    return definite, unresolved


def ledger_for_run(run: dict[str, Any], params: IncentiveParams = IncentiveParams()) -> dict[str, Any]:
    """시나리오 한 실행(모드 하나)의 원장. 시도별로 세고 당사자별로 합친다."""
    scenario = run["scenario"]
    culprits = culprits_for(scenario)
    audit = run["audit"]
    parties: dict[str, dict[str, Any]] = {
        p: {"cost_units": 0.0, "cost_events": {}, "benefit_units": 0.0, "just_liability": 0, "unjust_liability": 0,
            "unjust_reasons": [], "exonerated": 0, "honest": p not in culprits} for p in PARTIES}
    unresolved_total: list[str] = []
    for attempt in run["attempts"]:
        m = attempt["metrics"]
        counts = _count_events(run["timeline"], attempt["sub"])
        cost = {
            "U": counts["U"].get("contract_signed", 0) * params.sign + counts["U"].get("response_received", 0) * params.sign
                 + counts["U"].get("evidence_registered", 0) * params.register
                 + counts["U"].get("private_evidence_delivered", 0) * params.private
                 + (m["decision_wait_ms"] or 0) / 100 * params.wait_per_100ms,
            "R": counts["R"].get("relay_statement_issued", 0) * params.sign + counts["R"].get("evidence_registered", 0) * params.register,
            "M": counts["M"].get("receipt_issued", 0) * params.sign + counts["M"].get("evidence_registered", 0) * params.register
                 + counts["M"].get("inferred", 0) * params.inference,
            "T": counts["T"].get("verdict_issued", 0) * params.verdict + counts["T"].get("verdict_requested", 0) * params.verdict,
        }
        for p in PARTIES:
            parties[p]["cost_units"] += cost[p]
            for kind, n in counts[p].items():
                parties[p]["cost_events"][kind] = parties[p]["cost_events"].get(kind, 0) + n
        # 편익·손실 (U): 유해 응답을 쓰기 전에 막았는가, 아니면 썼는가.
        if m["attack_present"] and attempt["ground_truth"].get("harm_if_consumed"):
            if m["harm_exposed"]:
                parties["U"]["benefit_units"] -= params.harm
            elif m["blocked_before_use"]:
                parties["U"]["benefit_units"] += params.harm
        definite, unresolved = _blame(attempt, audit)
        unresolved_total.extend(unresolved)
        for party, reasons in definite.items():
            if party in culprits:
                parties[party]["just_liability"] += 1
                parties[party]["benefit_units"] -= params.liability
            else:
                parties[party]["unjust_liability"] += 1
                parties[party]["unjust_reasons"].extend(reasons)
                parties[party]["benefit_units"] -= params.liability
        # 면책: R 의 공격이 R 에게 단정 귀속되면, 같은 구간에 있던 정직한 M 은 의심에서 벗어난다.
        if culprits == {"R"} and "R" in definite and "M" not in definite and not unresolved:
            parties["M"]["exonerated"] += 1
            parties["M"]["benefit_units"] += params.liability
    # T 의 마지막 체크포인트는 시도와 무관한 세션 비용이다.
    session = _count_events(run["timeline"], None)["T"]
    parties["T"]["cost_units"] += session.get("checkpoint_anchored", 0) * params.checkpoint
    for p in PARTIES:
        parties[p]["net_units"] = round(parties[p]["benefit_units"] - parties[p]["cost_units"], 2)
        parties[p]["cost_units"] = round(parties[p]["cost_units"], 2)
        parties[p]["benefit_units"] = round(parties[p]["benefit_units"], 2)
    return {
        "scenario_id": scenario["id"], "mode": run["run"]["mode"], "culprits": sorted(culprits),
        "attack_present": bool(scenario["ground_truth"].get("attack_present")),
        "parties": parties, "unresolved": unresolved_total,
        "dispute_resolved": bool(culprits) and not unresolved_total
                            and all(parties[p]["just_liability"] > 0 for p in culprits if p != "M"),
    }


def summarize_ledgers(rows: list[dict[str, Any]], params: IncentiveParams = IncentiveParams()) -> dict[str, Any]:
    per_party: dict[str, dict[str, Any]] = {}
    for p in PARTIES:
        honest_rows = [r for r in rows if r["parties"][p]["honest"]]
        per_party[p] = {
            "unjust_liability": sum(r["parties"][p]["unjust_liability"] for r in rows),
            "just_liability": sum(r["parties"][p]["just_liability"] for r in rows),
            "exonerated": sum(r["parties"][p]["exonerated"] for r in rows),
            "honest_rows": len(honest_rows),
            "honest_cost_units": round(sum(r["parties"][p]["cost_units"] for r in honest_rows), 2),
            "honest_benefit_units": round(sum(r["parties"][p]["benefit_units"] for r in honest_rows), 2),
            "honest_net_units": round(sum(r["parties"][p]["net_units"] for r in honest_rows), 2),
            "unjust_reasons": sorted({x for r in rows for x in r["parties"][p]["unjust_reasons"]}),
        }
    # 가해자가 있는 공격만 '해결됐는가' 를 묻는다. 프롬프트 인젝션(S16)처럼 지목할 당사자가 없는 사건은 제외한다.
    attacks = [r for r in rows if r["attack_present"] and r["culprits"]]
    return {
        "rows": len(rows),
        "per_party": per_party,
        "structural": {
            "unjust_liability_total": sum(v["unjust_liability"] for v in per_party.values()),
            "no_unjust_liability": all(v["unjust_liability"] == 0 for v in per_party.values()),
            "attacks": len(attacks),
            "attacks_resolved": sum(r["dispute_resolved"] for r in attacks),
            "attacks_unresolved": sorted({r["scenario_id"] for r in attacks if not r["dispute_resolved"]}),
            "attacks_without_party": sorted({r["scenario_id"] for r in rows if r["attack_present"] and not r["culprits"]}),
            "claim_status": "mock_result",
        },
        "parametric": {
            "params": asdict(params),
            "honest_net_positive": {p: per_party[p]["honest_net_units"] > 0 for p in PARTIES},
            "claim_status": "hypothesis",
            "note": "단위 비용·편익은 근거 없는 자리표시자다. 부호만 읽고 크기는 읽지 않는다. T 의 경제(수수료)는 모형에 없다.",
        },
    }
