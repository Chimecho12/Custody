"""독립 재실행 검사: 감사자는 T 의 코드도, T 가 로그에 넣은 판정도 그대로 믿지 않는다.

트리·헤드·앵커가 모두 자기 일관적인 로그를 만들어 놓고(= 로그를 쥔 쪽이 할 수 있는 일),
판정 쪽만 손댔을 때 재실행이 그것을 드러내는지 본다.
"""
import copy
import unittest

from itx import CHECKER_VERSION
from itx.audit import replay_audit
from itx.crypto import canonical_json
from itx.sim.model import DEFAULT_MODELS, reference_hashes
from itx.sim.runner import _keys, run_scenario
from itx.sim.scenarios import scenario_by_id
from itx.statements import CT_VERDICT, SignedStatement
from itx.ts import CheckpointAnchor, MerkleTree

SEED = 42
REF = reference_hashes(DEFAULT_MODELS)


def _base_run():
    return run_scenario(scenario_by_id("S01"), "protect", seed=SEED)


def _base_export():
    return _base_run()["log_export"]


def _reseal(export):
    """로그를 쥔 쪽이 트리를 다시 계산하고 헤드를 다시 서명하고 다시 앵커한다.
    즉 트리·헤드 서명·체크포인트는 전부 맞는 상태로 만들어 둔다."""
    ts_key = _keys(SEED)["T"]
    tree = MerkleTree()
    for e in export["entries"]:
        tree.append(SignedStatement.from_dict(e["statement"]).leaf_bytes())
    head = {"log_id": export["log_id"], "tree_size": tree.size, "root_hash": tree.root().hex(),
            "time": export["head"]["time"], "ts_kid": export["ts_kid"]}
    head["signature"] = ts_key.sign(canonical_json(head)).hex()
    export["head"] = head
    anchor = CheckpointAnchor()
    anchor.anchor(head, head["time"])
    return export, anchor.records


def _verdicts(export):
    return [e for e in export["entries"] if e["statement"]["content_type"] == CT_VERDICT]


def _audit(export, anchors):
    return replay_audit(export, anchors, {}, {}, REF)


class ResealedBaselineTest(unittest.TestCase):
    def test_untouched_log_replays_clean(self):
        r = _audit(*_reseal(copy.deepcopy(_base_export())))
        self.assertTrue(r["ok"], r["verdict_mismatches"])
        self.assertEqual(r["unauthenticated_verdicts"], [])
        self.assertEqual(r["auditor_checker_version"], CHECKER_VERSION)


class VerdictAuthenticityTest(unittest.TestCase):
    def test_unsigned_verdict_is_not_read_as_a_verdict(self):
        export = copy.deepcopy(_base_export())
        touched = _verdicts(export)
        self.assertTrue(touched)
        for e in touched:
            e["statement"]["signature"] = "00" * 64
        r = _audit(*_reseal(export))
        self.assertFalse(r["ok"])
        self.assertEqual(len(r["unauthenticated_verdicts"]), len(touched))
        self.assertIn("서명", r["unauthenticated_verdicts"][0]["problem"])

    def test_verdict_signed_by_another_party_is_rejected(self):
        export = copy.deepcopy(_base_export())
        rk = _keys(SEED)["R"]
        for e in _verdicts(export):
            stmt = SignedStatement.from_dict(e["statement"])
            stmt.iss, stmt.kid = "urn:itx:party:relay", rk.kid
            stmt.signature = rk.sign(stmt.to_be_signed()).hex()
            e["statement"] = stmt.to_dict()
        r = _audit(*_reseal(export))
        self.assertFalse(r["ok"])
        self.assertTrue(r["unauthenticated_verdicts"])
        self.assertEqual(r["unauthenticated_verdicts"][0]["iss"], "urn:itx:party:relay")


class VerdictSnapshotTest(unittest.TestCase):
    def test_later_relay_statement_does_not_rewrite_past_verdict(self):
        from itx.statements import CT_RELAY
        export = copy.deepcopy(_base_export())
        relay = copy.deepcopy(next(e for e in export["entries"] if e["statement"]["content_type"] == CT_RELAY))
        stmt = SignedStatement.from_dict(relay["statement"])
        stmt.payload["resp_out_commit"] = "00" * 32
        stmt.signature = _keys(SEED)["R"].sign(stmt.to_be_signed()).hex()
        relay.update(index=len(export["entries"]), statement=stmt.to_dict())
        export["entries"].append(relay)
        report = _audit(*_reseal(export))
        self.assertTrue(report["ok"], report["verdict_mismatches"])
        self.assertEqual(report["verdicts_checked"][0]["evidence_after_verdict"], 1)


class HeldReceiptInclusionTest(unittest.TestCase):
    """로그를 쥔 쪽이 항목을 빼고 트리·헤드·앵커를 전부 다시 맞춰 놓은 경우.
    로그 안의 어떤 검사도 이를 보지 못한다. 제출자가 보관한 영수증만 본다."""

    def _omit_request(self):
        run = _base_run()
        export = copy.deepcopy(run["log_export"])
        sub = run["attempts"][0]["sub"]
        kept = [e for e in export["entries"] if e["statement"]["sub"] != sub]
        export["entries"] = [dict(e, index=i) for i, e in enumerate(kept)]
        return _reseal(export), run["held_receipts"], sub

    def test_forgetful_auditor_passes_the_omitted_log(self):
        (export, anchors), _, _ = self._omit_request()
        r = _audit(export, anchors)
        self.assertTrue(r["ok"])
        self.assertEqual(r["subs_checked"], 0)
        self.assertEqual(r["held_receipts"]["scope"], "none")

    def test_held_receipts_reveal_the_omission(self):
        (export, anchors), receipts, sub = self._omit_request()
        r = replay_audit(export, anchors, {}, {}, REF, held_receipts=receipts)
        self.assertFalse(r["ok"])
        self.assertTrue(r["tree_recomputed_matches_head"] and r["head_signature_valid"])
        self.assertTrue(all(a["ok"] for a in r["anchors"]))
        missing = r["held_receipts"]["missing"]
        self.assertTrue(missing)
        self.assertIn(sub, {m["sub"] for m in missing})
        self.assertTrue(any("found_at" in m for m in missing))  # 매니페스트는 남았지만 자리가 바뀌었다

    def test_forged_receipt_is_unverifiable_not_missing(self):
        (export, anchors), receipts, _ = self._omit_request()
        forged = copy.deepcopy(receipts[:1])
        forged[0]["receipt"]["signature"] = "00" * 64
        r = replay_audit(export, anchors, {}, {}, REF, held_receipts=forged)
        self.assertEqual(r["held_receipts"]["missing"], [])
        self.assertEqual(len(r["held_receipts"]["unverifiable"]), 1)
        self.assertTrue(r["held_receipts"]["ok"])  # 검증 불가한 영수증은 누락의 증거가 아니다

    def test_untouched_log_includes_every_held_receipt(self):
        run = _base_run()
        r = replay_audit(run["log_export"], [], {}, {}, REF, held_receipts=run["held_receipts"])
        self.assertEqual(r["held_receipts"]["included"], len(run["held_receipts"]))
        self.assertTrue(r["held_receipts"]["ok"])


class VerdictProvenanceTest(unittest.TestCase):
    """결론이 같아도 다른 정책·다른 검사기·다른 증거로 얻은 결론이면 재현이 아니다."""

    def _rewrite(self, **fields):
        export = copy.deepcopy(_base_export())
        ts_key = _keys(SEED)["T"]
        for e in _verdicts(export):
            stmt = SignedStatement.from_dict(e["statement"])
            stmt.payload.update(fields)
            stmt.signature = ts_key.sign(stmt.to_be_signed()).hex()  # 제대로 서명된 판정
            e["statement"] = stmt.to_dict()
        return _audit(*_reseal(export))

    def test_wrong_policy_hash_is_a_mismatch(self):
        r = self._rewrite(policy_hash="de" * 32)
        self.assertFalse(r["ok"])
        self.assertEqual(len(r["verdict_mismatches"]), 1)
        self.assertEqual(r["unauthenticated_verdicts"], [])  # 서명은 멀쩡하다

    def test_wrong_checker_version_is_a_mismatch(self):
        r = self._rewrite(checker_version="itx-reconcile/9.9.9-unreleased")
        self.assertFalse(r["ok"])
        self.assertEqual(len(r["verdict_mismatches"]), 1)

    def test_cleared_evidence_refs_is_a_mismatch(self):
        r = self._rewrite(evidence_refs=[])
        self.assertFalse(r["ok"])
        self.assertEqual(len(r["verdict_mismatches"]), 1)


if __name__ == "__main__":
    unittest.main()
