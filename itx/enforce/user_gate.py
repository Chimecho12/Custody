"""사용자 측 집행 모듈: 응답을 화면·업무·도구에 넘기기 전에 검사한다.

05 검토서 §3.1, §7.2 의 세 모드.
- observe : 모두 허용하고 상태만 표시. 최초 기준선·공격 관측용.
- protect : 필수 로컬 검증 후 허용. 실패한 응답은 격리. T 장애 시에도 로컬 증거로 계속.
- strict  : 로컬 검증 + T 의 판정까지 확인 후 수용. 기한 내 못 얻으면 명시적 거부.

'경로 밖' 인 T 는 차단하지 않는다. 차단은 U 가 자기 정책으로 한다. T 의 판정은 U 가 승인한
정책의 입력이며, T 가 '통과' 라고 해도 로컬 검증이 실패하면 격리한다 (T 를 맹신하지 않음).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from itx.statements import SignedStatement

MODES = ("observe", "protect", "strict")

PASS, FAIL, NA = "pass", "fail", "not_evaluable"

#: 검사의 근거 종류. 같은 'pass' 라도 U 가 직접 계산해 얻은 것과 서명자의 말을 기준값과 맞춰 본 것은
#: 다른 주장이다. 화면은 이 값을 그대로 표기하고 T 의 대조 등식과 섞지 않는다.
B_LOCAL = "measured_locally"        # U 가 직접 계산·비교: 해시·서명·nonce·시각·본문
B_ATTESTED = "signed_self_report"   # 서명은 U 가 검증했지만 내용은 서명자의 주장: 모델 id·모델 해시·폴백 선언
CHECK_BASIS: dict[str, str] = {
    "not_expired": B_LOCAL, "receipt_present": B_LOCAL, "receipt_signature": B_LOCAL, "nonce_match": B_LOCAL,
    "request_binding": B_LOCAL, "response_binding": B_LOCAL, "attempt_match": B_LOCAL, "tool_policy": B_LOCAL,
    # M 이 서명한 model_id·model_hash 를 기준값과 맞춰 볼 뿐, 그 모델이 실제로 실행됐다는 증명이 아니다.
    "model_hash_reference": B_ATTESTED,
    # 실제 경로는 M 의 model_id 또는 R 의 upstream_model 선언에서 읽는다. 폴백 선언도 R 의 자기보고다.
    "route_allowed": B_ATTESTED,
    # 발행자·역할·서명·요청 결합은 U 가 직접 검증한다 (런타임 Agent 가 낸다).
    "M_authority": B_LOCAL, "R_authority": B_LOCAL,
}

#: protect/strict 에서 not_evaluable 이면 수용하지 않고 격리하는 검사.
#: request_binding 이 여기 있는 이유: 계약이 재계산 불가한 요청 변환을 허용하면 이 검사는
#: not_evaluable 이 되고, 그 상태에서 수용하면 "M 이 받은 요청이 내가 보낸 요청" 이라는
#: 근거 없이 응답을 업무에 쓰는 것이 된다. 응답 쪽(response_binding)과 같은 기준으로 다룬다.
_REQUIRED_LOCAL_CHECKS = ("receipt_present", "request_binding", "response_binding", "nonce_match")


@dataclass
class GateDecision:
    mode: str
    action: str  # accept | accept_unverified | quarantine | reject | reject_timeout
    reasons: list[str]
    local_checks: dict[str, dict[str, str]]
    verdict_status: str | None
    received_at: int
    decided_at: int
    consumed_at: int | None
    waited_ms: int

    @property
    def consumed_before_decision(self) -> bool:
        return self.consumed_at is not None and self.consumed_at < self.decided_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "action": self.action,
            "reasons": list(self.reasons),
            "local_checks": self.local_checks,
            "verdict_status": self.verdict_status,
            "received_at": self.received_at,
            "decided_at": self.decided_at,
            "consumed_at": self.consumed_at,
            "waited_ms": self.waited_ms,
            "consumed_before_decision": self.consumed_before_decision,
        }


class UserGate:
    def __init__(
        self,
        mode: str,
        trusted_model_keys: dict[str, bytes],
        reference_model_hashes: dict[str, str],
        allow_tool_directives: bool = False,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode}")
        self.mode = mode
        self.trusted_model_keys = trusted_model_keys
        self.reference_model_hashes = dict(reference_model_hashes)
        self.allow_tool_directives = allow_tool_directives

    # -- 로컬 검증 (T 없이 U 혼자 할 수 있는 것) --------------------------------
    def local_checks(
        self,
        contract: dict[str, Any],
        received_commit: str,
        response_body: dict[str, Any] | None,
        inline_receipt: SignedStatement | None,
        inline_relay: SignedStatement | None,
        now: int,
        expected_request_commits: dict[str, str] | None = None,
    ) -> dict[str, dict[str, str]]:
        checks: dict[str, dict[str, str]] = {}
        expected_request_commits = expected_request_commits or {}

        def put(name: str, result: str, why: str) -> None:
            checks[name] = {"result": result, "reason": why, "basis": CHECK_BASIS[name]}

        # 1. 계약 만료
        put("not_expired", PASS if now <= contract["expires_at"] else FAIL,
            "유효기간 내" if now <= contract["expires_at"] else "계약 만료 후 수신")

        # 2. 인라인 영수증
        if inline_receipt is None:
            put("receipt_present", FAIL, "모델 영수증이 응답에 동봉되지 않음 (M 비협조 또는 R 이 제거)")
            for n in ("receipt_signature", "nonce_match", "request_binding", "response_binding", "attempt_match", "model_hash_reference"):
                put(n, NA, "영수증 없음")
        else:
            put("receipt_present", PASS, "동봉됨")
            pub = self.trusted_model_keys.get(inline_receipt.kid)
            sig_ok = pub is not None and inline_receipt.verify_with(pub)
            put("receipt_signature", PASS if sig_ok else FAIL,
                "신뢰 모델 키로 검증됨" if sig_ok else "신뢰 모델 키로 검증되지 않음")
            m = inline_receipt.payload
            if sig_ok:
                put("nonce_match", PASS if m.get("eat_nonce") == contract["nonce"] else FAIL,
                    "eat_nonce == 계약 nonce" if m.get("eat_nonce") == contract["nonce"] else "eat_nonce 가 없거나 다름 (재전송·nonce 제거 후보)")
                # 요청 결합: M 이 서명한 '받은 요청' 이 내가 보낸 요청(또는 승인 변환의 결과)인가
                approved = {contract["req_commit"]} if "identity" in contract["allowed_request_transforms"] else set()
                approved |= {c for t, c in expected_request_commits.items() if t in contract["allowed_request_transforms"]}
                if m.get("request_commit") in approved:
                    put("request_binding", PASS, "M 이 받은 요청 == 내가 보낸 요청(승인 변환 포함)")
                elif any(t != "identity" and t not in expected_request_commits for t in contract["allowed_request_transforms"]):
                    put("request_binding", NA, "재계산 불가한 변환을 계약이 허용함")
                else:
                    put("request_binding", FAIL, "M 이 받은 요청 != 내가 보낸 요청 (중개자 변조 후보)")
                put("response_binding", PASS if m.get("response_commit") == received_commit else FAIL,
                    "M 이 서명한 응답 == 받은 응답" if m.get("response_commit") == received_commit else "M 이 서명한 응답 != 받은 응답 (변조 후보)")
                put("attempt_match", PASS if m.get("attempt_id") == contract["attempt_id"] else FAIL,
                    "attempt_id 일치" if m.get("attempt_id") == contract["attempt_id"] else "다른 시도의 영수증")
                ref = self.reference_model_hashes.get(m.get("model_id", ""))
                if ref is None:
                    put("model_hash_reference", NA, "기준 해시 미등록 모델")
                else:
                    put("model_hash_reference", PASS if m.get("model_hash") == ref else FAIL,
                        "기준 해시 일치" if m.get("model_hash") == ref else "기준 해시 불일치")
                # 3. 경로/폴백 (M 의 model_id 기준)
                self._route_check(put, contract, m.get("model_id"), inline_relay)
            else:
                for n in ("nonce_match", "request_binding", "response_binding", "attempt_match", "model_hash_reference", "route_allowed"):
                    put(n, NA, "영수증 서명 미검증")

        if "route_allowed" not in checks:
            if inline_relay is not None:
                self._route_check(put, contract, inline_relay.payload.get("upstream_model"), inline_relay)
            else:
                put("route_allowed", NA, "경로를 보고한 진술 없음")

        # 4. 내용·행동 정책 (무결성과 별개의 보안 속성)
        if response_body is not None and response_body.get("tool_call") is not None:
            if self.allow_tool_directives:
                put("tool_policy", PASS, "도구 지시 허용 정책")
            else:
                put("tool_policy", FAIL, f"응답이 도구 실행을 지시함 ({response_body['tool_call']}) — 계약은 도구 실행을 허용하지 않음")
        else:
            put("tool_policy", PASS, "도구 지시 없음")
        return checks

    @staticmethod
    def _route_check(put, contract: dict[str, Any], actual_model: str | None, inline_relay: SignedStatement | None) -> None:
        if actual_model is None:
            put("route_allowed", NA, "실제 모델 정보 없음")
            return
        if actual_model == contract["requested_model"]:
            put("route_allowed", PASS, "요청한 모델")
            return
        if actual_model not in contract["allowed_models"] or contract["fallback_policy"] == "none":
            put("route_allowed", FAIL, f"허용되지 않은 모델 {actual_model}")
            return
        declared = inline_relay is not None and inline_relay.payload.get("policy_decision") == "fallback"
        put("route_allowed", PASS if declared else FAIL,
            "사전 승인된 폴백, 중개자 선언 확인" if declared else "허용 모델이지만 폴백 선언 없음 (숨은 라우팅)")

    # -- 최종 결정 ----------------------------------------------------------------
    def decide(
        self,
        checks: dict[str, dict[str, str]],
        received_at: int,
        now: int,
        verdict_status: str | None = None,
        deadline_hit: bool = False,
    ) -> GateDecision:
        fails = [k for k, v in checks.items() if v["result"] == FAIL]
        nas = [k for k, v in checks.items() if v["result"] == NA]
        reasons: list[str] = []

        if self.mode == "observe":
            action = "accept_unverified"
            reasons.append("관찰 모드: 검증 결과와 무관하게 수용")
            if fails:
                reasons.append("로컬 검증 실패 항목: " + ", ".join(fails))
            consumed_at = received_at  # 받는 즉시 업무에 사용됨
            return GateDecision(self.mode, action, reasons, checks, verdict_status, received_at, now, consumed_at, 0)

        # protect / strict 공통: 로컬 실패는 격리
        if fails:
            reasons.append("로컬 검증 실패: " + ", ".join(fails))
            return GateDecision(self.mode, "quarantine", reasons, checks, verdict_status, received_at, now, None, now - received_at)
        if nas and any(k in nas for k in _REQUIRED_LOCAL_CHECKS):
            reasons.append("로컬 증거 부족: " + ", ".join(k for k in nas if k in _REQUIRED_LOCAL_CHECKS))
            return GateDecision(self.mode, "quarantine", reasons, checks, verdict_status, received_at, now, None, now - received_at)

        if self.mode == "protect":
            reasons.append("로컬 검증 통과 (모델 영수증·nonce·응답 결합·경로)")
            if verdict_status is not None:
                reasons.append(f"T 판정(참고): {verdict_status}")
            return GateDecision(self.mode, "accept", reasons, checks, verdict_status, received_at, now, now, now - received_at)

        # strict
        if verdict_status == "passed":
            reasons.append("로컬 검증 통과 + T 판정 passed")
            return GateDecision(self.mode, "accept", reasons, checks, verdict_status, received_at, now, now, now - received_at)
        if verdict_status == "failed":
            reasons.append("T 판정 failed")
            return GateDecision(self.mode, "reject", reasons, checks, verdict_status, received_at, now, None, now - received_at)
        if deadline_hit:
            reasons.append("기한 내 T 판정을 얻지 못함 (T 장애·지연) → 명시적 거부. 승인된 대체 경로는 미구현")
            return GateDecision(self.mode, "reject_timeout", reasons, checks, verdict_status, received_at, now, None, now - received_at)
        reasons.append(f"T 판정 {verdict_status!r} 은 수용 근거가 아님")
        return GateDecision(self.mode, "reject", reasons, checks, verdict_status, received_at, now, None, now - received_at)
