"""Connection lifecycle, request cancellation and serialized desktop operations."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from ..agent import Agent
from ..common import json_loads
from ..lab import Lab
from .operations import AGENT_OPERATIONS, ALLOWED_OPERATIONS
from .provisioning import provision
from .standards import standards_operation


class Desktop:
    def __init__(self, directory, emit):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.emit = emit
        self.lab = None
        self.agent = None
        self.lock = threading.RLock()
        self.operation_lock = threading.Lock()
        self.active = {}

    def ensure(self):
        if self.agent is None:
            selection = self.directory / "connection.json"
            preference = json_loads(selection.read_bytes()) if selection.exists() else {}
            if preference.get("path"):
                self.agent = Agent(preference["path"], self.emit)
            else:
                self.lab = Lab(self.directory / "lab")
                self.agent = Agent(self.lab.start(), self.emit)

    def remember(self, path=None):
        target = self.directory / "connection.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps({"path": str(path) if path else None}), encoding="utf-8")
        temporary.replace(target)

    def execute(self, op, args):
        if op in ("status", "cancel", "history"):
            return self._execute(op, args)
        if not self.operation_lock.acquire(False):
            raise ValueError("다른 작업이 진행 중입니다. 완료 후 다시 실행하세요.")
        try:
            return self._execute(op, args)
        finally:
            self.operation_lock.release()

    def _execute(self, op, args):
        with self.lock:
            if op.startswith("enroll_") or op in ("recipient_create", "audit_verify"):
                return provision(self.directory, self.output_path, op, args)
            # Let the user repair a missing/invalid saved connection without silent fallback.
            if op in ("connect", "lab"):
                if self.active:
                    raise ValueError("진행 요청을 완료하거나 취소한 뒤 연결을 변경하세요.")
                if op == "connect":
                    path = Path(args["path"]).resolve(strict=True)
                    if self.agent and Path(self.agent.config["config_path"]) == path:
                        return {**self.agent.status(), "services": self.lab.status() if self.lab else None}
                    replacement = Agent(path, self.emit)
                    if replacement.config["lab"]:
                        replacement.close()
                        raise ValueError("연결 모드에는 lab=false로 준비한 U 설정이 필요합니다.")
                    if self.agent:
                        self.agent.close()
                    if self.lab:
                        self.lab.close()
                    self.lab, self.agent = None, replacement
                    self.remember(path)
                else:
                    if self.agent:
                        self.agent.close()
                    if self.lab:
                        self.lab.close()
                    self.agent, self.lab = None, None
                    self.remember()
                self.ensure()
                return {**self.agent.status(), "services": self.lab.status() if self.lab else None}
            self.ensure()
            agent = self.agent
            if op == "status":
                return {**agent.status(), "services": self.lab.status() if self.lab else None,
                        "operations": sorted(ALLOWED_OPERATIONS)}
            if op == "history":
                return agent.history()
            if op == "cancel":
                token = args["token"]
                if token in self.active:
                    self.active[token].set()
                return {"requested": token in self.active}
            if op in ("connect", "lab", "stop_t", "start_t") and self.active:
                raise ValueError("진행 요청을 완료하거나 취소한 뒤 연결을 변경하세요.")
            if op in ("stop_t", "start_t"):
                if not self.lab:
                    raise ValueError("실험실에서만 서비스를 제어할 수 있습니다.")
                if op == "stop_t":
                    self.lab.stop_role("T")
                else:
                    self.lab.restart_t()
                agent.store.put("control:" + str(time.time_ns()), {"operation": op})
                return self.execute("status", {})
            if op == "request":
                token = args["token"]
                if not isinstance(token, str) or not 1 <= len(token) <= 80 or token in self.active:
                    raise ValueError("invalid request token")
                cancellation = threading.Event()
                self.active[token] = cancellation
            elif op not in AGENT_OPERATIONS:
                raise ValueError(f"이 Agent 는 '{op}' 을 모릅니다. "
                                 "앱보다 오래된 Agent 빌드일 수 있습니다 — 사이드카를 다시 패키징하세요.")
        if op == "request":
            try:
                return agent.request(args["prompt"], args["mode"], args.get("scenario", "normal"), cancellation, token)
            finally:
                with self.lock:
                    self.active.pop(token, None)
        if op == "refresh":
            return agent.refresh(args["sub"])
        if op == "audit":
            return agent.audit()
        if op in ("standards", "key_inventory", "cose_export"):
            return standards_operation(self.output_path, op, args, agent)
        if op == "preflight":
            return agent.preflight()
        if op == "export_checkpoint":
            from ..auditing import fingerprint, verify_head
            from ..packages import write_document
            head = agent.peer.call("T", "audit_head", {})["head"]
            verify_head(head, agent.trust())
            path = self.output_path("checkpoint")
            write_document(path, head)
            return {"path": str(path), "head": head, "fingerprint": fingerprint(head)}
        if op == "witness":
            result = agent.witness()
            from ..packages import write_document
            path = self.output_path("anchor")
            write_document(path, result)
            return {**result, "path": str(path)}
        if op in ("retention_preview", "retention_apply"):
            from .. import retention
            return retention.preview(agent) if op == "retention_preview" else retention.apply(agent, args["token"])
        if op in ("export_evidence", "export_trust"):
            from ..auditing import fingerprint
            from ..packages import build_package, encrypt_package, read_document, write_document
            if op == "export_trust":
                value = agent.trust()
                path = self.output_path("trust")
                write_document(path, value)
                return {"path": str(path), "fingerprint": fingerprint(value)}
            recipient_path = args.get("recipient_path")
            value = build_package(agent, include_private=bool(recipient_path))
            if recipient_path:
                value = encrypt_package(value, read_document(recipient_path), args["recipient_fingerprint"])
            path = self.output_path("audit-encrypted" if recipient_path else "audit-public")
            write_document(path, value)
            return {"path": str(path), "private_included": bool(recipient_path), "encrypted": bool(recipient_path)}
        if op == "simulation":
            from itx.sim.runner import run_scenario
            from itx.sim.scenarios import scenario_by_id
            if args["mode"] not in ("observe", "protect", "strict"):
                raise ValueError("unknown mode")
            result = run_scenario(scenario_by_id(args["scenario"]), args["mode"])
            result.pop("log_export", None)
            return result
        if op == "simulation_matrix":
            # Compact form of run_all(): full runs exceed the IPC frame, the UI fetches one run at a time.
            from itx import CHECKER_VERSION, __version__
            from itx.crypto import BACKEND
            from itx.sim.runner import MODES, aggregate, run_q1_matrix, run_scenario
            from itx.sim.scenarios import SCENARIOS
            results = [run_scenario(sc, mode) for sc in SCENARIOS for mode in MODES]
            rows = []
            for r in results:
                last = r["attempts"][-1]
                fv = last["final_verdict"]
                rows.append({"scenario_id": r["run"]["scenario_id"], "mode": r["run"]["mode"],
                             "verification_status": fv["verification_status"], "completeness": fv["completeness"],
                             "codes": [d["code"] for d in fv["discrepancies"]], "gate_action": last["gate"]["action"],
                             "attack_present": last["metrics"]["attack_present"], "attempts": len(r["attempts"]),
                             "audit_ok": r["audit"]["ok"], "verdict_mismatches": len(r["audit"]["verdict_mismatches"]),
                             "anchors_ok": all(a["ok"] for a in r["audit"]["anchors"])})
            return {"generated_with": {"itx_version": __version__, "checker_version": CHECKER_VERSION, "seed": 42,
                                       "crypto_backend": BACKEND, "claim_status": "mock_result"},
                    "scenarios": [s.to_dict() for s in SCENARIOS], "rows": rows,
                    "q1_matrix": run_q1_matrix(), "summary": aggregate(results)}
        if op == "export":
            # Export only public UI records, never raw prompts, quarantine bodies, keys or salts.
            target = self.directory / "exports"
            target.mkdir(exist_ok=True, parents=True)
            path = target / ("itx-results-" + str(time.time_ns()) + ".json")
            path.write_text(json.dumps({"requests": agent.history(), "audit": agent.store.get("last_audit")},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
            return {"path": str(path)}

    def output_path(self, prefix, suffix=".json"):
        import secrets

        from ..common import now_ms
        directory = self.directory / "exports"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{prefix}-{now_ms()}-{secrets.token_hex(3)}{suffix}"

    def cancel_all(self):
        with self.lock:
            for event in self.active.values():
                event.set()

    def close(self):
        self.cancel_all()
        if self.agent:
            self.agent.close()
        if self.lab:
            self.lab.close()
