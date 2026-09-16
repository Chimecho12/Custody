"""Desktop lifecycle and IPC contracts must survive module boundaries."""
from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch

from itx.runtime.desktop import ALLOWED_OPERATIONS, Desktop
from itx.runtime.desktop.ipc import _stdio


class DesktopLifecycle(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = Desktop(self.directory.name, lambda event: None)
        self.app.agent = Mock()
        self.app.agent.status.return_value = {"source": "test"}
        self.app.agent.history.return_value = []
        self.addCleanup(self.app.close)

    def test_running_request_can_be_inspected_and_cancelled_but_not_replaced(self):
        entered = threading.Event()

        def request(prompt, mode, scenario, cancellation, token):
            entered.set()
            if not cancellation.wait(5):
                raise TimeoutError("test request was not cancelled")
            return {"state": "cancelled", "token": token}

        self.app.agent.request.side_effect = request
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.app.execute, "request", {"prompt": "test", "mode": "protect", "token": "one"})
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(self.app.execute("history", {}), [])
                self.assertEqual(set(self.app.execute("status", {})["operations"]), ALLOWED_OPERATIONS)
                with self.assertRaises(ValueError):
                    self.app.execute("connect", {"path": "not-opened.json"})
                self.assertEqual(self.app.execute("cancel", {"token": "one"}), {"requested": True})
                self.assertEqual(future.result(timeout=5)["state"], "cancelled")
            finally:
                self.app.cancel_all()
        self.assertEqual(self.app.active, {})
        self.assertEqual(self.app.execute("cancel", {"token": "one"}), {"requested": False})
        self.app.execute("refresh", {"sub": "next"})
        self.app.agent.refresh.assert_called_once_with("next")

    def test_failed_request_releases_token_and_operation_lock(self):
        self.app.agent.request.side_effect = RuntimeError("unavailable")
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            self.app.execute("request", {"prompt": "test", "mode": "strict", "token": "one"})
        self.assertEqual(self.app.active, {})
        self.app.agent.request.side_effect = None
        self.app.agent.request.return_value = {"state": "accept"}
        self.assertEqual(self.app.execute("request", {"prompt": "test", "mode": "strict", "token": "one"}),
                         {"state": "accept"})

    def test_provisioning_does_not_require_an_agent_connection(self):
        with patch.object(self.app, "ensure", side_effect=AssertionError("must not connect")), \
                patch("itx.runtime.desktop.controller.provision", return_value={"ok": True}) as provision:
            self.assertEqual(self.app.execute("enroll_inspect", {"bundle": "bundle.json"}), {"ok": True})
        self.assertEqual(provision.call_args.args[0], self.app.directory)
        self.assertEqual(provision.call_args.args[2:], ("enroll_inspect", {"bundle": "bundle.json"}))

    def test_unknown_operation_is_rejected_and_next_command_still_works(self):
        with self.assertRaises(ValueError):
            self.app.execute("unknown", {})
        self.app.execute("preflight", {})
        self.app.agent.preflight.assert_called_once_with()


class StdioProtocol(unittest.TestCase):
    def test_invalid_frame_does_not_hide_later_results_and_errors(self):
        frames = b'not-json\n{"id":"one","operation":"status"}\n{"id":"two","operation":"bad"}\n{"operation":"shutdown"}\n'
        output = io.StringIO()
        app = Mock()

        def execute(operation, args):
            if operation == "bad":
                raise ValueError("unsupported")
            return {"operations": sorted(ALLOWED_OPERATIONS)}

        app.execute.side_effect = execute
        with patch("itx.runtime.desktop.ipc.Desktop", return_value=app), \
                patch("sys.stdin", SimpleNamespace(buffer=io.BytesIO(frames))), patch("sys.stdout", output):
            _stdio("unused")
        replies = {message["id"]: message for message in map(json.loads, output.getvalue().splitlines())}
        self.assertFalse(replies[None]["ok"])
        self.assertEqual(set(replies["one"]["result"]["operations"]), ALLOWED_OPERATIONS)
        self.assertEqual(replies["two"], {"id": "two", "ok": False, "error": "unsupported"})
        app.cancel_all.assert_called_once_with()
        app.close.assert_called_once_with()
