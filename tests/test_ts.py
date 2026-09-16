"""투명성 로그 검사: Merkle 증명, 등록 정책, 영수증, 변조 탐지."""
import random
import unittest

from itx.crypto import KeyPair
from itx.statements import ALL_CONTENT_TYPES, CT_CONTRACT, CT_OBSERVATION, CT_RECEIPT, issue
from itx.statements.schemas import observation_payload, policy_payload, receipt_payload
from itx.ts import (
    CheckpointAnchor,
    MerkleTree,
    RegistrationRefused,
    TransparencyLog,
    verify_consistency,
    verify_inclusion,
    verify_receipt,
)
from itx.ts.merkle import leaf_hash, mth


class MerkleTest(unittest.TestCase):
    def test_inclusion_and_consistency_random_sizes(self):
        rnd = random.Random(7)
        for n in range(1, 40):
            t = MerkleTree()
            data = [bytes([rnd.randrange(256)]) * 3 + bytes([i]) for i in range(n)]
            for d in data:
                t.append(d)
            root = t.root()
            for i in range(n):
                self.assertTrue(verify_inclusion(i, n, leaf_hash(data[i]), t.inclusion_proof(i), root), (n, i))
                # 다른 리프로는 실패해야 한다.
                self.assertFalse(verify_inclusion(i, n, leaf_hash(data[i] + b"x"), t.inclusion_proof(i), root))
            for m in range(0, n + 1):
                self.assertTrue(
                    verify_consistency(m, n, t.root_at(m), root, t.consistency_proof(m, n)), (m, n)
                )

    def test_consistency_rejects_rewritten_history(self):
        t = MerkleTree()
        for i in range(10):
            t.append(b"entry-%d" % i)
        old_root, old_size = t.root(), t.size
        for i in range(10, 15):
            t.append(b"entry-%d" % i)
        self.assertTrue(verify_consistency(old_size, t.size, old_root, t.root(), t.consistency_proof(old_size)))
        t.replace_leaf(3, b"rewritten")
        self.assertFalse(verify_consistency(old_size, t.size, old_root, t.root(), t.consistency_proof(old_size)))

    def test_empty_tree_root(self):
        self.assertEqual(mth([]).hex(), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")


def _receipt():
    return receipt_payload(
        cti="c", attempt_id="a1", request_commit="00" * 32, response_commit="11" * 32,
        model_id="model-A", model_version="1", model_hash="22" * 32, eat_nonce=None,
        execution_time_ms=1, pre_exec_check="skipped", decision="served", attestation_doc_hash="33" * 32)


def _make_log(now=0):
    ts_key = KeyPair.from_name("ts-test")
    user = KeyPair.from_name("user-test")
    pol = policy_payload(
        version=1, ts_id="ts-test", ts_iss="urn:itx:party:ts-test",
        allowed_content_types=list(ALL_CONTENT_TYPES),
        sub_pattern=r"^urn:itx:(req|policy):[0-9a-zA-Z:-]+$",
        trusted_keys={user.kid: {"iss": "urn:itx:party:user-test", "public_key": user.public_hex}},
        issuer_content_types={"urn:itx:party:user-test": [CT_CONTRACT, CT_OBSERVATION]},
    )
    return TransparencyLog("ts-test", ts_key, pol, now), ts_key, user


class LogTest(unittest.TestCase):
    def test_policy_is_entry_zero_and_registration_receipt_verifies(self):
        log, ts_key, user = _make_log()
        self.assertEqual(log.entries[0].statement.content_type, "application/vnd.itx.policy+json")
        stmt = issue(
            user, iss="urn:itx:party:user-test", sub="urn:itx:req:abc", content_type=CT_OBSERVATION,
            payload=observation_payload(attempt_id="a1", resp_commit="00" * 32, received_at=5,
                                        inline_receipt_hash=None, inline_relay_hash=None),
            issued_at=5,
        )
        rc = log.register(stmt, registered_at=20)
        self.assertEqual(rc.leaf_index, 1)
        ok, reason = verify_receipt(rc, stmt, ts_key.public_key)
        self.assertTrue(ok, reason)
        # 등록 후 진술이 바뀌면 영수증이 맞지 않는다.
        stmt.payload["received_at"] = 6
        ok, reason = verify_receipt(rc, stmt, ts_key.public_key)
        self.assertFalse(ok)

    def test_registration_policy_refuses_bad_statements(self):
        log, _ts_key, user = _make_log()
        stranger = KeyPair.from_name("stranger")
        good_payload = observation_payload(attempt_id="a1", resp_commit="00" * 32, received_at=5,
                                           inline_receipt_hash=None, inline_relay_hash=None)
        with self.assertRaises(RegistrationRefused):
            log.register(issue(stranger, iss="urn:itx:party:stranger", sub="urn:itx:req:x",
                               content_type=CT_OBSERVATION, payload=good_payload, issued_at=1), 1)
        with self.assertRaises(RegistrationRefused):  # 잘못된 sub
            log.register(issue(user, iss="urn:itx:party:user-test", sub="bad",
                               content_type=CT_OBSERVATION, payload=good_payload, issued_at=1), 1)
        with self.assertRaises(RegistrationRefused):  # iss 와 kid 불일치
            log.register(issue(user, iss="urn:itx:party:someone-else", sub="urn:itx:req:x",
                               content_type=CT_OBSERVATION, payload=good_payload, issued_at=1), 1)
        with self.assertRaises(RegistrationRefused):  # 스키마 위반
            log.register(issue(user, iss="urn:itx:party:user-test", sub="urn:itx:req:x",
                               content_type=CT_CONTRACT, payload={"profile": "x"}, issued_at=1), 1)
        # 키는 신뢰 목록에 있지만 그 역할이 낼 수 없는 유형의 진술.
        with self.assertRaises(RegistrationRefused) as cm:
            log.register(issue(user, iss="urn:itx:party:user-test", sub="urn:itx:req:x",
                               content_type=CT_RECEIPT, payload=_receipt(), issued_at=1), 1)
        self.assertTrue(any("may not issue" in r for r in cm.exception.reasons), cm.exception.reasons)

    def test_anchor_detects_history_rewrite(self):
        log, _ts_key, user = _make_log()
        stmts = []
        for i in range(5):
            s = issue(user, iss="urn:itx:party:user-test", sub=f"urn:itx:req:{i}", content_type=CT_OBSERVATION,
                      payload=observation_payload(attempt_id=f"a{i}", resp_commit="11" * 32, received_at=i,
                                                  inline_receipt_hash=None, inline_relay_hash=None), issued_at=i)
            log.register(s, i)
            stmts.append(s)
        anchor = CheckpointAnchor()
        anchor.anchor(log.tree_head(100), 100)
        for i in range(5, 8):
            log.register(issue(user, iss="urn:itx:party:user-test", sub=f"urn:itx:req:{i}", content_type=CT_OBSERVATION,
                               payload=observation_payload(attempt_id=f"a{i}", resp_commit="11" * 32, received_at=i,
                                                           inline_receipt_hash=None, inline_relay_hash=None), issued_at=i), i)
        self.assertTrue(all(r["root_matches"] and r["consistent_with_head"] for r in anchor.verify_log(log)))
        forged = issue(user, iss="urn:itx:party:user-test", sub="urn:itx:req:2", content_type=CT_OBSERVATION,
                       payload=observation_payload(attempt_id="a2", resp_commit="22" * 32, received_at=2,
                                                   inline_receipt_hash=None, inline_relay_hash=None), issued_at=2)
        log.tamper_entry(3, forged)
        res = anchor.verify_log(log)
        self.assertFalse(res[0]["root_matches"])
        self.assertFalse(res[0]["consistent_with_head"])


if __name__ == "__main__":
    unittest.main()
