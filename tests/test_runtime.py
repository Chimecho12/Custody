import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from itx.crypto import HAS_CRYPTOGRAPHY
from itx.runtime.agent import Agent
from itx.runtime.common import Store, authenticate, json_loads, key_for, load_config, signed
from itx.runtime.lab import Lab
from itx.statements import CT_RECEIPT


@unittest.skipUnless(HAS_CRYPTOGRAPHY, "network runtime requires cryptography")
class NetworkRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="itx-network-")
        cls.lab = Lab(Path(cls.temp.name) / "deployment")
        cls.agent = Agent(cls.lab.start())

    @classmethod
    def tearDownClass(cls):
        cls.agent.close()
        cls.lab.close()
        cls.temp.cleanup()

    def reconcile(self, record):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            try:
                value = self.agent.refresh(record["sub"])
            except RuntimeError:
                # The recovery worker may still be submitting the contract/private evidence.
                time.sleep(0.1)
                continue
            if value["t_verdict"]["payload"]["completeness"] == "complete":
                return value
            time.sleep(0.2)
        self.fail("evidence did not reach T")

    def test_01_tls_normal_strict(self):
        record = self.agent.request("정상 네트워크 요청", "strict")
        self.assertEqual(record["state"], "accept", record)
        self.assertIn("정상 네트워크 요청", record["response"])
        self.assertEqual(record["t_verdict"]["payload"]["verification_status"], "passed")
        self.assertEqual(len({c.pid for c in self.lab.children.values()}), 3)
        self.assertNotIn("private", record)

    def test_02_response_tamper_before_release(self):
        record = self.agent.request("응답 무결성 검사", "protect", "response_tamper")
        self.assertEqual(record["state"], "quarantine", record)
        self.assertIsNone(record["response"])
        self.assertIsNone(record["gate"]["consumed_at"])
        self.assertNotIn("바꾼 응답", json.dumps(record, ensure_ascii=False))
        result = self.reconcile(record)["t_verdict"]["payload"]
        self.assertEqual(result["equations"]["E6"]["result"], "pass")
        self.assertEqual(result["equations"]["E7"]["result"], "pass")
        self.assertEqual(result["equations"]["E10"]["result"], "fail")

    def test_03_request_tamper(self):
        record = self.agent.request("승인 요청", "protect", "request_tamper")
        self.assertEqual(record["state"], "quarantine", record)
        self.assertEqual(record["checks"]["request_binding"]["result"], "fail")
        self.reconcile(record)

    def test_04_observe_is_not_defense(self):
        record = self.agent.request("관찰 대조군", "observe", "response_tamper")
        self.assertEqual(record["state"], "accept_unverified")
        self.assertIn("바꾼 응답", record["response"])
        self.reconcile(record)

    def test_05_missing_receipt_is_not_accepted(self):
        record = self.agent.request("영수증 누락", "protect", "missing_receipt")
        self.assertEqual(record["state"], "quarantine", record)
        self.assertEqual(record["checks"]["M_authority"]["result"], "fail")
        self.reconcile(record)

    def test_06_t_outage_and_persistent_recovery(self):
        self.lab.stop_role("T")
        try:
            local = self.agent.request("T 장애 중 로컬 검증", "protect")
            strict = self.agent.request("T 장애 중 엄격 검증", "strict")
            self.assertEqual(local["state"], "accept", local)
            self.assertEqual(strict["state"], "reject_timeout", strict)
            self.assertIsNone(strict["response"])
            self.assertGreater(len(self.agent.store.pending()), 0)
        finally:
            self.lab.restart_t()
        self.reconcile(local)
        self.reconcile(strict)

    def test_07_wrong_role_cannot_sign_model_receipt(self):
        cfg = load_config(self.lab.root / "R" / "config.json")
        bogus = signed(cfg, key_for(cfg), CT_RECEIPT, "urn:itx:req:fake", {})
        with self.assertRaises(ValueError):
            authenticate(self.agent.config, bogus.to_dict(), "M", CT_RECEIPT)

    def test_08_pinned_audit_and_changed_checkpoint(self):
        report = self.agent.audit()
        self.assertTrue(report["ok"], report)
        self.assertTrue(report["pinned_identity"])
        saved = self.agent.store.get("checkpoint")
        bad = dict(saved, root_hash="00" * 32)
        self.agent.store.put("checkpoint", bad)
        try:
            self.assertFalse(self.agent.audit()["ok"])
        finally:
            self.agent.store.put("checkpoint", saved)
        export = self.agent.peer.call("T", "audit", {})
        export["ts_public_key"] = "ff" * 32
        with patch.object(self.agent.peer, "call", return_value=export), self.assertRaises(ValueError):
            self.agent.audit()

    def test_09_cancel_before_send(self):
        event = threading.Event()
        event.set()
        record = self.agent.request("취소 요청", "protect", cancel=event)
        self.assertEqual(record["state"], "cancelled")
        self.assertIsNone(record["response"])

    def test_10_expired_policy(self):
        with patch.dict(self.agent.config, policy_expires_at=0), self.assertRaises(ValueError):
            self.agent.request("만료 정책", "protect")

    def test_11_authenticated_verdict_must_bind_current_contract(self):
        record = self.agent.request("판정 결합 검사", "protect")
        current = self.reconcile(record)
        saved = self.agent.store.get("request:" + record["sub"])
        cfg = load_config(self.lab.root / "T" / "config.json")
        from itx.statements import CT_VERDICT
        payload = dict(current["t_verdict"]["payload"], contract_hash="00" * 32)
        fake = signed(cfg, key_for(cfg), CT_VERDICT, record["sub"], payload)
        with (patch.object(self.agent.peer, "call", return_value={"statement": fake.to_dict()}),
              self.assertRaisesRegex(ValueError, "정책·요청")):
            self.agent.verdict(saved)

    def test_12_same_execution_is_returned_without_second_model_call(self):
        record = self.agent.request("중복 요청 검사", "protect")
        saved = self.agent.store.get("request:" + record["sub"])
        payload = {"contract": saved["contract"], "body": {"prompt": "중복 요청 검사"},
                   "salt": saved["private"]["salt"], "scenario": "normal"}
        first = self.agent.peer.call("R", "infer", payload)
        second = self.agent.peer.call("R", "infer", payload)
        self.assertEqual(first["receipt"], second["receipt"])
        self.assertEqual(first["relay"], second["relay"])
        payload["body"] = {"prompt": "다른 요청"}
        with self.assertRaises(RuntimeError):
            self.agent.peer.call("R", "infer", payload)

    def test_13_agent_restart_recovers_pending_without_release(self):
        record = self.agent.request("재시작 복구", "protect")
        self.reconcile(record)
        path = self.agent.config["config_path"]
        checkpoint = self.agent.store.get("checkpoint")
        saved = self.agent.store.get("request:" + record["sub"])
        saved.update(state="pending", response=None)
        self.agent.store.put("request:" + record["sub"], saved)
        self.agent.close()
        type(self).agent = Agent(path)
        recovered = self.agent.store.get("request:" + record["sub"])
        self.assertEqual(recovered["state"], "interrupted")
        self.assertIsNone(recovered["response"])
        self.assertEqual(self.agent.store.get("checkpoint"), checkpoint)


class RuntimeInputTests(unittest.TestCase):
    def test_process_lock_excludes_second_writer_and_releases(self):
        from itx.runtime.common import ProcessLock
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "service.lock"
            with ProcessLock(path), self.assertRaises(RuntimeError):
                ProcessLock(path)
            with ProcessLock(path):
                pass

    def test_duplicate_keys_and_float_rejected(self):
        for raw in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":1.5}'):
            with self.assertRaises(ValueError):
                json_loads(raw)

    def test_queue_full_does_not_drop_existing_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.enqueue({"evidence": "first"}, capacity=1)
            with self.assertRaises(RuntimeError):
                store.enqueue({"evidence": "second"}, capacity=1)
            store.close()
            reopened = Store(directory)
            self.assertEqual(reopened.pending()[0][1]["evidence"], "first")
            reopened.close()
