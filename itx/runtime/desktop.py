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
            # Let the user repair a missing/invalid saved connection without silent fallback.
            if op in ("connect", "lab"):
                if self.active:
                    raise ValueError("진행 요청을 완료하거나 취소한 뒤 연결을 변경하세요.")
                if op == "connect":
                    path = Path(args["path"]).resolve(strict=True)
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
            elif op not in ("refresh", "audit", "simulation", "export"):
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
