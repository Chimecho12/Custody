"""완전성 판정: 합의된 증거 집합이 등록되었는가.

05 검토서 §4.7: '완전함' 은 **사전에 합의된 증거 집합이 제출되었다는 뜻** 으로 한정한다.
매니페스트는 사용자가 선언한 요청의 결손을 찾을 뿐 모든 호출을 복원하지 못한다.
R 의 `refused` 선언만으로 실제 미실행을 확인했다고 표시하지 않는다.
"""
from __future__ import annotations

from typing import Any

from .evidence import EvidenceSet

EXPECTED_BY_PARTY = {
    "U": ("contract", "observation"),
    "R": ("relay",),
    "M": ("receipt",),
}


def assess_completeness(ev: EvidenceSet, expected_parties: list[str]) -> dict[str, Any]:
    missing: list[str] = []
    for party in expected_parties:
        for name in EXPECTED_BY_PARTY[party]:
            if getattr(ev, name) is None:
                missing.append(f"{party}.{name}")

    relay_refused = ev.r is not None and ev.r["policy_decision"] == "refused"
    receipt_refused = ev.m is not None and ev.m["decision"] == "refused"

    if not missing:
        status = "complete"
        note = "합의된 증거가 모두 등록됨"
    elif relay_refused and set(missing) <= {"M.receipt", "U.observation"}:
        status = "not_observable"
        note = ("중개자가 요청을 거부했다고 선언했으므로 상위 호출 증거 부재는 정상일 수 있음. "
                "단, 실제 미실행을 확인한 것은 아님")
    elif receipt_refused and set(missing) <= {"U.observation"}:
        status = "not_observable"
        note = "모델 운영자가 실행 전 검사에서 거부함. 응답 수신 진술 부재는 정상"
    else:
        status = "gap"
        note = "합의된 증거 일부가 등록되지 않음. 결손은 위반 판정이 아니라 관측 상태다"
    return {
        "status": status,
        "expected_parties": list(expected_parties),
        "present_parties": ev.present_parties,
        "missing": missing,
        "relay_refused": relay_refused,
        "model_refused": receipt_refused,
        "note": note,
    }
