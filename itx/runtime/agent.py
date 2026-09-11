from __future__ import annotations

import secrets
import threading
import time
from pathlib import Path

from itx import CHECKER_VERSION
from itx.crypto import canonical_json, content_hash_hex
from itx.statements import (SignedStatement, CT_CONTRACT, CT_RECEIPT, CT_RELAY, CT_OBSERVATION, CT_VERDICT, CT_POLICY)
from itx.statements.schemas import contract_payload, observation_payload
from itx.enforce import UserGate
from itx.ts import TransparencyLog, RegistrationReceipt, verify_receipt
from itx.audit import replay_audit
from .common import (Store, ISS, MAX_PROMPT, MAX_RESPONSE, authenticate, load_config, key_for,
                     now_ms, signed, digest, policy_for)
from .transport import Peer


class Agent:
    def __init__(self, path, emit=None):
        self.config = load_config(path)
        if self.config["role"] != "U":
            raise ValueError("사용자 U의 연결 설정을 선택하세요.")
        self.key = key_for(self.config)
        self.peer = Peer(self.config, self.key)
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
                    self.store.ack(ident)
                except Exception:
                    break
        finally:
            self.flush_lock.release()

    def policy_hash(self):
        i = self.config["identities"]["T"]
        return SignedStatement(ISS["T"], "urn:itx:policy:" + self.config["log_id"], CT_POLICY,
                               i["kid"], self.config["created_at"], policy_for(self.config)).statement_hash

    def status(self):
        return {"source": "network_lab" if self.config["lab"] else "connected_evaluation",
                "transport": "TLS", "model_kind": self.config["model_kind"],
                "governance": self.config["governance"], "model_id": self.config["model_id"],
                "policy_expires_at": self.config["policy_expires_at"], "pending_evidence": len(self.store.pending()),
                "endpoints": self.config["endpoints"], "identities": self.config["identities"],
                "policy_hash": self.policy_hash(), "config_path": self.config["config_path"]}

    def request(self, prompt, mode, scenario="normal", cancel=None, token=""):
        if not self.request_lock.acquire(False):
            raise RuntimeError("요청이 진행 중입니다. 완료 또는 취소 후 다시 실행하세요.")
        try:
            return self._request(prompt, mode, scenario, cancel or threading.Event(), token)
        finally:
            self.request_lock.release()

    def _request(self, prompt, mode, scenario, cancel, token):
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT:
            raise ValueError("1~16,000자의 요청을 입력하세요.")
        if mode not in ("observe", "protect", "strict"):
            raise ValueError("unknown enforcement mode")
        if scenario != "normal" and not self.config["lab"]:
            raise ValueError("연결 모드에서는 공격을 주입할 수 없습니다.")
        if now_ms() >= self.config["policy_expires_at"]:
            raise ValueError("정책과 신뢰 설정이 만료되었습니다. 새 설정을 등록하세요.")
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
                    checks[role + "_authority"] = {"result": "pass", "reason": "고정된 발행자·역할·유형·서명·요청 결합 확인"}
                except (ValueError, KeyError, TypeError):
                    checks[role + "_authority"] = {"result": "fail", "reason": "필수 증거가 없거나 발행자·서명·요청 결합이 올바르지 않음"}
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
        export = self.peer.call("T", "audit", {}, timeout=3)
        t = self.config["identities"]["T"]
        if (export["ts_public_key"] != t["public_key"] or export["ts_kid"] != t["kid"]
                or export["ts_iss"] != t["iss"] or export["log_id"] != self.config["log_id"]
                or export["policy_hash"] != self.policy_hash()):
            raise ValueError("감사 자료가 사전에 고정한 T 신원·정책과 다릅니다.")
        head = export["head"]
        if not TransparencyLog.verify_tree_head(head, bytes.fromhex(t["public_key"])):
            raise ValueError("invalid checkpoint signature")
        old = self.store.get("checkpoint")
        anchors = [] if old is None else [{"tree_size": old["tree_size"], "root_hash": old["root_hash"], "anchored_at": old["time"]}]
        private = {r["sub"]: r["private"] for _, r in self.store.items("request:")}
        report = replay_audit(export, anchors, private, {}, self.config["model_hashes"])
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
