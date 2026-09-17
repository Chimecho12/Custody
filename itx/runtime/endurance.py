"""장기 가용성 실측: T 정지·복구를 낀 연속 요청으로 적체와 회복을 잰다.

benchmark 가 "한 조건에서 n 회" 를 재는 표본이라면, 이 실험은 "T 가 죽었다 살아나는 동안 정상 요청이
어떻게 되는가" 를 시간 순서대로 잰다. 세 구간(정지 전·정지 중·복구 후)마다 서비스 여부와 적체(미제출
증거) 크기를 기록하고, 복구 뒤 적체가 비는 데 걸린 시간과 모든 요청이 결국 사후 판정을 받았는지를 적는다.

모형 모델·루프백 TLS·단일 PC 결과다. 실제 원격 운영자의 장애·부하가 아니다 (claim_status mock_result).
"""
from __future__ import annotations

import platform
import tempfile
import time
from pathlib import Path

from .agent import Agent
from .lab import Lab
from .packages import write_document

PHASES = ("before", "outage", "after")
SERVED = ("accept", "accept_unverified")


def parse_outage(spec: str, requests: int) -> tuple[int, int]:
    try:
        start, end = (int(x) for x in spec.split(":"))
    except ValueError:
        raise ValueError("outage must look like START:END (request indexes)") from None
    if not 0 <= start < end <= requests:
        raise ValueError("outage window must satisfy 0 <= START < END <= requests")
    return start, end


def _phase(i: int, window: tuple[int, int]) -> str:
    return "before" if i < window[0] else "outage" if i < window[1] else "after"


def _wait_for_backlog_to_clear(agent: Agent, timeout_s: float) -> int | None:
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        agent.flush()
        if not agent.store.pending():
            return int((time.monotonic() - started) * 1000)
        time.sleep(0.1)
    return None


def _settle_verdicts(agent: Agent, subs: list[str], timeout_s: float) -> dict[str, int]:
    """모든 요청이 결국 사후 판정을 받는가. 증거가 T 에 닿기 전이면 refresh 가 실패하므로 기다린다."""
    got, deadline = 0, time.monotonic() + timeout_s
    for sub in subs:
        while time.monotonic() < deadline:
            try:
                record = agent.refresh(sub)
            except (RuntimeError, ValueError):
                time.sleep(0.1)
                continue
            if record.get("t_verdict"):
                got += 1
                break
            time.sleep(0.1)
    return {"verdicts": got, "requests": len(subs)}


def run_mode(agent: Agent, lab: Lab, mode: str, requests: int, window: tuple[int, int]) -> dict:
    rows, restart_at = [], None
    for i in range(requests):
        if i == window[0]:
            lab.stop_role("T")
        if i == window[1]:
            lab.restart_t()
            restart_at = time.monotonic()
            agent.flush()  # 백그라운드 작업자가 0.25 s 마다 하는 일을 복구 직후 한 번 당겨서 한다
        record = agent.request(f"endurance {mode} {i}", mode)
        rows.append({"index": i, "phase": _phase(i, window), "state": record["state"],
                     "served": record["state"] in SERVED, "elapsed_ms": record["elapsed_ms"],
                     "decision_wait_ms": (record.get("gate") or {}).get("waited_ms"),
                     "backlog_after": len(agent.store.pending()), "sub": record["sub"]})
    if restart_at is None:  # 창이 끝까지 열려 있었다면 여기서 복구한다
        lab.restart_t()
        restart_at = time.monotonic()
    recovery_ms = _wait_for_backlog_to_clear(agent, timeout_s=30)
    settled = _settle_verdicts(agent, [r["sub"] for r in rows], timeout_s=30)
    audit = agent.audit()
    by_phase = {}
    for phase in PHASES:
        inphase = [r for r in rows if r["phase"] == phase]
        by_phase[phase] = {"served": sum(r["served"] for r in inphase), "requests": len(inphase),
                           "states": sorted({r["state"] for r in inphase}),
                           "max_backlog": max((r["backlog_after"] for r in inphase), default=0),
                           "wait_ms_max": max((r["decision_wait_ms"] or 0 for r in inphase), default=0)}
    return {"mode": mode, "requests": requests, "outage_window": list(window), "rows": rows, "by_phase": by_phase,
            "max_backlog": max(r["backlog_after"] for r in rows),
            "recovery_ms_after_restart": recovery_ms, "backlog_cleared": recovery_ms is not None,
            "verdicts_eventually": settled, "all_verdicts_eventually": settled["verdicts"] == settled["requests"],
            "audit_ok_after_recovery": audit["ok"], "held_receipts": audit["held_receipts"]["held"],
            "held_receipts_missing": len(audit["held_receipts"]["missing"])}


def endurance(output, requests: int = 24, outage: str = "8:16", modes=("protect", "strict"), strict_timeout_ms: int | None = None):
    if type(requests) is not int or not 2 <= requests <= 500:
        raise ValueError("requests must be 2..500")
    window = parse_outage(outage, requests)
    results = []
    with tempfile.TemporaryDirectory(prefix="itx-endurance-") as directory:
        lab = Lab(Path(directory) / "lab")
        agent = Agent(lab.start())
        if strict_timeout_ms is not None:
            agent.config["strict_timeout_ms"] = strict_timeout_ms
        try:
            for mode in modes:
                results.append(run_mode(agent, lab, mode, requests, window))
        finally:
            agent.close()
            lab.close()
    report = {"profile": "itx-endurance/1", "transport": "actual_loopback_TLS", "model": "deterministic_mock",
              "governance": "single_operator", "host": platform.platform(), "python": platform.python_version(),
              "claim_status": "mock_result", "evidence_backlog_policy": "bounded", "results": results,
              "note": "T 정지·복구를 낀 연속 요청. 모형 모델·루프백·단일 PC 결과이며 실제 원격 장애·부하가 아니다. "
                      "protect 는 정지 중에도 로컬 증거로 계속하고 strict 는 기한 내 거부한다 — 둘 다 복구 뒤 적체가 비고 사후 판정을 받아야 한다."}
    if output:
        write_document(output, report)
    return report
