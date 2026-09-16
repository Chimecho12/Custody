from __future__ import annotations

import secrets
import threading
import time
from pathlib import Path

from itx import CHECKER_VERSION
from itx.crypto import canonical_json, content_hash_hex
from itx.enforce import UserGate
from itx.enforce.user_gate import CHECK_BASIS
from itx.statements import CT_CONTRACT, CT_OBSERVATION, CT_POLICY, CT_RECEIPT, CT_RELAY, CT_VERDICT, SignedStatement
from itx.statements.schemas import contract_payload, observation_payload
from itx.ts import RegistrationReceipt, verify_receipt

from .common import (
    ISS,
    MAX_PROMPT,
    MAX_RESPONSE,
    ProcessLock,
    Store,
    authenticate,
    digest,
    key_for,
    load_config,
    now_ms,
    policy_for,
    signed,
)
from .transport import Peer


class Agent:
    def __init__(self, path, emit=None):
        self.config = load_config(path)
        if self.config["role"] != "U":
            raise ValueError("사용자 U의 연결 설정을 선택하세요.")
        self.key = key_for(self.config)
        self.peer = Peer(self.config, self.key)
        self.process_lock = ProcessLock(Path(self.config["directory"]) / "agent.lock")
        self.store = Store(self.config["directory"])
        # A crash cannot establish whether a remote execution completed. Never retry it.
        for key, record in self.store.items("request:"):
            if record.get("state") == "pending":
                record.update(state="interrupted", response=None,
                              error="Agent 종료로 중단되었습니다. 원격 실행 결과는 불명이며 자동 재실행하지 않습니다.")
                self.store.put(key, record)
        self.emit = emit or (lambda event: None)
        self.request_lock = threading.Lock()
        self.flush_lock = threading.Lock()
        self.stopped = threading.Event()
        self.worker = threading.Thread(target=self._background, daemon=True)
        self.worker.start()

    def _background(self):
        while not self.stopped.wait(0.25):
            self.flush()

    def flush(self):
        if not self.flush_lock.acquire(False):
            return
        try:
            for ident, item in self.store.pending():
                if self.stopped.is_set():
                    break
                try:
                    result = self.peer.call("T", "submit", item, timeout=0.5)
                    if "statement" in item:
                        rc = RegistrationReceipt.from_dict(result["receipt"])
                        stmt = SignedStatement.from_dict(item["statement"])
                        ok, why = verify_receipt(rc, stmt, bytes.fromhex(self.config["identities"]["T"]["public_key"]))
                        if not ok or rc.log_id != self.config["log_id"]:
                            raise ValueError("invalid registration receipt: " + why)
                        # 영수증은 검증하고 버리는 것이 아니라 보관한다. 다음 감사에서 T 가 이 항목을
                        # 지금도 갖고 있는지 물을 수 있는 유일한 근거이기 때문이다 (RFC 9162 §11.3).
                        self.remember_receipt(stmt, rc)
                    self.store.ack(ident)
                except Exception:
                    break
        finally:
            self.flush_lock.release()

    def policy_hash(self):
        i = self.config["identities"]["T"]
        return SignedStatement(ISS["T"], "urn:itx:policy:" + self.config["log_id"], CT_POLICY,
                               i["kid"], self.config["created_at"], policy_for(self.config)).statement_hash

    def trust(self):
        from .auditing import trust_from_config
        return trust_from_config(self.config)

    def remember_receipt(self, stmt, rc):
        self.store.put("receipt:" + stmt.statement_hash, {
            "receipt": rc.to_dict(), "statement_hash": stmt.statement_hash,
            "sub": stmt.sub, "content_type": stmt.content_type, "iss": stmt.iss})

    def held_receipts(self):
        return [record for _, record in self.store.items("receipt:")]

    def remember_private(self, private):
        self.store.put("private-version:" + content_hash_hex(canonical_json(private)), private)

    def private_evidence(self):
        return ({r["sub"]: r["private"] for _, r in self.store.items("request:") if r.get("private")},
                {k.split(":", 1)[1]: v for k, v in self.store.items("private-version:")})

    def audit_export(self):
        from .auditing import fetch_export
        return fetch_export(self.peer, self.trust())

    def status(self):
        return {"source": "network_lab" if self.config["lab"] else "connected_evaluation",
                "transport": "TLS", "model_kind": self.config["model_kind"],
                "governance": self.config["governance"], "model_id": self.config["model_id"],
                "policy_expires_at": self.config["policy_expires_at"], "pending_evidence": len(self.store.pending()),
                "endpoints": self.config["endpoints"], "identities": self.config["identities"],
                "policy_hash": self.policy_hash(), "config_path": self.config["config_path"],
                "epoch": self.config.get("epoch"), "deployment_hash": self.config.get("deployment_hash"),
                "deployment_history": self.config.get("deployment_history", []),
                "witness_configured": "W" in self.config["identities"],
                "held_receipts": self.store.count("receipt:")}

    def preflight(self):
        from itx.crypto import verify
        results = {}
        for role in self.config["endpoints"]:
            challenge = secrets.token_hex(16)
            start = time.monotonic_ns()
            try:
                response = self.peer.call(role, "health", {"challenge": challenge}, timeout=2)
                body = response["body"]
                if (body["challenge"] != challenge or body["role"] != role or body["log_id"] != self.config["log_id"]
                        or not verify(bytes.fromhex(self.config["identities"][role]["public_key"]),
                                      canonical_json(body), bytes.fromhex(response["signature"]))):
                    raise ValueError("authenticated service identity mismatch")
                results[role] = {**body, "ok": body.get("accepting_requests") is True,
                                 "elapsed_ms": (time.monotonic_ns() - start) // 1000000}
            except Exception as exc:
                results[role] = {"ok": False, "error": type(exc).__name__ + ": " + str(exc)[:500]}
        return {"services": results, "ok": all(v["ok"] for v in results.values()), "model_execution_verified": False}

    def witness(self):
        from .auditing import fingerprint
        from .witness import verify_witness_receipt
        if "W" not in self.config["identities"]:
            raise ValueError("별도 목격자 W가 등록된 배포를 먼저 연결하세요.")
        head = self.peer.call("T", "audit_head", {}, timeout=3)["head"]
        receipt = self.peer.call("W", "witness", {"head": head}, timeout=5)
        verify_witness_receipt(receipt, self.trust())
        b = receipt["body"]
        if any(b["head"][k] != head[k] for k in ("log_id", "tree_size", "root_hash")):
            raise ValueError("witness receipt refers to a different checkpoint")
        rows = self.store.items("witness:")
        if rows:
            previous = rows[0][1]
            old_seq = previous["body"]["sequence"]
            if b["sequence"] < old_seq or (b["sequence"] == old_seq and fingerprint(receipt) != fingerprint(previous)):
                raise ValueError("witness receipt rollback or equivocation")
            if b["sequence"] == old_seq + 1 and b["previous_receipt_hash"] != fingerprint(previous):
                raise ValueError("witness receipt chain conflict")
        self.store.put(f"witness:{b['sequence']:012d}", receipt)
        return {"receipt": receipt, "anchor_digest": fingerprint(receipt), "on_chain": False}

    def request(self, prompt, mode, scenario="normal", cancel=None, token=""):
        if not self.request_lock.acquire(False):
            raise RuntimeError("요청이 진행 중입니다. 완료 또는 취소 후 다시 실행하세요.")
        try:
            return self._request(prompt, mode, scenario, cancel or threading.Event(), token)
        finally:
            self.request_lock.release()

    def _request(self, prompt, mode, scenario, cancel, token):
        from .enrollment import assert_active
        assert_active(self.config)
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT:
            raise ValueError("1~16,000자의 요청을 입력하세요.")
        if mode not in ("observe", "protect", "strict"):
            raise ValueError("unknown enforcement mode")
        if scenario != "normal" and not self.config["lab"]:
            raise ValueError("연결 모드에서는 공격을 주입할 수 없습니다.")
        if now_ms() >= self.config["policy_expires_at"]:
            raise ValueError("정책과 신뢰 설정이 만료되었습니다. 새 설정을 등록하세요.")
        if self.store.count("request:") >= self.config.get("max_requests", 10000):
            raise ValueError("요청 보관 한도에 도달했습니다. 감사 자료 보관 후 새 배포 세대로 전환하세요.")
        if len(self.store.pending()) > self.config.get("queue_capacity", 256) - 5:
            raise RuntimeError("증거를 보관할 공간이 부족합니다. T 연결을 복구하세요.")
        start_ns, start = time.monotonic_ns(), now_ms()
        sub, attempt = "urn:itx:req:" + secrets.token_hex(16), secrets.token_hex(16)
        salt, nonce = secrets.token_hex(32), secrets.token_hex(32)
        body = {"prompt": prompt}
        contract = signed(self.config, self.key, CT_CONTRACT, sub, contract_payload(
            attempt_id=attempt, session_id=sub, session_seq=1, nonce=nonce, req_commit=digest(body, salt),
            requested_model=self.config["model_id"], allowed_models=[self.config["model_id"]], fallback_policy="none",
            allowed_request_transforms=["identity"], allowed_response_transforms=["identity"], relay_id=ISS["R"],
            expires_at=start + 60000, client_time=start, enforcement_mode=mode))
        private = {"salt": salt, "request_hash": content_hash_hex(canonical_json(body)),
                   "response_hash": None, "expected_request_commits": {}}
        record = {"sub": sub, "attempt_id": attempt, "mode": mode, "started_at": start,
                  "source": self.status()["source"], "transport": "TLS", "model_kind": self.config["model_kind"],
                  "governance": self.config["governance"], "lab_scenario": scenario if self.config["lab"] else None,
                  "contract": contract.to_dict(), "private": private, "timeline": [], "state": "pending",
                  "response": None, "checks": {}, "gate": None, "t_verdict": None}
        def event(actor, kind):
            item = {"actor": actor, "kind": kind, "t_ms": (time.monotonic_ns() - start_ns) // 1_000_000}
            record["timeline"].append(item)
            self.emit({"token": token, "sub": sub, **item})
        try:
            self.store.put("request:" + sub, record)
            event("U", "계약 서명 · 전송 전 기록")
            self.store.enqueue({"statement": contract.to_dict()})
            self.remember_private(private)
            self.store.enqueue({"sub": sub, "private": private})
            if cancel.is_set():
                raise InterruptedError("취소됨: 전송하지 않았습니다.")
            event("U", "R로 요청 전송")
            wire = self.peer.call("R", "infer", {"contract": contract.to_dict(), "body": body, "salt": salt,
                                                 "scenario": scenario}, timeout=23)
            received_at = now_ms()
            event("U", "응답 수신 · 사용 보류")
            response = wire["body"]
            if (not isinstance(response, dict) or set(response) != {"text"}
                    or not isinstance(response["text"], str) or len(response["text"]) > MAX_RESPONSE):
                raise ValueError("unsupported or oversized response")
            record["quarantined_body"] = response
            received_commit = digest(response, salt)
            checks = {}
            m = r = None
            for role, field, ct in (("M", "receipt", CT_RECEIPT), ("R", "relay", CT_RELAY)):
                try:
                    stmt = authenticate(self.config, wire[field], role, ct, sub)
                    if stmt.payload["attempt_id"] != attempt:
                        raise ValueError("attempt mismatch")
                    if role == "M":
                        m = stmt
                    else:
                        r = stmt
                    checks[role + "_authority"] = {"result": "pass", "reason": "고정된 발행자·역할·유형·서명·요청 결합 확인",
                                                   "basis": CHECK_BASIS[role + "_authority"]}
                except (ValueError, KeyError, TypeError):
                    checks[role + "_authority"] = {"result": "fail", "reason": "필수 증거가 없거나 발행자·서명·요청 결합이 올바르지 않음",
                                                   "basis": CHECK_BASIS[role + "_authority"]}
            gate = UserGate(mode, {self.config["identities"]["M"]["kid"]: bytes.fromhex(self.config["identities"]["M"]["public_key"])},
                            self.config["model_hashes"])
            checks.update(gate.local_checks(contract.payload, received_commit, response, m, r, received_at))
            # Network profile requires every configured check, including identity/route/reference.
            for check in checks.values():
                if check["result"] == "not_evaluable":
                    check["result"] = "fail"
            record["checks"] = checks
            observation = signed(self.config, self.key, CT_OBSERVATION, sub, observation_payload(
                attempt_id=attempt, resp_commit=received_commit, received_at=received_at,
                inline_receipt_hash=m.statement_hash if m else None, inline_relay_hash=r.statement_hash if r else None,
                presented_receipt=m.to_dict() if m else None))
            private["response_hash"] = content_hash_hex(canonical_json(response))
            self.remember_private(private)
            record["observation"] = observation.to_dict()
            self.store.put("request:" + sub, record)
            self.store.enqueue({"statement": observation.to_dict()})
            self.store.enqueue({"sub": sub, "private": private})
            event("U", "서명과 요청·응답 결합 검사 완료")
            verdict_status = None
            deadline = time.monotonic() + self.config.get("strict_timeout_ms", 2500) / 1000
            if mode == "strict" and all(v["result"] == "pass" for v in checks.values()):
                event("T", "유효한 T 판정 대기")
                while not cancel.is_set() and time.monotonic() < deadline:
                    try:
                        self.flush()
                        v = self.verdict(record, timeout=min(0.5, max(0.05, deadline - time.monotonic())))
                        record["t_verdict"] = v
                        verdict_status = v["payload"]["verification_status"]
                        if verdict_status in ("passed", "failed"):
                            break
                    except Exception as exc:
                        record["t_error"] = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
                    cancel.wait(0.1)
                if time.monotonic() >= deadline and verdict_status != "failed":
                    verdict_status = None
            if cancel.is_set():
                raise InterruptedError("취소됨: 응답을 공개하지 않았습니다. 원격 실행 여부와 별개입니다.")
            assert_active(self.config)
            if now_ms() > contract.payload["expires_at"] or now_ms() >= self.config["policy_expires_at"]:
                checks["not_expired"] = {"result": "fail", "reason": "수용 결정 전에 계약 또는 정책이 만료됨"}
            decision = gate.decide(checks, received_at, now_ms(), verdict_status, deadline_hit=True).to_dict()
            record.update(gate=decision, state=decision["action"])
            if decision["action"] in ("accept", "accept_unverified"):
                # This assignment is the sole response release to the IPC consumer.
                record["response"] = response["text"]
                event("U", "검증 후 응답 공개" if mode != "observe" else "관찰 모드 · 미검증 응답 공개")
            else:
                event("U", "응답 격리 · 공개하지 않음")
        except Exception as e:
            record.update(state="cancelled" if isinstance(e, InterruptedError) else "error", error=str(e), response=None)
            event("U", "요청 중단 · 응답 미공개")
        record["elapsed_ms"] = (time.monotonic_ns() - start_ns) // 1_000_000
        self.store.put("request:" + sub, record)
        return self.public(record)

    def verdict(self, record, timeout=1):
        result = self.peer.call("T", "verdict", {"sub": record["sub"]}, timeout=timeout)
        stmt = authenticate(self.config, result["statement"], "T", CT_VERDICT, record["sub"])
        v = stmt.payload
        if (v["attempt_id"] != record["attempt_id"] or v.get("contract_hash") != SignedStatement.from_dict(record["contract"]).statement_hash
                or v["policy_hash"] != self.policy_hash() or v["checker_version"] != CHECKER_VERSION
                or type(v.get("valid_until")) is not int or not now_ms() <= v["valid_until"] <= now_ms() + 60000
                or stmt.issued_at > now_ms() + 5000):
            raise ValueError("T 판정의 정책·요청·시도·유효기간이 일치하지 않습니다.")
        rc = RegistrationReceipt.from_dict(result["receipt"])
        ok, _ = verify_receipt(rc, stmt, bytes.fromhex(self.config["identities"]["T"]["public_key"]))
        if not ok or rc.log_id != self.config["log_id"]:
            raise ValueError("T 판정 등록 증명이 올바르지 않습니다.")
        self.remember_receipt(stmt, rc)  # T 의 판정도 T 가 나중에 지울 수 없게 영수증을 보관한다
        return stmt.to_dict()

    def refresh(self, sub):
        record = self.store.get("request:" + sub)
        if record is None:
            raise ValueError("unknown request")
        if record["state"] == "pending":
            raise ValueError("request is still in progress")
        self.flush()
        record["t_verdict"] = self.verdict(record)
        self.store.put("request:" + sub, record)
        return self.public(record)

    def audit(self):
        from .auditing import verify_export
        export = self.audit_export()
        head = export["head"]
        old = self.store.get("checkpoint")
        anchors = [] if old is None else [{"tree_size": old["tree_size"], "root_hash": old["root_hash"], "anchored_at": old["time"]}]
        private, versions = self.private_evidence()
        report = verify_export(export, self.trust(), anchors=anchors, private=private, private_by_hash=versions,
                               held_receipts=self.held_receipts())
        report.update(pinned_identity=True, previous_checkpoint=old, current_checkpoint=head,
                      witness_scope="사용자 PC 보관 · 별도 운영 목격자 아님")
        if report["ok"]:
            self.store.put("checkpoint", head)
        self.store.put("last_audit", report)
        return report

    @staticmethod
    def public(record):
        return {k: v for k, v in record.items() if k not in ("quarantined_body", "private", "contract", "observation")}

    def history(self):
        records = [self.public(r) for _, r in self.store.items("request:")]
        return sorted(records, key=lambda r: r["started_at"], reverse=True)[:100]

    def close(self):
        self.stopped.set()
        self.worker.join(timeout=2)
        self.store.close()
        self.process_lock.close()
