"""Model execution and signed receipts."""
from __future__ import annotations

from typing import Any

from itx.crypto import KeyPair, sha256_hex
from itx.reconcile.transforms import IDENTITY
from itx.statements import CT_RECEIPT, SignedStatement, issue
from itx.statements.schemas import receipt_payload
from itx.ts import ServiceUnavailable

from ..context import SIGN_MS, SimContext
from ..model import MockModel
from .evidence import EvidenceQueue
from .messages import WireRequest, _commit
from .third_party import ThirdParty


class ModelOperator:
    def __init__(
        self,
        ctx: SimContext,
        key: KeyPair,
        models: dict[str, MockModel],
        third_party: ThirdParty,
        issue_receipts: bool = True,
        pre_exec_enforce: bool = False,
        queue_capacity: int = 100,
        collude: bool = False,
    ) -> None:
        self.ctx = ctx
        self.key = key
        self.iss = "urn:itx:party:model-operator"
        self.models = models
        self.T = third_party
        self.issue_receipts = issue_receipts
        self.pre_exec_enforce = pre_exec_enforce
        self.collude = collude  # True 면 정직한 영수증을 내지 않고 R 이 요청하는 위조 영수증만 서명 (S15)
        self.queue = EvidenceQueue(ctx, "M", queue_capacity)
        self._cti = 0

    def _pre_exec_check(self, wire: WireRequest) -> tuple[str, str]:
        """실행 직전 검사 (05 검토서 §3.1 'M 의 실행 직전'). (결과, 사유)"""
        if not self.pre_exec_enforce:
            return "skipped", "M 집행 비활성"
        try:
            contract = self.T.lookup_contract(wire.sub, self.ctx.now())
        except ServiceUnavailable:
            return "unavailable", "T 장애로 계약을 조회할 수 없음 → 미검증 상태로 진행"
        if contract is None:
            return "unavailable", "등록된 계약 없음 (아직 미등록이거나 사용자 비협조)"
        c = contract.payload
        if wire.nonce is None or wire.nonce != c["nonce"]:
            return "failed", "nonce 가 없거나 계약과 다름"
        if wire.salt is None:
            return "failed", "솔트 미전달 → 커밋 검증 불가"
        got = _commit(wire.salt, wire.body)
        if IDENTITY in c["allowed_request_transforms"] and got == c["req_commit"]:
            return "passed", "받은 요청이 사용자 계약의 커밋과 일치 (무변환)"
        other = [t for t in c["allowed_request_transforms"] if t != IDENTITY]
        if other:
            return "unverifiable", f"계약이 변환 {other} 을 허용하나 M 은 원문 없이 재계산 불가 → 진행"
        return "failed", "받은 요청이 사용자 계약의 커밋과 다름 (중개자 변조 후보) → 실행 거부"

    def serve(self, upstream_model: str, wire: WireRequest) -> tuple[dict[str, Any] | None, SignedStatement | None, str]:
        model = self.models[upstream_model]
        check, why = self._pre_exec_check(wire)
        self.ctx.record("M", "pre_exec_check", wire.sub, wire.attempt_id, result=check, reason=why)
        self._cti += 1
        cti = f"cti-{self._cti:04d}"
        if check == "failed":
            receipt = self._receipt(wire, cti, model, request_commit=_commit(wire.salt, wire.body),
                                    response_commit=None, exec_ms=0, check=check, decision="refused")
            self.ctx.record("M", "refused", wire.sub, wire.attempt_id, reason=why)
            return None, receipt, "refused"
        self.ctx.advance(model.latency_ms)
        response = model.infer(wire.body)
        self.ctx.record("M", "inferred", wire.sub, wire.attempt_id, model=model.model_id, output=response["output"][:80])
        if self.collude:
            self.ctx.record("M", "honest_receipt_withheld", wire.sub, wire.attempt_id, note="공모: 정직한 영수증을 내지 않음")
            return response, None, "served"
        receipt = self._receipt(wire, cti, model, request_commit=_commit(wire.salt, wire.body),
                                response_commit=_commit(wire.salt, response), exec_ms=model.latency_ms,
                                check=check, decision="served")
        return response, receipt, "served"

    def forge_receipt(self, wire: WireRequest, model_id: str, response: dict[str, Any]) -> SignedStatement | None:
        """R 과 공모한 M: 실제 생성하지 않은 응답에 대해 영수증을 서명한다 (S15 전용)."""
        model = self.models[model_id]
        self._cti += 1
        return self._receipt(wire, f"cti-forged-{self._cti:04d}", model, request_commit=_commit(wire.salt, wire.body),
                             response_commit=_commit(wire.salt, response), exec_ms=model.latency_ms,
                             check="skipped", decision="served", forged=True)

    def _receipt(self, wire: WireRequest, cti: str, model: MockModel, *, request_commit, response_commit,
                 exec_ms: int, check: str, decision: str, forged: bool = False) -> SignedStatement | None:
        if not self.issue_receipts:
            return None
        payload = receipt_payload(
            cti=cti, attempt_id=wire.attempt_id, request_commit=request_commit, response_commit=response_commit,
            model_id=model.model_id, model_version=model.version, model_hash=model.manifest_hash,
            eat_nonce=wire.nonce, execution_time_ms=exec_ms, pre_exec_check=check, decision=decision,
            attestation_doc_hash=sha256_hex(f"mock-attestation:{cti}".encode()),
        )
        self.ctx.advance(SIGN_MS)
        stmt = issue(self.key, iss=self.iss, sub=wire.sub, content_type=CT_RECEIPT, payload=payload, issued_at=self.ctx.now())
        self.ctx.record("M", "receipt_issued", wire.sub, wire.attempt_id, cti=cti, decision=decision, forged=forged)
        self.queue.enqueue("statement", wire.sub, stmt)
        self.queue.flush(self.T)
        return stmt
