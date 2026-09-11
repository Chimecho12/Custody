"""대조 엔진: 등록된 진술 + 사용자 비공개 증거 → 판정 페이로드.

결정적이다. 제3자(T)와 독립 감사자가 같은 입력으로 같은 판정을 재계산한다 (audit/replay.py).
"""
from __future__ import annotations

from typing import Any, Iterable

from itx import CHECKER_VERSION, DEPLOYMENT_MODE, PROFILE_VERSION
from itx.statements import (
    SignedStatement, CT_CONTRACT, CT_RELAY, CT_RECEIPT, CT_OBSERVATION, CT_MANIFEST,
)
from .evidence import EvidenceSet, PrivateEvidence, StatementRef
from .equations import evaluate_equations, FAIL, PASS, NA
from .discrepancy import classify, Discrepancy, SEV_VIOLATION, SEV_CONTRADICTION, SEV_OBSERVATION
from .completeness import assess_completeness
from .transforms import transform_definition_hash

THREAT_MODEL_TM1 = "TM1: U 집행 모듈과 M 입출력 관측은 정직, R 은 악성일 수 있음. R+M 공모·T 침해는 별도 실험군"

# 판정 'passed' 를 주기 위해 반드시 pass 여야 하는 등식.
#
# E4 는 요청 쪽에서 E10 이 응답 쪽에서 하는 일과 같다 — "M 이 실제로 받은 것이 U 가 보낸
# 것(또는 승인된 변환의 결과)인가". 둘 중 하나라도 평가할 수 없으면 경로 무결성은 확립되지
# 않았으므로 passed 가 아니라 insufficient_evidence 다. E4 를 빼 두면, 계약이 재계산 불가한
# 변환을 하나라도 허용하는 순간 R 이 요청을 마음대로 바꿔도 E4=not_evaluable 로 남고
# 판정은 passed 가 된다.
REQUIRED_FOR_PASS = ("E1", "E4", "E5", "E8", "E9", "E10", "E11", "E12")

_CT_TO_FIELD = {
    CT_CONTRACT: "contract",
    CT_RELAY: "relay",
    CT_RECEIPT: "receipt",
    CT_OBSERVATION: "observation",
    CT_MANIFEST: "manifest",
}


class ReconciliationEngine:
    def __init__(
        self,
        trusted_keys: dict[str, tuple[str, bytes]],
        reference_model_hashes: dict[str, str],
        policy_hash: str,
        trust_keys_version: str,
        issuer_content_types: dict[str, tuple[str, ...] | list[str]],
        late_threshold_ms: int = 1000,
    ) -> None:
        self.trusted_keys = trusted_keys
        self.reference_model_hashes = dict(reference_model_hashes)
        self.policy_hash = policy_hash
        self.trust_keys_version = trust_keys_version
        #: iss -> 그 발행자가 낼 수 있는 진술 유형 (등록 정책과 같은 값).
        #: 등록기가 이미 걸렀다고 가정하지 않는다. 감사자는 T 의 코드를 믿지 않으므로
        #: 대조 단계에서 다시 확인한다.
        self.issuer_content_types = {iss: tuple(cts) for iss, cts in issuer_content_types.items()}
        self.late_threshold_ms = late_threshold_ms

    def authorized(self, iss: str, content_type: str) -> bool:
        return content_type in self.issuer_content_types.get(iss, ())

    # -- 수집 ------------------------------------------------------------------
    def gather(
        self,
        sub: str,
        entries: Iterable[Any],
        private: PrivateEvidence | None,
        now: int,
    ) -> EvidenceSet:
        """로그 항목(index, registered_at, statement)들을 유형별 최신 진술로 정리한다.
        서명이 검증되지 않는 진술은 증거로 쓰지 않고 별도 목록에 남긴다."""
        ev = EvidenceSet(sub=sub, private=private, reference_model_hashes=self.reference_model_hashes, now=now)
        for e in entries:
            stmt: SignedStatement = e.statement
            key = self.trusted_keys.get(stmt.kid)
            valid = key is not None and key[0] == stmt.iss and stmt.verify_with(key[1])
            ref = StatementRef(
                content_type=stmt.content_type, iss=stmt.iss, kid=stmt.kid,
                statement_hash=stmt.statement_hash, log_index=getattr(e, "index", None),
                registered_at=getattr(e, "registered_at", None), signature_valid=valid,
            )
            if not valid:
                ev.invalid_signatures.append(ref)
                continue
            # 서명이 맞아도 역할이 맞아야 한다. 중개자가 자기 키로 서명한 '모델 영수증' 은
            # 유효한 서명이지만 M 의 증거가 아니다.
            if not self.authorized(stmt.iss, stmt.content_type):
                ev.unauthorized_issuers.append(ref)
                continue
            field_name = _CT_TO_FIELD.get(stmt.content_type)
            if field_name is None:
                continue
            ev.refs.append(ref)
            # 같은 유형이 여럿이면 등록 순서상 마지막(정정 진술)을 쓴다.
            setattr(ev, field_name, stmt)

        # 등록된 영수증이 없으면, 사용자에게 제시된 영수증 사본(서명 검증 시)을 대신 쓴다.
        # 재전송·다른 시도의 영수증을 보여 준 경우가 여기서 드러난다.
        presented = ev.o.get("presented_receipt") if ev.o else None
        if ev.receipt is None and presented:
            try:
                pr = SignedStatement.from_dict(presented)
            except (KeyError, TypeError, ValueError):
                pr = None
            if pr is not None and pr.content_type == CT_RECEIPT:
                key = self.trusted_keys.get(pr.kid)
                if (key is not None and key[0] == pr.iss and pr.verify_with(key[1])
                        and self.authorized(pr.iss, pr.content_type)):
                    ev.receipt = pr
                    ev.receipt_source = "presented_to_user"
                    ev.refs.append(StatementRef(pr.content_type, pr.iss, pr.kid, pr.statement_hash, None, None, True))
        if ev.receipt is None:
            ev.receipt_source = "none"
        return ev

    # -- 판정 ------------------------------------------------------------------
    def reconcile(self, ev: EvidenceSet, expected_parties: list[str]) -> dict[str, Any]:
        eqs = evaluate_equations(ev)
        discrepancies: list[Discrepancy] = classify(eqs, ev.present_parties)
        completeness = assess_completeness(ev, expected_parties)

        for ref in ev.invalid_signatures:
            discrepancies.append(Discrepancy(
                "D-SIG-INVALID", SEV_CONTRADICTION, [], f"{ref.iss} (kid {ref.kid})",
                "신뢰 키로 검증되지 않는 서명. 위조·키 교체·손상 중 어느 것인지는 별도 조사",
                {"content_type": ref.content_type, "statement_hash": ref.statement_hash},
            ))
        for ref in ev.unauthorized_issuers:
            discrepancies.append(Discrepancy(
                "D-ISSUER-UNAUTHORIZED", SEV_VIOLATION, [], ref.iss,
                "서명은 유효하나 이 발행자는 이 유형의 진술을 낼 권한이 없음. 다른 당사자의 "
                "역할을 사칭한 진술이므로 증거로 쓰지 않는다",
                {"content_type": ref.content_type, "statement_hash": ref.statement_hash,
                 "allowed": list(self.issuer_content_types.get(ref.iss, ()))},
            ))
        presented = ev.o.get("presented_receipt") if ev.o else None
        if presented and ev.receipt_source == "registered" and ev.receipt is not None:
            try:
                presented_hash = SignedStatement.from_dict(presented).statement_hash
            except (KeyError, TypeError, ValueError):
                presented_hash = None
            if presented_hash is not None and presented_hash != ev.receipt.statement_hash:
                discrepancies.append(Discrepancy(
                    "D-RECEIPT-PRESENTED-DIFFERS", SEV_CONTRADICTION, [], "R",
                    "M 이 등록한 영수증과 R 이 사용자에게 보여 준 영수증이 다름",
                    {"registered": ev.receipt.statement_hash, "presented": presented_hash},
                ))
        if completeness["status"] == "gap":
            discrepancies.append(Discrepancy(
                "D-GAP", SEV_OBSERVATION, [], "관측 상태 (귀속 없음)",
                "합의된 증거 미등록. 누락·회피·장애 어느 것인지 이 자료만으로는 알 수 없음",
                {"missing": completeness["missing"]},
            ))
        late = self._late_registrations(ev)
        if late:
            discrepancies.append(Discrepancy(
                "D-LATE", SEV_OBSERVATION, [], "관측 상태 (귀속 없음)",
                "등록 시각은 발생 시각의 상한이며, 지연에는 시계 차이와 자기 보고 오차가 섞여 있음",
                {"late": late, "threshold_ms": self.late_threshold_ms},
            ))

        status = self._status(eqs, discrepancies, ev)
        assurance = "air-local" if (status == "passed" and ev.receipt is not None) else "none"
        return {
            "profile": f"{PROFILE_VERSION}/verdict",
            "attempt_id": self._attempt_id(ev),
            "verification_status": status,
            "established_assurance": assurance,
            "deployment_mode": DEPLOYMENT_MODE,
            "cooperation_set": ev.cooperation_set,
            "completeness": completeness["status"],
            "completeness_detail": completeness,
            "equations": {k: v.to_dict() for k, v in eqs.items()},
            "discrepancies": [d.to_dict() for d in discrepancies],
            "evidence_refs": [r.to_dict() for r in ev.refs],
            "invalid_signature_refs": [r.to_dict() for r in ev.invalid_signatures],
            "unauthorized_issuer_refs": [r.to_dict() for r in ev.unauthorized_issuers],
            "policy_hash": self.policy_hash,
            "checker_version": CHECKER_VERSION,
            "trust_keys_version": self.trust_keys_version,
            "transform_definitions": {
                t: transform_definition_hash(t)
                for t in (ev.c["allowed_request_transforms"] if ev.c else [])
                if transform_definition_hash(t) is not None
            },
            "threat_model": THREAT_MODEL_TM1,
            "notes": self._notes(eqs, ev),
        }

    # -- 내부 -----------------------------------------------------------------
    @staticmethod
    def _attempt_id(ev: EvidenceSet) -> str:
        for pl in (ev.c, ev.o, ev.m, ev.r):
            if pl is not None and pl.get("attempt_id"):
                return pl["attempt_id"]
        return "unknown"

    def _late_registrations(self, ev: EvidenceSet) -> list[dict[str, Any]]:
        out = []
        client_time = ev.c.get("client_time") if ev.c else None
        if client_time is None:
            return out
        for ref in ev.refs:
            if ref.registered_at is not None and ref.registered_at - client_time > self.late_threshold_ms:
                out.append({"content_type": ref.content_type, "delay_ms": ref.registered_at - client_time})
        return out

    @staticmethod
    def _status(eqs, discrepancies: list[Discrepancy], ev: EvidenceSet) -> str:
        if any(d.severity in (SEV_VIOLATION, SEV_CONTRADICTION) for d in discrepancies):
            return "failed"
        if any(e.result == FAIL for e in eqs.values()):
            return "failed"
        if all(eqs[k].result == PASS for k in REQUIRED_FOR_PASS):
            return "passed"
        return "insufficient_evidence"

    @staticmethod
    def _notes(eqs, ev: EvidenceSet) -> list[str]:
        notes = []
        na = [k for k, e in eqs.items() if e.result == NA]
        if na:
            notes.append("평가 불가 등식: " + ", ".join(f"{k}({eqs[k].reason})" for k in na))
        if ev.receipt is None:
            notes.append("추론 영수증이 없어 종단 응답 무결성(E10)을 확립할 수 없음. 진술 간 모순만 검사함")
        elif ev.receipt_source == "presented_to_user":
            notes.append("이 요청에 등록된 영수증이 없어, 중개자가 사용자에게 제시한 영수증 사본(서명 검증됨)을 근거로 검사함")
        if ev.m is not None:
            notes.append("영수증 security_mode=evaluation, attestation=mock. TEE 출처를 주장하지 않음")
        notes.append("아티팩트 해시 일치(E9)는 실행 일치가 아님. 등록 시각은 발생 시각의 상한임")
        return notes
