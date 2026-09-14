"""Line-framed, structured IPC. stdout is reserved for protocol messages."""
from __future__ import annotations

import concurrent.futures
import json
import threading
import sys
from pathlib import Path

from .agent import Agent
from .lab import Lab
from .common import MAX_WIRE, json_loads, ProcessLock


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
                return self.provision(op, args)
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
                return {**agent.status(), "services": self.lab.status() if self.lab else None}
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
                agent.store.put("control:" + str(__import__('time').time_ns()), {"operation": op})
                return self.execute("status", {})
            if op == "request":
                token = args["token"]
                if not isinstance(token, str) or not 1 <= len(token) <= 80 or token in self.active:
                    raise ValueError("invalid request token")
                cancellation = threading.Event()
                self.active[token] = cancellation
            elif op not in ("refresh", "audit", "simulation", "export", "export_evidence", "export_trust", "preflight",
                            "witness", "export_checkpoint", "retention_preview", "retention_apply"):
                raise ValueError("허용되지 않은 명령입니다.")
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
        if op == "preflight":
            return agent.preflight()
        if op == "export_checkpoint":
            from .auditing import verify_head, fingerprint
            from .packages import write_document
            head = agent.peer.call("T", "audit_head", {})["head"]
            verify_head(head, agent.trust())
            path = self.output_path("checkpoint")
            write_document(path, head)
            return {"path": str(path), "head": head, "fingerprint": fingerprint(head)}
        if op == "witness":
            result = agent.witness()
            from .packages import write_document
            path = self.output_path("anchor")
            write_document(path, result)
            return {**result, "path": str(path)}
        if op in ("retention_preview", "retention_apply"):
            from . import retention
            return retention.preview(agent) if op == "retention_preview" else retention.apply(agent, args["token"])
        if op in ("export_evidence", "export_trust"):
            from .packages import build_package, read_document, write_document, encrypt_package
            from .auditing import fingerprint
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
        if op == "export":
            # Export only public UI records, never raw prompts, quarantine bodies, keys or salts.
            target = self.directory / "exports"
            target.mkdir(exist_ok=True, parents=True)
            path = target / ("itx-results-" + str(__import__('time').time_ns()) + ".json")
            path.write_text(json.dumps({"requests": agent.history(), "audit": agent.store.get("last_audit")},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
            return {"path": str(path)}

    def output_path(self, prefix):
        from .common import now_ms
        import secrets
        directory = self.directory / "exports"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{prefix}-{now_ms()}-{secrets.token_hex(3)}.json"

    def provision(self, op, args):
        from . import enrollment
        from .packages import read_document, write_document, create_recipient, verify_package
        from .auditing import fingerprint
        from .common import MODEL_ID, MODEL_HASH
        import secrets
        if op == "enroll_prepare":
            directory = self.directory / "operators" / ("operator-" + secrets.token_hex(6))
            return {**enrollment.prepare_operator(directory, args["role"], args.get("endpoint") or None), "directory": str(directory)}
        if op == "enroll_propose":
            paths = args["card_paths"]
            if not 4 <= len(paths) <= 5:
                raise ValueError("역할별 카드 4~5개가 필요합니다.")
            proposal = enrollment.propose([read_document(p) for p in paths],
                previous=read_document(args["previous_bundle"]) if args.get("previous_bundle") else None,
                checkpoint=read_document(args["checkpoint"]) if args.get("checkpoint") else None,
                model_id=args.get("model_id") or MODEL_ID, model_hash=args.get("model_hash") or MODEL_HASH,
                model_kind=args.get("model_kind", "deterministic_mock"), model_name=args.get("model_name") or None,
                pre_exec=args.get("pre_exec", False))
            path = self.output_path("deployment-proposal")
            write_document(path, proposal)
            return {"path": str(path), "fingerprint": fingerprint(proposal), "proposal": proposal}
        if op == "enroll_endorse":
            endorsement = enrollment.endorse(args["operator_directory"], read_document(args["proposal"]),
                                               args["fingerprint"], args.get("previous_config") or None)
            path = self.output_path("endorsement")
            write_document(path, endorsement)
            return {"path": str(path), "role": endorsement["body"]["role"]}
        if op == "enroll_assemble":
            paths = args["endorsement_paths"]
            if not 4 <= len(paths) <= 5:
                raise ValueError("모든 운영자의 승인 파일이 필요합니다.")
            bundle = enrollment.assemble(read_document(args["proposal"]), [read_document(p) for p in paths],
                read_document(args["previous_bundle"]) if args.get("previous_bundle") else None)
            path = self.output_path("deployment-bundle")
            write_document(path, bundle)
            return {"path": str(path), "fingerprint": fingerprint(bundle["proposal"])}
        if op == "enroll_inspect":
            bundle = read_document(args["bundle"])
            digest = enrollment.verify_deployment(bundle)
            config = enrollment.configuration(bundle)
            return {"fingerprint": digest, "epoch": config["epoch"], "identities": config["identities"],
                    "endpoints": config["endpoints"], "model_id": config["model_id"],
                    "history": config["deployment_history"], "endorsements_verified": True,
                    "legal_independence_verified": False}
        if op == "enroll_activate":
            return enrollment.activate(args["operator_directory"], read_document(args["bundle"]), args["fingerprint"],
                bind=args.get("bind") or "127.0.0.1", model_endpoint=args.get("model_endpoint") or None,
                previous_config=args.get("previous_config") or None)
        if op == "recipient_create":
            return create_recipient(self.directory / "auditors" / secrets.token_hex(8))
        if op == "audit_verify":
            return verify_package(read_document(args["package"]), read_document(args["trust"]),
                                  args["fingerprint"], args.get("recipient_directory") or None)
        raise ValueError("unsupported provisioning operation")

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


def stdio(directory):
    with ProcessLock(Path(directory) / "app.lock"):
        _stdio(directory)


def _stdio(directory):
    output_lock = threading.Lock()
    def send(value):
        with output_lock:
            print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), flush=True)
    app = Desktop(directory, lambda event: send({"event": "progress", "data": event}))
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
    slots = threading.BoundedSemaphore(8)
    def handle(message):
        try:
            result = app.execute(message["operation"], message.get("args", {}))
            send({"id": message["id"], "ok": True, "result": result})
        except Exception as e:
            send({"id": message.get("id"), "ok": False, "error": str(e)})
        finally:
            slots.release()
    try:
        while True:
            line = sys.stdin.buffer.readline(MAX_WIRE + 1)
            if not line:
                break
            if len(line) > MAX_WIRE or not line.endswith(b"\n"):
                raise ValueError("IPC frame too large or incomplete")
            try:
                message = json_loads(line)
                if message.get("operation") == "shutdown":
                    break
                if not isinstance(message.get("id"), str) or len(message["id"]) > 80:
                    raise ValueError("invalid id")
                if not slots.acquire(False):
                    send({"id": message["id"], "ok": False, "error": "작업 큐가 가득 찼습니다."})
                    continue
                executor.submit(handle, message)
            except (ValueError, TypeError, AttributeError):
                send({"id": None, "ok": False, "error": "invalid IPC message"})
    finally:
        app.cancel_all()
        executor.shutdown(wait=True, cancel_futures=False)
        app.close()
