"""Consumer-boundary and actual HTTP adapter fixtures; no real LLM required."""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from itx.client import ItxClient, ResponseRejected
from itx.runtime.common import MAX_RESPONSE, MAX_WIRE
from itx.runtime.models import model_reply, parse_ollama_response, validate_model_endpoint
from itx.runtime.service import Service


class SdkTests(unittest.TestCase):
    def test_consumer_release_outage_and_clean_restart(self):
        with tempfile.TemporaryDirectory(prefix="itx-sdk-") as directory:
            with ItxClient(directory, lab=True) as client:
                response = client.request("SDK 정상", mode="strict")
                self.assertIn("SDK 정상", response.text)
                self.assertTrue(all(v["result"] == "pass" for v in response.checks.values()))
                with self.assertRaises(ValueError):
                    client.request("observe must be explicit", mode="observe")
                self.assertEqual(client.observe("control")["state"], "accept_unverified")
                bad = client._call("request", {"prompt": "SDK tamper", "mode": "protect",
                                   "scenario": "response_tamper", "token": "test-tamper"})
                self.assertEqual(bad["state"], "quarantine")
                self.assertIsNone(bad["response"])
                self.assertNotIn("quarantined_body", bad)
                client._call("stop_t")
                self.assertIn("outage", client.request("outage", mode="protect").text)
                with self.assertRaises(ResponseRejected) as caught:
                    client.request("must not release", mode="strict")
                self.assertEqual(caught.exception.state, "reject_timeout")
                self.assertFalse(hasattr(caught.exception, "text"))
                self.assertFalse(hasattr(caught.exception, "response"))
                client._call("start_t")
            self.assertEqual(client.proc.returncode, 0)
            self.assertFalse(client.reader.is_alive())
            self.assertFalse(client.error_reader.is_alive())
            self.assertTrue(client.proc.stdout.closed and client.proc.stderr.closed and client.proc.stdin.closed)
            with ItxClient(directory, lab=True) as restarted:
                self.assertEqual(len(restarted._call("history")), 5)
                self.assertEqual(restarted.request("restart", mode="strict").mode, "strict")


class OllamaAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                cls.seen.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                self.send_response(cls.status)
                if cls.status == 302:
                    self.send_header("Location", "/redirect-target")
                self.send_header("Content-Length", str(len(cls.payload)))
                self.end_headers()
                self.wfile.write(cls.payload)
            def log_message(self, *args):
                pass
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.service = Service.__new__(Service)
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        type(self).status = 200
        type(self).seen = []
        type(self).payload = json.dumps({"model": "fixture:latest", "response": "한글 fixture", "done": True}).encode()
        self.service.config = {"model_kind": "ollama", "model_name": "fixture:latest", "model_endpoint": self.endpoint}

    def test_nonstreaming_request_and_exact_model(self):
        self.assertEqual(self.service.model_reply({"prompt": "hello"}), {"text": "한글 fixture"})
        self.assertEqual(self.seen, [("/api/generate", {"model": "fixture:latest", "prompt": "hello", "stream": False})])

    def test_incomplete_duplicate_wrong_model_and_oversize_rejected(self):
        cases = [b'{"model":"fixture:latest","response":"x","done":1}',
                 b'{"model":"fixture:latest","response":"x","response":"y","done":true}',
                 b'{"model":"other:latest","response":"x","done":true}',
                 b'{"model":"fixture:latest","response":"x","done":false}',
                 json.dumps({"model": "fixture:latest", "response": "x" * (MAX_RESPONSE + 1), "done": True}).encode()]
        for payload in cases:
            with self.subTest(payload=payload[:70]):
                type(self).payload = payload
                with self.assertRaises(ValueError):
                    self.service.model_reply({"prompt": "hello"})

    def test_redirect_and_remote_cleartext_never_followed(self):
        type(self).status = 302
        with self.assertRaisesRegex(ValueError, "redirects"):
            self.service.model_reply({"prompt": "hello"})
        self.assertEqual(len(self.seen), 1)
        self.service.config["model_endpoint"] = "http://example.invalid"
        with self.assertRaises(ValueError):
            self.service.model_reply({"prompt": "hello"})
        self.assertEqual(len(self.seen), 1)

    def test_endpoint_validation_happens_before_the_request(self):
        for endpoint in ("http://example.invalid", self.endpoint + "/api/generate",
                         self.endpoint + "?model=other", self.endpoint + "#fragment",
                         "https://user:password@example.invalid", "file:///tmp/model"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                model_reply({**self.service.config, "model_endpoint": endpoint}, {"prompt": "hello"})
        self.assertEqual(self.seen, [])
        self.assertEqual(validate_model_endpoint("https://model.example.invalid/"), "https://model.example.invalid")

    def test_provider_metadata_allows_finite_numbers_but_not_ambiguous_json(self):
        type(self).payload = b'{"model":"fixture:latest","response":"ok","done":true,"score":0.5}'
        self.assertEqual(model_reply(self.service.config, {"prompt": "hello"}), {"text": "ok"})
        for number in ("NaN", "Infinity", "-Infinity"):
            raw = '{"model":"fixture:latest","response":"ok","done":true,"score":' + number + '}'
            with self.subTest(number=number), self.assertRaises(ValueError):
                parse_ollama_response(raw, "fixture:latest")

    def test_wire_limit_applies_to_provider_metadata_too(self):
        type(self).payload = json.dumps({"model": "fixture:latest", "response": "ok", "done": True,
                                        "metadata": "x" * MAX_WIRE}).encode()
        with self.assertRaisesRegex(ValueError, "too large"):
            model_reply(self.service.config, {"prompt": "hello"})

    def test_mock_and_unknown_providers_do_not_open_connections(self):
        self.assertIn("hello", model_reply({"model_kind": "deterministic_mock"}, {"prompt": "hello"})["text"])
        with self.assertRaisesRegex(ValueError, "unsupported model adapter"):
            model_reply({**self.service.config, "model_kind": "unknown"}, {"prompt": "hello"})
        self.assertEqual(self.seen, [])


class PreExecutionAndRetirementTests(unittest.TestCase):
    def test_model_gate_and_retirement_before_response_release(self):
        from unittest.mock import patch

        from itx.runtime.agent import Agent
        from itx.runtime.common import Store
        from itx.runtime.lab import Lab
        with tempfile.TemporaryDirectory(prefix="itx-pre-exec-") as directory:
            lab = Lab(Path(directory) / "lab")
            for role in "URMT":
                path = lab.root / role / "config.json"
                config = json.loads(path.read_text())
                config["pre_exec"] = True
                path.write_text(json.dumps(config))
            agent = Agent(lab.start())
            try:
                rejected = agent.request("before execution", "protect", "request_tamper")
                self.assertEqual(rejected["state"], "error")
                self.assertIsNone(rejected["response"])
                store = Store(lab.root / "M")
                try:
                    saved = store.get("execution:" + rejected["sub"])
                    self.assertEqual(saved["status"], "started")
                    self.assertNotIn("result", saved)
                finally:
                    store.close()
                self.assertEqual(agent.request("permitted execution", "strict")["state"], "accept")
                original = agent.peer.call
                def retire_after_receive(role, op, payload, **kwargs):
                    reply = original(role, op, payload, **kwargs)
                    if role == "R" and op == "infer":
                        (lab.root / "U" / "retirement.json").write_text("{}")
                    return reply
                with patch.object(agent.peer, "call", side_effect=retire_after_receive):
                    retired = agent.request("retired while in flight", "protect")
                self.assertEqual(retired["state"], "error")
                self.assertIsNone(retired["response"])
                self.assertIn("폐기", retired["error"])
            finally:
                agent.close()
                lab.close()
