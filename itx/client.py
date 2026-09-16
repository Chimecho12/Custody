"""Small stdlib SDK for apps that explicitly route requests through an itx Agent."""
from __future__ import annotations

import concurrent.futures
import json
import os
import secrets
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path


class ResponseRejected(RuntimeError):
    def __init__(self, record):
        self.state = record.get("state", "error")
        self.request_id = record.get("sub")
        self.checks = record.get("checks", {})
        super().__init__("itx did not release this response: " + self.state)


@dataclass(frozen=True)
class VerifiedResponse:
    text: str
    request_id: str
    mode: str
    elapsed_ms: int
    checks: dict


class ItxClient:
    def __init__(self, data_directory, *, config=None, agent_binary=None, lab=False):
        if not config and not lab:
            raise ValueError("supply a pinned U config or explicitly select lab=True")
        command = [str(Path(agent_binary).resolve())] if agent_binary else [sys.executable, "-B", str(Path(__file__).resolve().parents[1] / "runtime.py")]
        self.proc = subprocess.Popen([*command, "desktop", "--data-dir", str(Path(data_directory).resolve())],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", creationflags=0x08000000 if os.name == "nt" else 0,
            env=dict(os.environ, PYTHONUTF8="1"))
        self.lock = threading.Lock()
        self.pending = {}
        self.closed = False
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.error_reader = threading.Thread(target=self._drain_errors, daemon=True)
        self.reader.start()
        self.error_reader.start()
        try:
            self._call("connect", {"path": str(Path(config).resolve())}) if config else self._call("status")
        except Exception:
            self.close()
            raise

    def _drain_errors(self):
        for _ in self.proc.stderr:
            pass

    def _read(self):
        try:
            for line in self.proc.stdout:
                message = json.loads(line)
                with self.lock:
                    future = self.pending.pop(message.get("id"), None)
                if future:
                    if message.get("ok"):
                        future.set_result(message["result"])
                    else:
                        future.set_exception(RuntimeError(message.get("error", "Agent error")))
        finally:
            with self.lock:
                for future in self.pending.values():
                    future.set_exception(RuntimeError("Agent disconnected"))
                self.pending.clear()

    def _call(self, operation, args=None, timeout=90):
        ident = secrets.token_hex(12)
        future = concurrent.futures.Future()
        with self.lock:
            if self.closed or self.proc.poll() is not None:
                raise RuntimeError("Agent is closed")
            self.pending[ident] = future
            try:
                self.proc.stdin.write(json.dumps({"id": ident, "operation": operation, "args": args or {}}) + "\n")
                self.proc.stdin.flush()
            except OSError:
                self.pending.pop(ident, None)
                raise
        try:
            return future.result(timeout)
        finally:
            with self.lock:
                self.pending.pop(ident, None)

    def request(self, prompt, *, mode="protect", token=None):
        if mode not in ("protect", "strict"):
            raise ValueError("request() requires protect or strict; use observe() for the unverified control")
        record = self._call("request", {"prompt": prompt, "mode": mode, "token": token or secrets.token_hex(16)})
        if record["state"] != "accept" or not isinstance(record.get("response"), str):
            raise ResponseRejected(record)
        return VerifiedResponse(record["response"], record["sub"], mode, record["elapsed_ms"], record["checks"])

    def observe(self, prompt):
        return self._call("request", {"prompt": prompt, "mode": "observe", "token": secrets.token_hex(16)})

    def cancel(self, token):
        return self._call("cancel", {"token": token})

    def status(self):
        return self._call("status")

    def audit(self):
        return self._call("audit")

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            if self.proc.poll() is None:
                try:
                    self.proc.stdin.write('{"operation":"shutdown"}\n')
                    self.proc.stdin.flush()
                except OSError:
                    pass
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        self.reader.join(timeout=5)
        self.error_reader.join(timeout=5)
        self.proc.stdout.close()
        self.proc.stderr.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
