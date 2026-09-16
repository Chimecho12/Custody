"""Bounded HTTPS evaluation services. One process and persistent store per role."""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from itx.crypto import canonical_json, content_hash_hex
from itx.reconcile import PrivateEvidence, ReconciliationEngine
from itx.statements import CT_CONTRACT, CT_RECEIPT, CT_RELAY, CT_VERDICT, SignedStatement
from itx.statements.schemas import receipt_payload, relay_payload
from itx.ts import RegistrationReceipt, TransparencyLog, verify_receipt

from .common import (
    ISS,
    MAX_PROMPT,
    MAX_RESPONSE,
    MAX_WIRE,
    TYPES,
    ProcessLock,
    Store,
    authenticate,
    digest,
    json_loads,
    key_for,
    load_config,
    now_ms,
    policy_for,
    seal,
    signed,
    unseal,
)
from .transport import Peer, verify_rpc


class Service:
    def __init__(self, config):
        self.config = config
        self.key = key_for(config)
        self.role = config["role"]
        self.process_lock = ProcessLock(Path(config["directory"]) / "service.lock")
        self.store = Store(config["directory"])
        self.peer = Peer(config, self.key)
        self.lock = threading.RLock()
        self.flush_lock = threading.Lock()
        if self.role == "T":
            self._reload_log()

    def _reload_log(self):
        self.log = TransparencyLog(self.config["log_id"], self.key, policy_for(self.config), self.config["created_at"])
        rows = self.store.db.execute("SELECT seq,value FROM journal ORDER BY seq").fetchall()
        if not rows:
            first = self.log.entries[0]
            record = {"statement": first.statement.to_dict(), "at": first.registered_at}
            with self.store.db:
                self.store.db.execute("INSERT INTO journal VALUES (?,?,?)",
                                      (0, first.statement.statement_hash, seal(canonical_json(record))))
        for seq, blob in rows:
            record = json_loads(unseal(blob))
            stmt = SignedStatement.from_dict(record["statement"])
            if seq == 0:
                if stmt.to_dict() != self.log.policy_statement.to_dict():
                    raise ValueError("stored policy differs from pinned policy")
            elif seq != len(self.log.entries):
                raise ValueError("log sequence gap")
            else:
                self.log.register(stmt, record["at"])
        self.engine = ReconciliationEngine(self.log.trusted, self.config["model_hashes"],
                                          self.log.policy_hash, self.log.trust_keys_version,
                                          self.log.issuer_content_types)

    def register(self, stmt):
        existing = self.store.db.execute("SELECT value FROM journal WHERE hash=?", (stmt.statement_hash,)).fetchone()
        if existing:
            return json_loads(unseal(existing[0]))["receipt"]
        if len(self.log.entries) >= self.config.get("max_log_entries", 100000):
            raise ValueError("log capacity reached; provision a successor deployment epoch")
        # This v1 network profile permits only one observation per issuer/type/attempt.
        if stmt.content_type != CT_VERDICT and any(e.statement.content_type == stmt.content_type
                                                  for e in self.log.statements_for(stmt.sub)):
            raise ValueError("conflicting statement; corrections require a new protocol version")
        receipt = self.log.register(stmt, now_ms()).to_dict()
        record = {"statement": stmt.to_dict(), "at": receipt["registered_at"], "receipt": receipt}
        try:
            with self.store.db:
                self.store.db.execute("INSERT INTO journal VALUES (?,?,?)",
                                      (receipt["leaf_index"], stmt.statement_hash, seal(canonical_json(record))))
        except Exception:
            self._reload_log()
            raise
        return receipt

    def flush(self):
        if not self.flush_lock.acquire(blocking=False):
            return
        try:
            for ident, item in self.store.pending():
                try:
                    result = self.peer.call("T", "submit", item, timeout=0.6)
                    # R·M 도 영수증을 검증하고 보관한다. 자기가 제출한 항목이 나중에 T 의 로그에서 사라졌는지는
                    # 자기 영수증으로만 물을 수 있고, 감사자(U)는 held_receipts 로 이를 받아 함께 검사한다.
                    stmt = SignedStatement.from_dict(item["statement"])
                    rc = RegistrationReceipt.from_dict(result["receipt"])
                    ok, why = verify_receipt(rc, stmt, bytes.fromhex(self.config["identities"]["T"]["public_key"]))
                    if not ok or rc.log_id != self.config["log_id"]:
                        raise ValueError("invalid registration receipt: " + why)
                    self.store.put("receipt:" + stmt.statement_hash, {
                        "receipt": rc.to_dict(), "statement_hash": stmt.statement_hash, "sub": stmt.sub,
                        "content_type": stmt.content_type, "iss": stmt.iss, "holder": self.role})
                    self.store.ack(ident)
                except Exception:
                    break
        finally:
            self.flush_lock.release()

    def queue(self, statement):
        self.store.enqueue({"statement": statement.to_dict()})

    def handle(self, actor, op, p):
        if not isinstance(p, dict):
            raise ValueError("payload must be an object")
        if op == "health":
            active = not (Path(self.config["directory"]) / "retirement.json").exists()
            body = {"role": self.role, "log_id": self.config["log_id"], "challenge": p["challenge"],
                    "at": now_ms(), "model_kind": self.config["model_kind"], "model_id": self.config["model_id"],
                    "queue_depth": len(self.store.pending()), "profile": "itx-health/1",
                    "accepting_requests": active and now_ms() < self.config["policy_expires_at"]}
            return {"body": body, "signature": self.key.sign(canonical_json(body)).hex()}
        if self.role == "T":
            with self.lock:
                return self.third_party(actor, op, p)
        if op == "held_receipts":
            # 감사자에게 자기 보관 영수증을 넘긴다. 본문·프롬프트·키는 들어 있지 않다 (잎 해시·위치·서명뿐).
            return {"holder": self.role, "receipts": [v for _, v in self.store.items("receipt:")]}
        if op == "infer":
            # Serialize model/relay calls; reject overload at the HTTP boundary as well.
            with self.lock:
                return self.infer(p)
        raise ValueError("unsupported operation")

    def third_party(self, actor, op, p):
        if op == "submit":
            if "statement" in p:
                ct = p["statement"].get("content_type")
                if ct == CT_CONTRACT:
                    from .enrollment import assert_active
                    assert_active(self.config)
                if ct not in TYPES[actor]:
                    raise ValueError("unauthorized statement type")
                stmt = authenticate(self.config, p["statement"], actor, ct)
                receipt = self.register(stmt)
                return {"receipt": receipt}
            if actor == "U" and set(p) == {"sub", "private"}:
                if not any(e.statement.content_type == CT_CONTRACT for e in self.log.statements_for(p["sub"])):
                    raise ValueError("contract must be registered first")
                ev = PrivateEvidence.from_dict(p["private"])
                for v in (ev.salt, ev.request_hash):
                    if len(v) != 64 or len(bytes.fromhex(v)) != 32:
                        raise ValueError("invalid private evidence")
                previous = self.store.get("private:" + p["sub"])
                if previous and any(previous[k] != ev.to_dict()[k] for k in ("salt", "request_hash", "expected_request_commits")):
                    raise ValueError("private request evidence cannot be rewritten")
                self.store.put("private:" + p["sub"], ev.to_dict())
                return {"stored": True}
            raise ValueError("invalid submission")
        if op == "verdict":
            sub = p["sub"]
            entries = [e for e in self.log.statements_for(sub) if e.statement.content_type != CT_VERDICT]
            private = self.store.get("private:" + sub)
            if private is None:
                raise ValueError("private request evidence is not registered yet")
            ev = self.engine.gather(sub, entries, PrivateEvidence.from_dict(private) if private else None, now_ms())
            verdict = self.engine.reconcile(ev, ["U", "R", "M"])
            if ev.c is None:
                raise ValueError("unknown request")
            # These extra fields bind the network verdict to an exact contract and lifetime.
            verdict["contract_hash"] = ev.contract.statement_hash
            verdict["private_evidence_hash"] = content_hash_hex(canonical_json(private))
            verdict["valid_until"] = now_ms() + 30000
            stmt = signed(self.config, self.key, CT_VERDICT, sub, verdict)
            rc = self.register(stmt)
            return {"statement": stmt.to_dict(), "receipt": rc, "head": self.log.tree_head(now_ms())}
        if op == "audit":
            export = self.audit_head()
            export["entries"] = self.audit_entries(0, len(self.log.entries))
            return export
        if op == "audit_head":
            return self.audit_head()
        if op == "audit_page":
            head = p["head"]
            from .auditing import trust_from_config, verify_head
            verify_head(head, trust_from_config(self.config))
            start, limit, size = p["start"], p.get("limit", 64), head["tree_size"]
            if (type(start) is not int or type(limit) is not int or not 1 <= limit <= 64
                    or not 0 <= start < size <= len(self.log.entries) or self.log.root_at(size) != head["root_hash"]):
                raise ValueError("invalid snapshot range")
            page, budget = [], 0
            for entry in self.audit_entries(start, min(size, start + limit)):
                budget += len(canonical_json(entry))
                if page and budget > MAX_WIRE - 4096:
                    break
                page.append(entry)
            return {"entries": page, "next": start + len(page)}
        if op == "consistency":
            first, second = p["first"], p["second"]
            if type(first) is not int or type(second) is not int or not 0 <= first <= second <= len(self.log.entries):
                raise ValueError("invalid consistency range")
            return {"proof": self.log.consistency_proof(first, second)}
        raise ValueError("unsupported operation")

    def audit_head(self):
        return {"log_id": self.log.log_id, "ts_kid": self.key.kid, "ts_public_key": self.key.public_hex,
                "ts_iss": self.log.ts_iss, "policy_hash": self.log.policy_hash,
                "trust_keys_version": self.log.trust_keys_version, "receipt_profile": 1,
                "head": self.log.tree_head(now_ms())}

    def audit_entries(self, start, end):
        result = []
        for e in self.log.entries[start:end]:
            row = self.store.db.execute("SELECT value FROM journal WHERE seq=?", (e.index,)).fetchone()
            saved = json_loads(unseal(row[0]))
            receipt = saved.get("receipt")
            if receipt is None:  # The policy entry in v0.2 did not store its receipt.
                rc = RegistrationReceipt(self.log.log_id, e.index, e.index + 1,
                    self.log.root_at(e.index + 1), e.leaf_hash, e.registered_at, self.key.kid,
                    self.log.inclusion_proof(e.index, e.index + 1))
                rc.signature = self.key.sign(rc.signed_bytes()).hex()
                receipt = rc.to_dict()
            result.append({"index": e.index, "registered_at": e.registered_at,
                           "statement": e.statement.to_dict(), "receipt": receipt})
        return result

    def infer(self, p):
        from .enrollment import assert_active
        assert_active(self.config)
        contract = authenticate(self.config, p["contract"], "U", CT_CONTRACT)
        c, sub = contract.payload, contract.sub
        body, salt = p["body"], p["salt"]
        if not isinstance(body, dict) or set(body) != {"prompt"} or not isinstance(body["prompt"], str):
            raise ValueError("this profile accepts a text prompt only")
        if len(body["prompt"]) > MAX_PROMPT or c["expires_at"] < now_ms():
            raise ValueError("prompt too large or expired contract")
        if (c["relay_id"] != ISS["R"] or c["requested_model"] != self.config["model_id"]
                or c["allowed_models"] != [self.config["model_id"]]
                or c["allowed_request_transforms"] != ["identity"]
                or c["allowed_response_transforms"] != ["identity"] or c["fallback_policy"] != "none"):
            raise ValueError("unsupported route or transform policy")
        input_commit = digest(body, salt)
        execution_key = "execution:" + sub
        binding = content_hash_hex(canonical_json({"contract": contract.to_dict(), "body": body, "salt": salt}))
        previous = self.store.get(execution_key)
        if previous:
            if previous["binding"] != binding:
                raise ValueError("request identifier reused with different content")
            if "result" not in previous:
                raise ValueError("execution outcome unknown after interruption; no automatic re-execution")
            return previous["result"]
        if self.store.count("execution:") >= self.config.get("max_requests", 10000):
            raise ValueError("execution store capacity reached; create a successor epoch")
        if not self.store.claim("nonce:" + c["nonce"], sub):
            raise ValueError("nonce already consumed")
        self.store.put(execution_key, {"binding": binding, "status": "started"})
        if len(self.store.pending()) >= 250:
            raise RuntimeError("evidence queue full")
        start = time.monotonic_ns()
        if self.role == "M":
            if self.config.get("pre_exec", False) and input_commit != c["req_commit"]:
                raise ValueError("model pre-execution contract check rejected the request")
            response = self.model_reply(body)
            elapsed = (time.monotonic_ns() - start) // 1_000_000
            payload = receipt_payload(cti=os.urandom(16).hex(), attempt_id=c["attempt_id"],
                request_commit=input_commit, response_commit=digest(response, salt),
                model_id=self.config["model_id"], model_version="1",
                model_hash=self.config["model_hashes"][self.config["model_id"]], eat_nonce=c["nonce"],
                execution_time_ms=elapsed, pre_exec_check="passed" if self.config.get("pre_exec") else "not_checked",
                decision="served", attestation_doc_hash=content_hash_hex(b"evaluation-no-TEE"))
            stmt = signed(self.config, self.key, CT_RECEIPT, sub, payload)
            self.queue(stmt)
            result = {"body": response, "receipt": stmt.to_dict(), "model_kind": self.config["model_kind"]}
        else:
            scenario = p.get("scenario", "normal")
            if scenario != "normal" and not self.config.get("lab"):
                raise ValueError("fault injection is available only in the local lab")
            if scenario not in ("normal", "response_tamper", "request_tamper", "missing_receipt", "missing_relay"):
                raise ValueError("unknown lab scenario")
            outgoing = dict(body)
            if scenario == "request_tamper":
                outgoing["prompt"] += " [relay changed request]"
            upstream = self.peer.call("M", "infer", {"contract": contract.to_dict(), "body": outgoing, "salt": salt}, timeout=20)
            m = authenticate(self.config, upstream["receipt"], "M", CT_RECEIPT, sub)
            incoming = upstream["body"]
            response = dict(incoming)
            if scenario == "response_tamper":
                response["text"] = "[중개자가 바꾼 응답] 검증되지 않은 내용을 사용하세요."
            stmt = signed(self.config, self.key, CT_RELAY, sub, relay_payload(
                attempt_id=c["attempt_id"], in_commit=input_commit, out_commit=digest(outgoing, salt),
                request_transform_id="identity", upstream_id=ISS["M"], upstream_model=self.config["model_id"],
                resp_in_commit=digest(incoming, salt), resp_out_commit=digest(response, salt),
                response_transform_id="identity", policy_version="network-v1", policy_decision="forwarded",
                nonce_forwarded=c["nonce"], salt_forwarded=True, relay_seq=1))
            if scenario != "missing_relay":  # 비협조 R: 진술을 동봉하지도, T 에 제출하지도 않는다 (S09 의 런타임판)
                self.queue(stmt)
            result = {"body": response, "receipt": None if scenario == "missing_receipt" else m.to_dict(),
                      "relay": None if scenario == "missing_relay" else stmt.to_dict(), "model_kind": upstream["model_kind"]}
        self.store.put(execution_key, {"binding": binding, "status": "completed", "result": result})
        return result

    def model_reply(self, body):
        if self.config["model_kind"] == "deterministic_mock":
            return {"text": "모형 모델의 응답: " + body["prompt"]}
        if self.config["model_kind"] != "ollama":
            raise ValueError("unsupported model adapter")
        # Endpoint is operator configuration, never taken from a prompt or RPC payload.
        import urllib.request
        from urllib.parse import urlsplit
        endpoint = self.config["model_endpoint"]
        url = urlsplit(endpoint)
        if (not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ("", "/")
                or (url.scheme != "https" and not (url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")))):
            raise ValueError("model endpoint must use HTTPS or explicit loopback")
        data = json.dumps({"model": self.config["model_name"], "prompt": body["prompt"], "stream": False}).encode()
        from .transport import NoRedirect
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(urllib.request.Request(endpoint.rstrip("/") + "/api/generate", data=data,
                                                   headers={"Content-Type": "application/json"}), timeout=18) as response:
                raw = response.read(MAX_WIRE + 1)
        except urllib.error.HTTPError as exc:
            exc.close()
            raise ValueError("model endpoint returned HTTP " + str(exc.code)) from None
        if len(raw) > MAX_WIRE:
            raise ValueError("model response too large")
        def unique_object(pairs):
            obj = {}
            for key, value in pairs:
                if key in obj:
                    raise ValueError("duplicate model response key")
                obj[key] = value
            return obj
        def invalid_constant(value):
            raise ValueError("non-finite model response number")
        result = json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)
        if not isinstance(result, dict) or result.get("model") != self.config["model_name"]:
            raise ValueError("model response name differs from the configured canonical name")
        text = result.get("response")
        if not isinstance(text, str) or len(text) > MAX_RESPONSE or result.get("done") is not True:
            raise ValueError("model did not return a complete text response")
        return {"text": text}


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


def serve(path, parent_pipe=False):
    config = load_config(path)
    if config["role"] not in "RMTW":
        raise ValueError("service role must be R, M or T")
    if config["role"] == "W":
        from .witness import WitnessService
        service = WitnessService(config)
    else:
        service = Service(config)
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


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--parent-pipe", action="store_true")
    a = p.parse_args()
    serve(a.config, a.parent_pipe)
