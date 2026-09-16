"""Bounded line-framed IPC. Standard output is reserved for protocol messages."""
import concurrent.futures
import json
import sys
import threading
from pathlib import Path

from ..common import MAX_WIRE, ProcessLock, json_loads
from .controller import Desktop


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
