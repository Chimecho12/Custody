import copy
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from itx.crypto import HAS_CRYPTOGRAPHY, canonical_json
from itx.runtime.agent import Agent
from itx.runtime.common import load_config, key_for, Store
from itx.runtime.auditing import fingerprint, verify_export, trust_from_config
from itx.runtime import enrollment
from itx.runtime.packages import (read_document, write_document, create_recipient, build_package,
                                  encrypt_package, verify_package)


def ports(count):
    sockets = [socket.socket() for _ in range(count)]
    try:
        for s in sockets:
            s.bind(("127.0.0.1", 0))
        return [s.getsockname()[1] for s in sockets]
    finally:
        for s in sockets:
            s.close()


def provision(root, previous=None, old_configs=None, checkpoint=None, pre_exec=False):
    addresses = dict(zip("RMTW", ports(4)))
    directories, cards = {}, []
    for role in "URMTW":
        directories[role] = root / role
        result = enrollment.prepare_operator(directories[role], role,
            f"https://127.0.0.1:{addresses[role]}" if role != "U" else None)
        cards.append(read_document(result["card"]))
    proposal = enrollment.propose(cards, previous=previous, checkpoint=checkpoint, pre_exec=pre_exec)
    digest = fingerprint(proposal)
    endorsements = [enrollment.endorse(directories[r], proposal, digest, old_configs[r] if previous else None) for r in directories]
    bundle = enrollment.assemble(proposal, endorsements, previous)
    configs = {r: enrollment.activate(directories[r], bundle, digest, previous_config=old_configs[r] if previous else None)["config_path"] for r in directories}
    return directories, bundle, configs


class Processes:
    def __init__(self, configs):
        self.children = []
        try:
            for role in "TMRW":
                path = Path(configs[role])
                errors = open(path.parent / "test.stderr.log", "ab")
                child = subprocess.Popen([sys.executable, "-B", "-m", "itx.runtime.service", "--config", str(path), "--parent-pipe"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                    env=dict(os.environ, PYTHONUTF8="1"), creationflags=0x08000000 if os.name == "nt" else 0)
                errors.close()
                self.children.append(child)
                ready = queue.Queue()
                threading.Thread(target=lambda c=child, q=ready: q.put(c.stdout.readline()), daemon=True).start()
                line = ready.get(timeout=25)
                if not line or not json.loads(line).get("ready"):
                    raise RuntimeError((path.parent / "test.stderr.log").read_text())
        except Exception:
            self.close()
            raise

    def close(self):
        for child in self.children:
            child.stdin.close()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
            child.stdout.close()
        self.children = []


@unittest.skipUnless(HAS_CRYPTOGRAPHY, "network runtime requires cryptography")
class ExtensionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="itx-extensions-")
        cls.root = Path(cls.temp.name)
        cls.operators, cls.bundle, cls.configs = provision(cls.root / "first")
        cls.services = Processes(cls.configs)
        cls.agent = Agent(cls.configs["U"])

    @classmethod
    def tearDownClass(cls):
        cls.agent.close()
        cls.services.close()
        cls.temp.cleanup()

    def test_01_independent_keys_tls_and_strict(self):
        status = self.agent.preflight()
        self.assertTrue(status["ok"], status)
        self.assertEqual(set(status["services"]), set("RMTW"))
        record = self.agent.request("independent provisioning", "strict")
        self.assertEqual(record["state"], "accept", record)
        self.assertEqual(len(set(p.pid for p in self.services.children)), 4)
        self.assertEqual(len(set(self.agent.config["ca_files"].values())), 4)

    def test_02_package_public_and_recipient_encrypted(self):
        trust = self.agent.trust()
        public = build_package(self.agent)
        report = verify_package(public, trust, fingerprint(trust))
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["private_scope"], "partial")
        self.assertEqual(report["deployment_epochs_verified"], 1)
        self.assertEqual(public["body"]["private_by_sub"], {})
        recipient = create_recipient(self.root / "auditor")
        full = build_package(self.agent, True)
        encrypted = encrypt_package(full, read_document(recipient["path"]), recipient["fingerprint"])
        self.assertNotIn("salt", canonical_json(encrypted).decode())
        report = verify_package(encrypted, trust, fingerprint(trust), self.root / "auditor")
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["private_scope"], "complete")
        bad = copy.deepcopy(public)
        bad["body"]["created_at"] += 1
        with self.assertRaises(ValueError):
            verify_package(bad, trust, fingerprint(trust))
        with self.assertRaises(ValueError):
            verify_package(public, trust, "00" * 32)
        bad = copy.deepcopy(public)
        bad["body"]["deployment_bundle"]["endorsements"].pop()
        bad["u_signature"] = self.agent.key.sign(canonical_json(bad["body"])).hex()
        with self.assertRaises(ValueError):
            verify_package(bad, trust, fingerprint(trust))
        wrong = create_recipient(self.root / "wrong-auditor")
        with self.assertRaises(ValueError):
            verify_package(encrypted, trust, fingerprint(trust), self.root / "wrong-auditor")
        bad = copy.deepcopy(encrypted)
        bad["nonce"] = "00" * 12
        with self.assertRaises(Exception):
            verify_package(bad, trust, fingerprint(trust), self.root / "auditor")

    def test_03_witness_rejects_fork_and_survives_new_checkpoint(self):
        first = self.agent.witness()
        before = first["receipt"]["body"]["head"]
        bad_head = dict(before, root_hash="11" * 32)
        t = key_for(load_config(self.configs["T"]))
        bad_head["signature"] = t.sign(canonical_json({k:v for k,v in bad_head.items() if k != "signature"})).hex()
        with self.assertRaises(RuntimeError):
            self.agent.peer.call("W", "witness", {"head": bad_head})
        self.assertEqual(self.agent.request("witness extension", "strict")["state"], "accept")
        second = self.agent.witness()
        self.assertEqual(second["receipt"]["body"]["previous_receipt_hash"], fingerprint(first["receipt"]))
        package = build_package(self.agent, True)
        report = verify_package(package, self.agent.trust(), fingerprint(self.agent.trust()))
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["witness_receipts_checked"], 2)

    def test_04_paginated_snapshot_and_registration_timestamps(self):
        for i in range(13):
            self.assertEqual(self.agent.request(f"page {i}", "strict")["state"], "accept")
        metadata = self.agent.peer.call("T", "audit_head", {})
        self.assertGreater(metadata["head"]["tree_size"], 64)
        self.agent.request("after snapshot", "strict")
        entries = []
        while len(entries) < metadata["head"]["tree_size"]:
            page = self.agent.peer.call("T", "audit_page", {"head": metadata["head"], "start": len(entries), "limit": 7})
            self.assertLessEqual(len(page["entries"]), 7)
            entries.extend(page["entries"])
        export = {**metadata, "entries": entries}
        private, versions = self.agent.private_evidence()
        report = verify_export(export, self.agent.trust(), private=private, private_by_hash=versions)
        self.assertTrue(report["ok"], report)
        export["entries"][1]["registered_at"] += 1
        self.assertFalse(verify_export(export, self.agent.trust(), private=private, private_by_hash=versions)["ok"])

    def test_05_operator_ca_is_scoped_to_each_endpoint(self):
        from itx.runtime.transport import Peer
        bad = copy.deepcopy(self.agent.config)
        bad["ca_files"]["M"] = bad["ca_files"]["R"]
        peer = Peer(bad, self.agent.key)
        with self.assertRaises(Exception):
            peer.call("M", "health", {"challenge": "wrong-ca"})

    def test_06_enrollment_rejects_missing_or_modified_approvals(self):
        bad = copy.deepcopy(self.bundle)
        bad["endorsements"].pop()
        with self.assertRaises(ValueError):
            enrollment.verify_deployment(bad)
        bad = copy.deepcopy(self.bundle)
        bad["proposal"]["model_hash"] = "00" * 32
        with self.assertRaises(ValueError):
            enrollment.verify_deployment(bad)
        with self.assertRaises(ValueError):
            enrollment.endorse(self.operators["U"], self.bundle["proposal"], "ff" * 32)
        cfg = read_document(self.configs["U"])
        cfg["endpoints"]["T"] = "https://127.0.0.1:1"
        path = Path(self.configs["U"]).parent / "tampered-config.json"
        write_document(path, cfg)
        with self.assertRaises(ValueError):
            load_config(path)

    def test_07_previewed_retention_keeps_signed_evidence(self):
        from itx.runtime import retention
        from itx.runtime.common import now_ms
        record = self.agent.request("retention source", "strict")
        key = "request:" + record["sub"]
        saved = self.agent.store.get(key)
        saved["started_at"] = now_ms() - 40 * 86400000
        self.agent.store.put(key, saved)
        deadline = time.monotonic() + 8
        while self.agent.store.pending() and time.monotonic() < deadline:
            self.agent.flush()
            time.sleep(.1)
        self.assertFalse(self.agent.store.pending(), "evidence did not flush")
        plan = retention.preview(self.agent)
        self.assertEqual(plan["count"], 1)
        with self.assertRaises(ValueError):
            retention.apply(self.agent, "bad-token")
        result = retention.apply(self.agent, plan["token"])
        self.assertEqual(result["pruned_records"], 1)
        pruned = self.agent.store.get(key)
        self.assertIn("contract", pruned)
        self.assertEqual(pruned["gate"], saved["gate"])
        self.assertNotIn("private", pruned)
        self.assertNotIn("quarantined_body", pruned)
        self.assertIsNone(pruned["response"])
        self.assertEqual(self.agent.audit()["private_scope"], "partial")

    def test_99_rotation_preserves_history_and_retires_old_epoch(self):
        checkpoint = self.agent.peer.call("T", "audit_head", {})["head"]
        operators, bundle, configs = provision(self.root / "second", self.bundle, self.configs, checkpoint)
        bad = copy.deepcopy(bundle)
        bad["endorsements"][0]["previous_signature"] = None
        with self.assertRaises(ValueError):
            enrollment.verify_deployment(bad)
        with self.assertRaisesRegex(ValueError, "폐기"):
            self.agent.request("old epoch", "protect")
        self.assertFalse(self.agent.preflight()["ok"])
        servers = Processes(configs)
        agent = Agent(configs["U"])
        try:
            self.assertTrue(agent.preflight()["ok"])
            self.assertEqual(agent.config["epoch"], 2)
            self.assertEqual(len(agent.config["deployment_history"]), 2)
            self.assertEqual(agent.config["deployment_history"][0]["previous_checkpoint"], checkpoint)
            self.assertEqual(agent.request("rotated keys", "strict")["state"], "accept")
            self.assertTrue(agent.audit()["ok"])
            package = build_package(agent, True)
            report = verify_package(package, agent.trust(), fingerprint(agent.trust()))
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["deployment_epochs_verified"], 2)
            self.assertIsNotNone(agent.witness()["receipt"])
        finally:
            agent.close()
            servers.close()


class HistoricalVerdictTest(unittest.TestCase):
    def test_wrong_early_verdict_is_not_hidden_by_correct_later_verdict(self):
        from test_audit import _base_export, _reseal, _audit, _verdicts, _keys, SEED
        from itx.statements import SignedStatement
        export = copy.deepcopy(_base_export())
        first = _verdicts(export)[0]
        correct = copy.deepcopy(first)
        stmt = SignedStatement.from_dict(first["statement"])
        stmt.payload["checker_version"] = "wrong-checker"
        stmt.signature = _keys(SEED)["T"].sign(stmt.to_be_signed()).hex()
        first["statement"] = stmt.to_dict()
        correct["index"] = len(export["entries"])
        export["entries"].append(correct)
        report = _audit(*_reseal(export))
        self.assertFalse(report["ok"])
        records = report["verdicts_checked"][0]["historical_verdicts"]
        self.assertFalse(records[0]["match"])
        self.assertTrue(records[-1]["match"])
