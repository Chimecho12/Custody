"""Repeatable mock-model TLS comparison, with explicit safety denominators."""
from __future__ import annotations

import math
import platform
import tempfile
from pathlib import Path

from .agent import Agent
from .lab import Lab
from .packages import write_document


def benchmark(output, repeats=5):
    if type(repeats) is not int or not 1 <= repeats <= 100:
        raise ValueError("repeats must be 1..100")
    rows = []
    with tempfile.TemporaryDirectory(prefix="itx-benchmark-") as directory:
        lab = Lab(Path(directory) / "lab")
        agent = Agent(lab.start())
        try:
            for condition in ("normal", "response_tamper", "t_down"):
                if condition == "t_down":
                    lab.stop_role("T")
                for mode in ("observe", "protect", "strict"):
                    records = [agent.request(f"repeatable benchmark sample {i}", mode,
                               "response_tamper" if condition == "response_tamper" else "normal") for i in range(repeats)]
                    elapsed = sorted(r["elapsed_ms"] for r in records)
                    attack = condition == "response_tamper"
                    safe = sum(r["state"] == "accept" and all(c["result"] == "pass" for c in r["checks"].values())
                               and r["elapsed_ms"] <= 5000 for r in records)
                    rows.append({"condition": condition, "mode": mode, "count": repeats,
                        "safe_completions_within_5000ms": safe, "safe_completion_denominator": repeats,
                        "attacks_blocked_before_release": sum(r["state"] == "quarantine" for r in records) if attack else None,
                        "attack_denominator": repeats if attack else 0,
                        "normal_requests_not_released": sum(r["response"] is None for r in records) if not attack else None,
                        "latency_ms": {"min": elapsed[0], "p50": elapsed[math.ceil(repeats*.5)-1],
                                       "p95": elapsed[math.ceil(repeats*.95)-1], "max": elapsed[-1]},
                        "states": [r["state"] for r in records]})
        finally:
            agent.close()
            lab.close()
    report = {"profile": "itx-benchmark/1", "transport": "actual_loopback_TLS", "model": "deterministic_mock",
              "governance": "single_operator", "host": platform.platform(), "python": platform.python_version(),
              "concurrency": 1, "repeats_per_cell": repeats, "rows": rows,
              "note": "기능 비교용 표본. 모형 모델·루프백 결과이며 실제 LLM·원격 성능 추정이 아니다. observe는 안전 완료로 세지 않는다."}
    write_document(output, report)
    return report
