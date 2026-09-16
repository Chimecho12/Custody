"""User request contracts, observations and enforcement."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from itx.crypto import KeyPair, canonical_json, commit_hex, content_hash_hex
from itx.enforce import GateDecision, UserGate
from itx.reconcile import PrivateEvidence
from itx.reconcile.transforms import IDENTITY, PUBLIC_FORMATTER_V1, public_formatter_v1
from itx.statements import CT_CONTRACT, CT_MANIFEST, CT_OBSERVATION, SignedStatement, issue
from itx.statements.schemas import contract_payload, manifest_payload, observation_payload
from itx.ts import ServiceUnavailable

from ..context import SIGN_MS, STRICT_DEADLINE_MS, STRICT_POLL_MS, SimContext
from .evidence import EvidenceQueue
from .messages import WireRequest, _commit
from .relay import Relay
from .third_party import ThirdParty


@dataclass
class AttemptResult:
    sub: str
    attempt_id: str
    sent_at: int
    received_at: int | None
    contract: SignedStatement
    observation: SignedStatement | None
    private: PrivateEvidence
    response_body: dict[str, Any] | None
    error: str | None
    inline_receipt: SignedStatement | None
    inline_relay: SignedStatement | None
    gate: dict[str, Any]
    live_verdict: dict[str, Any] | None
    expected_parties: list[str]


class User:
    def __init__(
        self,
        ctx: SimContext,
        key: KeyPair,
        relay: Relay,
        third_party: ThirdParty,
        gate_mode: str,
        reference_model_hashes: dict[str, str],
        trusted_model_keys: dict[str, bytes],
        session_id: str = "session-1",
        queue_capacity: int = 100,
        strict_deadline_ms: int = STRICT_DEADLINE_MS,
        allow_tool_directives: bool = False,
    ) -> None:
        self.ctx = ctx
        self.key = key
        self.iss = "urn:itx:party:user"
        self.relay = relay
        self.T = third_party
        self.gate = UserGate(gate_mode, trusted_model_keys, reference_model_hashes, allow_tool_directives)
        self.session_id = session_id
        self.queue = EvidenceQueue(ctx, "U", queue_capacity)
        self.strict_deadline_ms = strict_deadline_ms
        self.attempts: list[AttemptResult] = []
        self._seq = 0

    def request(
        self,
        text: str,
        requested_model: str = "model-A",
        allowed_models: tuple[str, ...] = ("model-A",),
        fallback_policy: str = "none",
        allowed_request_transforms: tuple[str, ...] = (IDENTITY,),
        ttl_ms: int = 5000,
        expected_parties: tuple[str, ...] = ("U", "R", "M"),
    ) -> AttemptResult:
        self._seq += 1
        sub = f"urn:itx:req:{self.ctx.short_id(16)}"
        attempt_id = f"att-{self._seq:03d}"
        nonce, salt = self.ctx.hex32(), self.ctx.hex32()
        body = {"input": text, "model": requested_model}
        request_hash = content_hash_hex(canonical_json(body))
        req_commit = commit_hex(salt, request_hash)
        now = self.ctx.now()

        # 1. 전송 전: 요청 계약 서명 (전송 이전의 신용)
        contract = issue(self.key, iss=self.iss, sub=sub, content_type=CT_CONTRACT, issued_at=now, payload=contract_payload(
            attempt_id=attempt_id, session_id=self.session_id, session_seq=self._seq, nonce=nonce, req_commit=req_commit,
            requested_model=requested_model, allowed_models=list(allowed_models), fallback_policy=fallback_policy,
            allowed_request_transforms=list(allowed_request_transforms), allowed_response_transforms=[IDENTITY],
            relay_id=self.relay.relay_id, expires_at=now + ttl_ms, client_time=now, enforcement_mode=self.gate.mode,
        ))
        expected_commits = {}
        if PUBLIC_FORMATTER_V1 in allowed_request_transforms:
            expected_commits[PUBLIC_FORMATTER_V1] = _commit(salt, public_formatter_v1(body))
        private = PrivateEvidence(salt=salt, request_hash=request_hash, expected_request_commits=expected_commits)
        self.ctx.advance(SIGN_MS)
        self.ctx.record("U", "contract_signed", sub, attempt_id, requested_model=requested_model,
                        allowed_models=list(allowed_models), fallback_policy=fallback_policy,
                        transforms=list(allowed_request_transforms), expires_at=now + ttl_ms)
        self.queue.enqueue("statement", sub, contract)
        self.queue.enqueue("private", sub, private)
        self.queue.flush(self.T)

        # 2. 전송
        sent_at = self.ctx.now()
        self.ctx.record("U", "request_sent", sub, attempt_id, to=self.relay.relay_id)
        wire_resp = self.relay.handle(WireRequest(sub, attempt_id, nonce, salt, body, requested_model))
        received_at = self.ctx.now()

        # 3. 수신
        observation = None
        if wire_resp.body is None:
            self.ctx.record("U", "error_received", sub, attempt_id, error=wire_resp.error)
            checks = {"response_received": {"result": "fail", "reason": f"응답 없음: {wire_resp.error}"}}
            # 응답이 없으면 수용·격리의 대상도 없다. 오차단 집계에서 구별하기 위해 별도 행동으로 남긴다.
            decision = GateDecision(self.gate.mode, "no_response", [f"응답 없음: {wire_resp.error}"], checks,
                                    None, received_at, self.ctx.now(), None, 0)
            live_verdict = None
        else:
            received_hash = content_hash_hex(canonical_json(wire_resp.body))
            private.response_hash = received_hash
            received_commit = commit_hex(salt, received_hash)
            self.ctx.record("U", "response_received", sub, attempt_id,
                            inline_receipt=wire_resp.inline_receipt is not None,
                            inline_relay=wire_resp.inline_relay is not None,
                            latency_ms=received_at - sent_at)
            observation = issue(self.key, iss=self.iss, sub=sub, content_type=CT_OBSERVATION, issued_at=received_at,
                                payload=observation_payload(
                                    attempt_id=attempt_id, resp_commit=received_commit, received_at=received_at,
                                    inline_receipt_hash=wire_resp.inline_receipt.statement_hash if wire_resp.inline_receipt else None,
                                    inline_relay_hash=wire_resp.inline_relay.statement_hash if wire_resp.inline_relay else None,
                                    presented_receipt=wire_resp.inline_receipt.to_dict() if wire_resp.inline_receipt else None))
            self.ctx.advance(SIGN_MS)
            self.queue.enqueue("statement", sub, observation)
            self.queue.enqueue("private", sub, private)
            self.queue.flush(self.T)

            # 4. 게이트: 로컬 검증
            checks = self.gate.local_checks(contract.payload, received_commit, wire_resp.body,
                                            wire_resp.inline_receipt, wire_resp.inline_relay, self.ctx.now(),
                                            expected_request_commits=expected_commits)
            self.ctx.record("U", "gate_local_checks", sub, attempt_id,
                            failed=[k for k, v in checks.items() if v["result"] == "fail"],
                            not_evaluable=[k for k, v in checks.items() if v["result"] == "not_evaluable"])
            live_verdict, decision = self._decide(checks, received_at, sub, list(expected_parties))

        self.ctx.record("U", "gate_decision", sub, attempt_id, action=decision.action, mode=self.gate.mode,
                        consumed_at=decision.consumed_at, waited_ms=decision.waited_ms)
        if decision.consumed_at is not None:
            self.ctx.record("U", "response_consumed", sub, attempt_id, at=decision.consumed_at,
                            before_decision=decision.consumed_before_decision)
        result = AttemptResult(sub, attempt_id, sent_at, received_at, contract, observation, private,
                               wire_resp.body, wire_resp.error, wire_resp.inline_receipt, wire_resp.inline_relay,
                               decision.to_dict(), live_verdict, list(expected_parties))
        self.attempts.append(result)
        return result

    def _decide(self, checks, received_at: int, sub: str, expected_parties: list[str]):
        if self.gate.mode != "strict":
            return None, self.gate.decide(checks, received_at, self.ctx.now(), None, False)
        if any(v["result"] == "fail" for v in checks.values()):
            # 로컬 검증이 이미 실패했으면 T 를 기다릴 이유가 없다.
            return None, self.gate.decide(checks, received_at, self.ctx.now(), None, False)
        deadline = received_at + self.strict_deadline_ms
        verdict = None
        while True:
            try:
                verdict, signed = self.T.request_verdict(sub, expected_parties, self.ctx.now())
                if signed is not None:
                    self.ctx.record("U", "verdict_received", sub, status=verdict["verification_status"],
                                    waited_ms=self.ctx.now() - received_at)
                    return verdict, self.gate.decide(checks, received_at, self.ctx.now(), verdict["verification_status"], False)
            except ServiceUnavailable:
                self.ctx.record("U", "verdict_unavailable", sub, reason="third party down")
            if self.ctx.now() + STRICT_POLL_MS > deadline:
                self.ctx.record("U", "verdict_deadline", sub, waited_ms=self.ctx.now() - received_at)
                return verdict, self.gate.decide(checks, received_at, self.ctx.now(),
                                                 verdict["verification_status"] if verdict else None, True)
            self.ctx.advance(STRICT_POLL_MS)

    def close_session(self) -> SignedStatement:
        now = self.ctx.now()
        attempts = [{"sub": a.sub, "attempt_id": a.attempt_id} for a in self.attempts]
        manifest = issue(self.key, iss=self.iss, sub=f"urn:itx:req:session:{self.session_id}", content_type=CT_MANIFEST,
                         issued_at=now, payload=manifest_payload(session_id=self.session_id, attempts=attempts,
                                                                 closed_at=now, prev_manifest_hash=None))
        self.ctx.record("U", "manifest_issued", attempts=len(attempts))
        self.queue.enqueue("statement", manifest.sub, manifest)
        self.queue.flush(self.T)
        return manifest
