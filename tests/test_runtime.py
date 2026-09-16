import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from itx.crypto import HAS_CRYPTOGRAPHY
from itx.runtime.agent import Agent
from itx.runtime.common import Store, authenticate, json_loads, key_for, load_config, policy_for, seal, signed, unseal
from itx.runtime.lab import Lab
from itx.statements import CT_RECEIPT, SignedStatement
from itx.ts import TransparencyLog


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

    def reconcile(self, record, completeness=("complete",)):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            try:
                value = self.agent.refresh(record["sub"])
            except RuntimeError:
                # The recovery worker may still be submitting the contract/private evidence.
                time.sleep(0.1)
                continue
            if value["t_verdict"]["payload"]["completeness"] in completeness:
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
        # 결손은 위반이 아니라 평가 불가다. 격리는 필수 로컬 검사(receipt_present)가 한다.
        self.assertEqual(record["checks"]["M_authority"]["result"], "not_evaluable")
        self.assertEqual(record["checks"]["receipt_present"]["result"], "fail")
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


    def test_14_omitted_log_entries_are_caught_only_by_held_receipts(self):
        """T 가 어떤 요청의 항목을 전부 빼고 저널을 다시 꾸민 뒤 재기동한다. 트리·헤드·영수증 프로파일은
        전부 새로 맞춰지므로 로그만 보는 감사는 통과한다. Agent 가 보관한 등록 영수증만 누락을 본다."""
        record = self.agent.request("영수증 보관 검사", "protect")
        self.reconcile(record)
        # 앞선 테스트가 남긴 판정 없는 요청(취소·미조회)에 사후 판정을 붙여 감사 기준선을 깨끗하게 만든다.
        for _, saved in self.agent.store.items("request:"):
            if saved["state"] != "pending" and not saved.get("t_verdict"):
                self.reconcile(saved) if saved.get("observation") else self.agent.refresh(saved["sub"])
        self.assertTrue(self.agent.audit()["ok"])
        held_before = self.agent.store.count("receipt:")
        self.assertGreater(held_before, 0)
        self.lab.stop_role("T")
        t_dir = self.lab.root / "T"
        cfg = load_config(t_dir / "config.json")
        store = Store(t_dir)
        original = store.db.execute("SELECT seq,hash,value FROM journal ORDER BY seq").fetchall()
        records = [json_loads(unseal(blob)) for _, _, blob in original]
        log = TransparencyLog(cfg["log_id"], key_for(cfg), policy_for(cfg), cfg["created_at"])
        rebuilt = [original[0]]
        for saved in records[1:]:
            if saved["statement"]["sub"] == record["sub"]:
                continue
            stmt = SignedStatement.from_dict(saved["statement"])
            rc = log.register(stmt, saved["at"])
            rebuilt.append((rc.leaf_index, stmt.statement_hash,
                            seal(__import__("itx.crypto", fromlist=["canonical_json"]).canonical_json(
                                {"statement": saved["statement"], "at": saved["at"], "receipt": rc.to_dict()}))))
        self.assertLess(len(rebuilt), len(original))
        checkpoint = self.agent.store.get("checkpoint")
        try:
            with store.db:
                store.db.execute("DELETE FROM journal")
                store.db.executemany("INSERT INTO journal VALUES (?,?,?)", rebuilt)
            store.close()
            self.lab.restart_t()
            self.agent.store.put("checkpoint", None)  # 첫 감사처럼: 비교할 이전 체크포인트가 없다
            from itx.runtime.auditing import verify_export
            export = self.agent.audit_export()
            private, versions = self.agent.private_evidence()
            forgetful = verify_export(export, self.agent.trust(), private=private, private_by_hash=versions)
            self.assertTrue(forgetful["ok"], forgetful)  # 영수증을 버린 감사자는 아무것도 보지 못한다
            self.assertEqual(forgetful["receipt_errors"], [])
            self.assertEqual(forgetful["held_receipts"]["scope"], "none")
            report = self.agent.audit()
            self.assertFalse(report["ok"])
            self.assertTrue(report["tree_recomputed_matches_head"] and report["head_signature_valid"])
            self.assertEqual(report["anchors"], [])
            held = report["held_receipts"]
            self.assertGreaterEqual(held["held"], held_before)
            self.assertIn(record["sub"], {m["sub"] for m in held["missing"]})
            # R·M 도 자기 영수증을 보관·제출하므로 그들이 제출한 항목의 누락도 보인다.
            self.assertEqual({m["holder"] for m in held["missing"]}, {"U", "R", "M"})
            self.assertEqual(held["scope"], "all_parties")
            self.assertEqual(held["holders_unreachable"], [])
            self.assertIsNone(self.agent.store.get("checkpoint"))  # 실패한 감사는 체크포인트를 옮기지 않는다
        finally:
            self.lab.stop_role("T")
            store = Store(t_dir)
            with store.db:
                store.db.execute("DELETE FROM journal")
                store.db.executemany("INSERT INTO journal VALUES (?,?,?)", original)
            store.close()
            self.lab.restart_t()
            self.agent.store.put("checkpoint", checkpoint)
        self.assertTrue(self.agent.audit()["ok"])


    def test_15_relay_withholding_is_a_gap_not_a_denial(self):
        """R 이 진술을 내지 않는다. 결손은 위반이 아니므로 protect 는 U+M 증거로 계속하고(S09 의 런타임판),
        strict 도 T 가 gap·passed 로 판정하면 수용한다. R 진술을 필수로 만드는 것은 명시적 정책뿐이다 —
        그 정책이 없으면 R 은 진술 보류만으로 모든 응답을 격리시키는 서비스 거부 스위치를 쥔다."""
        record = self.agent.request("R 진술 보류", "protect", "missing_relay")
        self.assertEqual(record["state"], "accept", record)
        self.assertIsNotNone(record["response"])
        self.assertEqual(record["checks"]["R_authority"]["result"], "not_evaluable")
        self.assertEqual(record["checks"]["route_allowed"]["result"], "pass")  # M 영수증의 model_id 로 판단
        verdict = self.reconcile(record, completeness=("gap",))["t_verdict"]["payload"]
        self.assertEqual(verdict["verification_status"], "passed")
        self.assertEqual(verdict["completeness"], "gap")
        strict = self.agent.request("R 진술 보류 · strict", "strict", "missing_relay")
        self.assertEqual(strict["state"], "accept", strict)
        with patch.dict(self.agent.config, require_relay_statement=True):
            required = self.agent.request("R 진술 필수 정책", "protect", "missing_relay")
        self.assertEqual(required["state"], "quarantine", required)
        self.assertEqual(required["checks"]["R_authority"]["result"], "fail")
        self.reconcile(required, completeness=("gap",))

    def test_16_evidence_backlog_policy_is_explicit(self):
        """큐 포화 시 동작은 버그가 아니라 정책이다. bounded 는 새 요청을 거절하고, unbounded 는 계속 쌓는다.
        어느 쪽도 이미 보관한 증거를 버리지 않는다."""
        with patch.dict(self.agent.config, evidence_backlog_policy="bogus"), self.assertRaises(ValueError):
            self.agent.status()
        self.lab.stop_role("T")
        try:
            first = self.agent.request("T 장애 · 적체 시작", "protect")
            self.assertEqual(first["state"], "accept")
            backlog = len(self.agent.store.pending())
            self.assertGreater(backlog, 0)
            with patch.dict(self.agent.config, queue_capacity=backlog + 4), self.assertRaisesRegex(RuntimeError, "bounded"):
                self.agent.request("T 장애 · 한도 초과", "protect")
            with patch.dict(self.agent.config, queue_capacity=backlog + 4, evidence_backlog_policy="unbounded"):
                more = self.agent.request("T 장애 · unbounded 정책", "protect")
            self.assertEqual(more["state"], "accept", more)
            self.assertGreater(len(self.agent.store.pending()), backlog)
            self.assertEqual(self.agent.status()["evidence_backlog_policy"], "bounded")
        finally:
            self.lab.restart_t()
        self.reconcile(first)
        self.reconcile(more)


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
