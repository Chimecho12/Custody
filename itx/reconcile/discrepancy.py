"""불일치 분류(D-코드)와 귀속.

05 검토서 §4.3, §4.5: '상대방 진술 불일치(contradiction)' 와 '승인된 변환 위반(violation)' 을
다른 코드로 기록하고, 귀속은 항상 그 귀속이 의존하는 신뢰 가정과 함께 적는다.
서명 검증은 "누가 서명했는가" 를 확인할 뿐, 서명자가 정직하게 관측했는가는 별도 가정이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .equations import EqResult, FAIL, G_SELF

SEV_VIOLATION = "violation"          # 계약·정책 위반이 관측됨
SEV_CONTRADICTION = "contradiction"  # 두 당사자의 진술이 모순. 누가 거짓인지는 미확정
SEV_OBSERVATION = "observation"      # 결손·지연 등 관측 상태. 위반 판정 아님

DISCREPANCY_DOCS: dict[str, str] = {
    "D-USER-SELF": "사용자 계약과 사용자 비공개 증거가 맞지 않음 (사용자 측 자료 문제)",
    "D-REQ-CONTRADICT": "요청에 대한 두 당사자의 진술이 모순",
    "D-REQ-UNAPPROVED": "M 이 받은 요청이 승인된 변환의 결과가 아님 (요청 변조)",
    "D-NONCE": "nonce 미전달·교체",
    "D-RESP-CONTRADICT": "응답에 대한 두 당사자의 진술이 모순",
    "D-RESP-UNAPPROVED": "사용자가 받은 응답이 M 이 서명한 응답과 다름 (응답 변조)",
    "D-ROUTE-UNAPPROVED": "허용되지 않은 모델·경로로 처리됨",
    "D-ROUTE-UNDECLARED": "허용 모델이지만 폴백을 선언하지 않음 (숨은 라우팅)",
    "D-MODEL-ART": "모델 아티팩트 해시가 기준값과 다름",
    "D-ATTEMPT-MISMATCH": "진술 간 attempt_id 불일치 (재전송·다른 시도의 응답 가능)",
    "D-EXPIRED": "계약 만료 후 처리",
    "D-SIG-INVALID": "서명 검증 실패 진술 존재",
    "D-ISSUER-UNAUTHORIZED": "발행자가 낼 권한이 없는 유형의 진술 (다른 당사자 역할 사칭)",
    "D-RECEIPT-PRESENTED-DIFFERS": "M 이 등록한 영수증과 R 이 사용자에게 보여 준 영수증이 다름",
    "D-GAP": "합의된 증거가 등록되지 않음 (결손)",
    "D-LATE": "등록 지연이 임계를 넘음",
}


@dataclass
class Discrepancy:
    code: str
    severity: str
    equations: list[str]
    attribution: str
    attribution_basis: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "equations": list(self.equations),
            "attribution": self.attribution,
            "attribution_basis": self.attribution_basis,
            "description": DISCREPANCY_DOCS.get(self.code, ""),
            "detail": dict(self.detail),
        }


TM1 = "TM1: U 집행 모듈과 M 입출력 관측은 정직, R 은 악성일 수 있음"


def classify(eqs: dict[str, EqResult], present_parties: list[str]) -> list[Discrepancy]:
    out: list[Discrepancy] = []
    has_m = "M" in present_parties

    def failed(eid: str) -> bool:
        return eqs[eid].result == FAIL

    if failed("E1"):
        out.append(Discrepancy("D-USER-SELF", SEV_CONTRADICTION, ["E1"], "U (증거 묶음)",
                               "사용자 자신의 계약과 비공개 증거 비교"))
    if failed("E2"):
        out.append(Discrepancy("D-REQ-CONTRADICT", SEV_CONTRADICTION, ["E2"], "U 또는 R (U→R 구간)",
                               "두 서명 진술의 모순만 확인. 어느 쪽이 거짓인지는 독립 관측 필요"))
    if failed("E3"):
        out.append(Discrepancy("D-REQ-CONTRADICT", SEV_CONTRADICTION, ["E3"], "R 또는 M (R→M 구간)",
                               "두 서명 진술의 모순만 확인"))
    if failed("E4"):
        e = eqs["E4"]
        if e.trust_grade == G_SELF:
            out.append(Discrepancy("D-REQ-UNAPPROVED", SEV_VIOLATION, ["E4"], "R (자기 주장 기준)",
                                   "R 스스로 승인 밖 변환을 선언·기록함", e.detail))
        else:
            out.append(Discrepancy("D-REQ-UNAPPROVED", SEV_VIOLATION, ["E4"], "R",
                                   f"{TM1} — M 의 요청 관측이 정직하다는 가정 하에 R 에 귀속", e.detail))
    if failed("E5"):
        out.append(Discrepancy("D-NONCE", SEV_VIOLATION, ["E5"], "R" if has_m else "R (자기 주장 기준)",
                               f"{TM1} — nonce 는 U 가 발급하고 R 이 전달해야 함", eqs["E5"].detail))
    if failed("E6"):
        out.append(Discrepancy("D-RESP-CONTRADICT", SEV_CONTRADICTION, ["E6"], "R 또는 M (M→R 구간)",
                               "두 서명 진술의 모순만 확인"))
    if failed("E7"):
        out.append(Discrepancy("D-RESP-CONTRADICT", SEV_CONTRADICTION, ["E7"], "R 또는 U (R→U 구간)",
                               "두 서명 진술의 모순만 확인"))
    if failed("E10"):
        out.append(Discrepancy("D-RESP-UNAPPROVED", SEV_VIOLATION, ["E10"], "R",
                               f"{TM1} — M 이 서명한 응답과 U 가 받은 응답이 다르므로 사이의 R 에 귀속. "
                               "R·M 이 공모해 일치하는 거짓 진술을 내면 이 등식은 위반을 보지 못함",
                               eqs["E10"].detail))
    if failed("E8"):
        kind = eqs["E8"].detail.get("route_kind", "")
        code = "D-ROUTE-UNDECLARED" if kind == "undeclared_fallback" else "D-ROUTE-UNAPPROVED"
        out.append(Discrepancy(code, SEV_VIOLATION, ["E8"], "R",
                               f"{TM1} — 실제 모델은 M 영수증(또는 R 선언)에서, 승인 집합은 U 계약에서", eqs["E8"].detail))
    if failed("E9"):
        out.append(Discrepancy("D-MODEL-ART", SEV_VIOLATION, ["E9"], "M 또는 R",
                               "M 이 다른 아티팩트를 서명했거나 R 이 다른 M 으로 보냈을 수 있음", eqs["E9"].detail))
    if failed("E11"):
        out.append(Discrepancy("D-ATTEMPT-MISMATCH", SEV_VIOLATION, ["E11"], "R",
                               f"{TM1} — 다른 시도의 응답·영수증이 이 시도에 전달됨 (재전송 후보)", eqs["E11"].detail))
    if failed("E12"):
        out.append(Discrepancy("D-EXPIRED", SEV_VIOLATION, ["E12"], "R (지연) 또는 정책",
                               "만료는 계약 위반이지만 원인(지연·재전송)은 별도 조사", eqs["E12"].detail))
    return out
