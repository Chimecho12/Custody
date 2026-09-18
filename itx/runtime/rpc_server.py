"""Bounded TLS transport for role services; independent of reconciliation and models."""
from __future__ import annotations

import json
import os
import ssl
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from itx.crypto import canonical_json

from .common import MAX_WIRE, json_loads, unseal
from .transport import verify_rpc


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, service, context):
        self.service, self.context = service, context
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, Handler)

    def get_request(self):
        sock, address = self.socket.accept()
        sock.settimeout(3)
        try:
            tls = self.context.wrap_socket(sock, server_side=True)
            tls.settimeout(25)
            return tls, address
        except Exception:
            sock.close()
            raise

    def process_request(self, request, client_address):
        if not self.slots.acquire(False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        try:
            if self.path != "/rpc" or self.headers.get("Transfer-Encoding"):
                raise ValueError("invalid request path or framing")
            if self.headers.get("Content-Type") != "application/json":
                raise ValueError("JSON is required")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_WIRE:
                raise ValueError("invalid content length")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("truncated request")
            rpc = json_loads(raw)
            args = verify_rpc(self.server.service.config, rpc)
            result = self.server.service.handle(*args)
            output = canonical_json({"ok": True, "result": result})
            if len(output) > MAX_WIRE:
                raise ValueError("export exceeds v1 wire limit; use a smaller deployment")
            code = 200
        except (ValueError, KeyError, TypeError, OverflowError, RecursionError):
            code, output = 400, canonical_json({"ok": False, "error": "invalid or unauthorized input"})
        except Exception as exc:
            # Frame locations aid packaged diagnostics without logging prompts, keys or payloads.
            import traceback
            frames = [f"{Path(f.filename).name}:{f.lineno}:{f.name}" for f in traceback.extract_tb(exc.__traceback__)]
            print(json.dumps({"error_type": type(exc).__name__, "frames": frames}), file=sys.stderr, flush=True)
            code, output = 503, canonical_json({"ok": False, "error": "service unavailable"})
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(output)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(output)
        except (OSError, ssl.SSLError):
            pass


def serve_rpc(service, config, parent_pipe=False):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    password = unseal(Path(config["tls_password_file"]).read_bytes()).decode() if config.get("tls_password_file") else None
    context.load_cert_chain(config["tls_cert"], config["tls_key"], password=password)
    server = Server((config.get("bind", "127.0.0.1"), config.get("port", 0)), service, context)
    stopped = threading.Event()
    def background():
        while not stopped.wait(0.2):
            if service.role in "RM":
                service.flush()
    threading.Thread(target=background, daemon=True).start()
    if parent_pipe:
        def watch_parent():
            sys.stdin.buffer.read()  # EOF on Agent death also stops grandchildren.
            os._exit(0)
        threading.Thread(target=watch_parent, daemon=True).start()
    print(json.dumps({"ready": True, "role": config["role"], "port": server.server_port}), flush=True)
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        stopped.set()
        server.server_close()

