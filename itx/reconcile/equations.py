"""홉별 정합 등식 E1~E12.

설계 문서 v2 §4.7 의 E1~E9 를 05 검토서 §4 에 따라 고친 판본이다.

핵심 수정
- E10 (신설) 종단 응답 결합: M 이 서명한 응답 커밋과 U 가 실제 받은 응답 커밋을 **직접** 비교한다.
  E6·E7 은 각 당사자의 진술이 서로 모순되지 않는지만 본다. 중개자가 응답을 바꾸고 전후 해시를
  정직하게 적으면 E6·E7 은 모두 통과하지만 E10 이 실패한다.
- E4 승인 변환: 선언 식별자가 아니라 **승인된 변환의 재계산 결과**와 비교한다.
- E8 라우팅: '선언된 폴백' 이 아니라 '계약이 사전 승인한 집합에 속하는 실제 경로' 를 검사한다.
- E9 아티팩트: 원래 요청 모델이 아니라 **승인된 실제 모델**의 기준 해시와 비교한다.
- E11 시도 결합, E12 계약 만료를 추가한다.

각 등식은 pass / fail / not_evaluable 중 하나이며 not_evaluable 은 사유를 반드시 남긴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from itx.crypto import commit_hex
from .evidence import EvidenceSet
from .transforms import IDENTITY, is_recomputable_request_transform

PASS, FAIL, NA = "pass", "fail", "not_evaluable"

# 신뢰 등급 (AIR-02 §11.9 + 설계문서 §4.8 의 네 번째 등급)
G_EXT = "externally_corroborable"      # 두 당사자의 서명 진술을 서로 비교
G_SELF = "self_asserted"               # 한 당사자의 자기 주장만 근거
G_SALT = "third_party_salted"          # 솔트 보유자(T·권한 감사자)만 재계산 가능

EQUATION_DOCS: dict[str, dict[str, str]] = {
    "E1": {"title": "사용자 자기 정합", "hop": "U", "what": "계약의 req_commit == commit(salt, H(request))"},
    "E2": {"title": "U→R 구간", "hop": "U→R", "what": "R.in_commit == U.req_commit"},
    "E3": {"title": "R→M 진술 일치", "hop": "R→M", "what": "R.out_commit == M.request_commit"},
    "E4": {"title": "승인된 요청 변환", "hop": "R", "what": "M 이 받은 요청 커밋 ∈ 승인 변환의 재계산 결과"},
    "E5": {"title": "nonce 전파", "hop": "R", "what": "M.eat_nonce == U.nonce == R.nonce_forwarded"},
    "E6": {"title": "M→R 진술 일치", "hop": "M→R", "what": "M.response_commit == R.resp_in_commit"},
    "E7": {"title": "R→U 진술 일치", "hop": "R→U", "what": "R.resp_out_commit == U.resp_commit"},
    "E8": {"title": "승인된 경로", "hop": "R", "what": "실제 모델 ∈ 계약 허용 집합, 폴백은 선언 필요"},
    "E9": {"title": "모델 아티팩트", "hop": "M", "what": "M.model_hash == reference(실제 모델)"},
    "E10": {"title": "종단 응답 결합", "hop": "M⇢U", "what": "M.response_commit == U.resp_commit (무변환 정책)"},
    "E11": {"title": "시도 결합", "hop": "all", "what": "모든 진술의 attempt_id 일치"},
    "E12": {"title": "계약 유효기간", "hop": "U", "what": "수신 시각 <= 계약 만료"},
}


@dataclass
class EqResult:
    id: str
    result: str
    reason: str
    compared: list[str] = field(default_factory=list)
    trust_grade: str = G_EXT
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "reason": self.reason,
            "compared": list(self.compared),
            "trust_grade": self.trust_grade,
            "detail": dict(self.detail),
            "title": EQUATION_DOCS[self.id]["title"],
            "hop": EQUATION_DOCS[self.id]["hop"],
        }


def _na(eid: str, reason: str, grade: str = G_EXT) -> EqResult:
    return EqResult(eid, NA, reason, trust_grade=grade)


def _cmp(eid: str, a: Any, b: Any, label: str, grade: str = G_EXT, **detail: Any) -> EqResult:
    ok = a is not None and b is not None and a == b
    return EqResult(
        eid, PASS if ok else FAIL,
        "일치" if ok else "불일치",
        compared=[label], trust_grade=grade, detail=detail,
    )


def evaluate_equations(ev: EvidenceSet) -> dict[str, EqResult]:
    c, r, m, o, p = ev.c, ev.r, ev.m, ev.o, ev.private
    res: dict[str, EqResult] = {}

    # E1 ---------------------------------------------------------------
    if c is None:
        res["E1"] = _na("E1", "요청 계약 없음", G_SALT)
    elif p is None:
        res["E1"] = _na("E1", "사용자 비공개 증거(솔트·요청 해시) 없음", G_SALT)
    else:
        expected = commit_hex(p.salt, p.request_hash)
        res["E1"] = _cmp("E1", c["req_commit"], expected, "U.req_commit vs commit(salt, H(request))", G_SALT)

    # E2 ---------------------------------------------------------------
    if c is None or r is None:
        res["E2"] = _na("E2", "계약 또는 중계 진술 없음")
    else:
        res["E2"] = _cmp("E2", r["in_commit"], c["req_commit"], "R.in_commit vs U.req_commit")

    # E3 ---------------------------------------------------------------
    if r is None or m is None or m.get("request_commit") is None:
        res["E3"] = _na("E3", "중계 진술 또는 추론 영수증 없음")
    else:
        res["E3"] = _cmp("E3", r["out_commit"], m["request_commit"], "R.out_commit vs M.request_commit")

    # E4 ---------------------------------------------------------------
    res["E4"] = _eval_request_transform(ev)

    # E5 ---------------------------------------------------------------
    if c is None:
        res["E5"] = _na("E5", "요청 계약 없음")
    elif m is None and r is None:
        res["E5"] = _na("E5", "nonce 를 보고한 당사자 없음")
    else:
        compared, ok, why = [], True, []
        if m is not None:
            compared.append("M.eat_nonce vs U.nonce")
            if m.get("eat_nonce") != c["nonce"]:
                ok = False
                why.append("M 영수증의 eat_nonce 가 없거나 다름")
        if r is not None:
            compared.append("R.nonce_forwarded vs U.nonce")
            if r.get("nonce_forwarded") != c["nonce"]:
                ok = False
                why.append("R 이 전달했다고 적은 nonce 가 없거나 다름")
        res["E5"] = EqResult("E5", PASS if ok else FAIL, "일치" if ok else "; ".join(why), compared)

    # E6 ---------------------------------------------------------------
    if r is None or m is None or m.get("response_commit") is None or r.get("resp_in_commit") is None:
        res["E6"] = _na("E6", "중계 진술 또는 추론 영수증(응답) 없음")
    else:
        res["E6"] = _cmp("E6", m["response_commit"], r["resp_in_commit"], "M.response_commit vs R.resp_in_commit")

    # E7 ---------------------------------------------------------------
    if r is None or o is None or r.get("resp_out_commit") is None:
        res["E7"] = _na("E7", "중계 진술 또는 사용자 수신 진술 없음")
    else:
        res["E7"] = _cmp("E7", r["resp_out_commit"], o["resp_commit"], "R.resp_out_commit vs U.resp_commit")

    # E8 ---------------------------------------------------------------
    res["E8"] = _eval_route(ev)

    # E9 ---------------------------------------------------------------
    if m is None:
        res["E9"] = _na("E9", "추론 영수증 없음")
    else:
        ref = ev.reference_model_hashes.get(m["model_id"])
        if ref is None:
            res["E9"] = _na("E9", f"모델 {m['model_id']} 의 기준 해시가 등록되지 않음")
        else:
            res["E9"] = _cmp("E9", m["model_hash"], ref, f"M.model_hash vs reference({m['model_id']})",
                             detail={"note": "아티팩트 식별이지 실행 계산의 일치가 아니다 (AIR-02 §11.5)"})

    # E10 --------------------------------------------------------------
    res["E10"] = _eval_end_to_end_response(ev)

    # E11 --------------------------------------------------------------
    ids = {}
    for name, pl in (("U.contract", c), ("R.relay", r), ("M.receipt", m), ("U.observation", o)):
        if pl is not None:
            ids[name] = pl.get("attempt_id")
    if len(ids) < 2:
        res["E11"] = _na("E11", "비교할 진술이 2개 미만")
    else:
        distinct = set(ids.values())
        res["E11"] = EqResult(
            "E11", PASS if len(distinct) == 1 else FAIL,
            "일치" if len(distinct) == 1 else "attempt_id 불일치 (재전송·다른 시도의 응답 가능)",
            compared=[" vs ".join(ids.keys())], detail={"attempt_ids": ids},
        )

    # E12 --------------------------------------------------------------
    if c is None or o is None:
        res["E12"] = _na("E12", "계약 또는 수신 진술 없음", G_SELF)
    else:
        ok = o["received_at"] <= c["expires_at"]
        res["E12"] = EqResult("E12", PASS if ok else FAIL,
                              "유효기간 내" if ok else "계약 만료 후 수신",
                              ["U.received_at vs U.expires_at"], G_SELF,
                              {"received_at": o["received_at"], "expires_at": c["expires_at"]})
    return res


def _eval_request_transform(ev: EvidenceSet) -> EqResult:
    c, r, m, p = ev.c, ev.r, ev.m, ev.private
    if c is None:
        return _na("E4", "요청 계약 없음")
    # M 이 실제로 받은 요청의 커밋. M 관측이 있으면 그것을, 없으면 R 의 자기 주장을 쓴다.
    if m is not None and m.get("request_commit") is not None:
        actual, source, grade = m["request_commit"], "M.request_commit", G_EXT
    elif r is not None:
        actual, source, grade = r["out_commit"], "R.out_commit (self-asserted)", G_SELF
    else:
        return _na("E4", "M 이 받은 요청을 보고한 당사자 없음")

    allowed = list(c["allowed_request_transforms"])
    declared = r["request_transform_id"] if r is not None else None
    approved: dict[str, str] = {}
    if IDENTITY in allowed:
        approved[IDENTITY] = c["req_commit"]
    if p is not None:
        for tid, cm in p.expected_request_commits.items():
            if tid in allowed:
                approved[tid] = cm

    detail = {"declared_transform": declared, "allowed": allowed, "source": source}
    if declared is not None and declared not in allowed:
        return EqResult("E4", FAIL, f"선언된 변환 {declared!r} 은 계약이 허용하지 않음",
                        [f"{source} vs approved set"], grade, detail)
    matched = [tid for tid, cm in approved.items() if cm == actual]
    if matched:
        detail["matched_transform"] = matched[0]
        if declared is not None and declared not in matched:
            # 결과는 승인된 변환과 같지만 선언이 다르다. 위반은 아니고 기록한다.
            detail["note"] = f"결과는 {matched[0]} 와 일치하나 선언은 {declared}"
        return EqResult("E4", PASS, f"승인된 변환 {matched[0]} 의 재계산 결과와 일치",
                        [f"{source} vs approved set"], grade, detail)
    unverifiable = [t for t in allowed if not is_recomputable_request_transform(t)]
    if unverifiable:
        return EqResult("E4", NA, f"허용 변환 {unverifiable} 은 재계산 불가 (선언 확인·관계 미검증)",
                        [f"{source} vs approved set"], grade, detail)
    # 계약이 무변환 외의 변환을 허용하는데 사용자 비공개 증거가 없으면, 그 변환의 기대 커밋을
    # 재계산할 수 없다. 이것은 위반의 증거가 아니라 증거 부족이다 — 솔트를 받지 못한 감사자가
    # 정상 경로를 '요청 변조' 로 잘못 귀속하지 않도록 구분한다.
    if p is None and any(t != IDENTITY for t in allowed):
        detail["missing"] = "user private evidence (expected_request_commits)"
        return EqResult("E4", NA, "승인 변환의 기대 커밋을 재계산할 사용자 비공개 증거가 없음",
                        [f"{source} vs approved set"], G_SALT, detail)
    return EqResult("E4", FAIL, "M 이 받은 요청이 승인된 어떤 변환의 결과와도 다름",
                    [f"{source} vs approved set"], grade, detail)


def _eval_route(ev: EvidenceSet) -> EqResult:
    c, r, m = ev.c, ev.r, ev.m
    if c is None:
        return _na("E8", "요청 계약 없음")
    if m is not None:
        actual, source, grade = m["model_id"], "M.model_id", G_EXT
    elif r is not None:
        actual, source, grade = r["upstream_model"], "R.upstream_model (self-asserted)", G_SELF
    else:
        return _na("E8", "실제 경로를 보고한 당사자 없음")
    detail = {"actual_model": actual, "requested_model": c["requested_model"],
              "allowed_models": c["allowed_models"], "fallback_policy": c["fallback_policy"],
              "relay_decision": r["policy_decision"] if r else None, "source": source}
    if actual == c["requested_model"]:
        return EqResult("E8", PASS, "요청한 모델로 처리됨", [f"{source} vs U.requested_model"], grade, detail)
    if actual not in c["allowed_models"]:
        kind = "선언됨" if (r is not None and r["policy_decision"] == "fallback") else "미선언"
        detail["route_kind"] = "declared_unapproved" if kind == "선언됨" else "undeclared"
        return EqResult("E8", FAIL, f"허용되지 않은 모델 {actual} 로 처리됨 ({kind})",
                        [f"{source} vs U.allowed_models"], grade, detail)
    # 허용 집합 안의 다른 모델 = 폴백 후보
    if c["fallback_policy"] == "none":
        detail["route_kind"] = "fallback_forbidden"
        return EqResult("E8", FAIL, "계약이 폴백을 허용하지 않음", [f"{source} vs U.allowed_models"], grade, detail)
    if r is None:
        detail["route_kind"] = "fallback_undeclared_unknown"
        return EqResult("E8", NA, "허용 모델이지만 폴백 선언(중계 진술)을 확인할 수 없음",
                        [f"{source} vs U.allowed_models"], grade, detail)
    if r["policy_decision"] == "fallback":
        detail["route_kind"] = "declared_approved_fallback"
        return EqResult("E8", PASS, "사전 승인된 폴백이며 중개자가 선언함",
                        [f"{source} vs U.allowed_models", "R.policy_decision"], grade, detail)
    detail["route_kind"] = "undeclared_fallback"
    return EqResult("E8", FAIL, "허용 모델이지만 중개자가 폴백을 선언하지 않음 (숨은 라우팅)",
                    [f"{source} vs U.allowed_models", "R.policy_decision"], grade, detail)


def _eval_end_to_end_response(ev: EvidenceSet) -> EqResult:
    c, r, m, o = ev.c, ev.r, ev.m, ev.o
    if m is None or m.get("response_commit") is None:
        return _na("E10", "추론 영수증(응답 커밋) 없음 — 종단 무결성을 확립할 수 없음")
    if o is None:
        return _na("E10", "사용자 수신 진술 없음")
    allowed = list(c["allowed_response_transforms"]) if c is not None else [IDENTITY]
    declared = r["response_transform_id"] if r is not None else None
    detail = {"declared_transform": declared, "allowed": allowed}
    if declared is not None and declared not in allowed:
        return EqResult("E10", FAIL, f"선언된 응답 변환 {declared!r} 은 계약이 허용하지 않음",
                        ["M.response_commit vs U.resp_commit"], G_EXT, detail)
    if allowed != [IDENTITY]:
        return EqResult("E10", NA, "첫 버전은 응답 무변환 정책만 재계산 가능", ["M.response_commit vs U.resp_commit"], G_EXT, detail)
    ok = m["response_commit"] == o["resp_commit"]
    return EqResult("E10", PASS if ok else FAIL,
                    "M 이 서명한 응답과 U 가 받은 응답이 같음" if ok else "M 이 서명한 응답과 U 가 받은 응답이 다름",
                    ["M.response_commit vs U.resp_commit"], G_EXT, detail)
