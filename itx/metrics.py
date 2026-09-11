"""지표 (05 검토서 §3.2, §7.3). 탐지·차단·피해 억제를 따로 센다.

- 탐지: 최종 판정이 failed 인가 (공격이 있고 증거로 관측 가능한 경우에 한해).
- 사용 전 방어: 공격 시도에서 응답이 업무에 **소비되지 않았는가** (게이트 격리·거부, M 의 실행 전 거부 포함).
- 피해 노출: 공격 응답이 업무에 소비됐는가 (관찰 모드의 '수신 즉시 소비' 포함).
- 오차단: 공격이 없는데 격리·거부했는가. 응답 자체가 없던 경우(no_response)는 차단이 아니다.
- 안전 완료: 검증을 통과해 수용됐는가 (accept_unverified 는 아님).
- 가용성 비용: 왕복 지연, 결정 대기.
분모와 제외 건수를 함께 보고한다. 표본이 작으므로 비율은 시나리오 비교용이다.
"""
from __future__ import annotations

from statistics import mean
from typing import Any

BLOCKING = ("quarantine", "reject", "reject_timeout")


def attempt_metrics(ground_truth: dict[str, Any], gate: dict[str, Any], verdict: dict[str, Any],
                    sent_at: int, received_at: int | None) -> dict[str, Any]:
    attack = bool(ground_truth.get("attack_present"))
    detectable = bool(ground_truth.get("detectable_by_evidence", True))
    action = gate["action"]
    blocked = action in BLOCKING
    consumed = gate.get("consumed_at") is not None
    consumed_before = bool(gate.get("consumed_before_decision"))
    return {
        "attack_present": attack,
        "detectable_by_evidence": detectable,
        "detected_by_verdict": verdict["verification_status"] == "failed",
        "verdict_status": verdict["verification_status"],
        "completeness": verdict["completeness"],
        "gate_action": action,
        "consumed": consumed,
        "blocked_before_use": attack and not consumed,
        "harm_exposed": attack and bool(ground_truth.get("harm_if_consumed")) and consumed,
        "false_block": (not attack) and blocked,
        "safe_completion": action == "accept",
        "consumed_before_decision": consumed_before,
        "rtt_ms": (received_at - sent_at) if received_at is not None else None,
        "decision_wait_ms": gate.get("waited_ms"),
        "evidence_complete": verdict["completeness"] == "complete",
    }


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    """모드별 집계. 각 비율은 (분자/분모) 와 함께 낸다."""
    by_mode: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        for a in r["attempts"]:
            by_mode.setdefault(r["run"]["mode"], []).append({**a["metrics"], "scenario_id": r["run"]["scenario_id"]})
    out: dict[str, Any] = {}
    for mode, rows in by_mode.items():
        attacks = [m for m in rows if m["attack_present"]]
        detectable = [m for m in attacks if m["detectable_by_evidence"]]
        legit = [m for m in rows if not m["attack_present"]]
        legit_with_response = [m for m in legit if m["gate_action"] != "no_response"]
        waits = [m["decision_wait_ms"] for m in rows if m["decision_wait_ms"] is not None]
        rtts = [m["rtt_ms"] for m in rows if m["rtt_ms"] is not None]
        out[mode] = {
            "attempts": len(rows),
            "attack_attempts": len(attacks),
            "detection": {"num": sum(m["detected_by_verdict"] for m in detectable), "den": len(detectable),
                          "rate": _rate(sum(m["detected_by_verdict"] for m in detectable), len(detectable)),
                          "excluded_undetectable": len(attacks) - len(detectable)},
            "defense_before_use": {"num": sum(m["blocked_before_use"] for m in attacks), "den": len(attacks),
                                   "rate": _rate(sum(m["blocked_before_use"] for m in attacks), len(attacks))},
            "harm_exposed": {"num": sum(m["harm_exposed"] for m in attacks), "den": len(attacks)},
            "false_block": {"num": sum(m["false_block"] for m in legit_with_response), "den": len(legit_with_response),
                            "rate": _rate(sum(m["false_block"] for m in legit_with_response), len(legit_with_response)),
                            "excluded_no_response": len(legit) - len(legit_with_response)},
            "safe_completion_legit": {"num": sum(m["safe_completion"] for m in legit_with_response), "den": len(legit_with_response),
                                      "rate": _rate(sum(m["safe_completion"] for m in legit_with_response), len(legit_with_response))},
            "evidence_complete": {"num": sum(m["evidence_complete"] for m in rows), "den": len(rows)},
            "decision_wait_ms": {"mean": round(mean(waits), 1) if waits else None, "max": max(waits) if waits else None},
            "rtt_ms": {"mean": round(mean(rtts), 1) if rtts else None, "max": max(rtts) if rtts else None},
        }
    return out
