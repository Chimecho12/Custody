"""키 보관·노출 모델과 외부 서명자.

`CommandSigner` 는 실제로 다른 프로세스를 띄워서 검사한다. 모의 객체로 대신하면
「사설키가 이 프로세스에 없다」는 성질 자체가 검사되지 않는다.
"""
from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import ClassVar

from itx.crypto import KeyPair
from itx.keys import (
    SENDS_DIGEST,
    SENDS_MESSAGE,
    CommandSigner,
    Custody,
    LocalKeySigner,
    SignerError,
    build,
    custody_from_config,
    signing_chain,
    summarise,
)

#: 외부 서명자 대역. 시드를 자기 안에 갖고 있고, itx 프로세스는 그 시드를 본 적이 없다.
HELPER = textwrap.dedent("""
    import sys
    sys.path.insert(0, %(root)r)
    from itx.crypto import KeyPair
    key = KeyPair.from_seed(%(kid)r, bytes.fromhex(%(seed)r))
    payload = bytes.fromhex(sys.stdin.read().strip())
    sys.stdout.write(key.sign(payload).hex())
""")


def _helper(tmp: Path, kid: str, seed: bytes, *, broken: str = "") -> list[str]:
    root = str(Path(__file__).resolve().parents[1])
    source = HELPER % {"root": root, "kid": kid, "seed": seed.hex()}
    if broken == "garbage":
        source = "import sys\nsys.stdout.write('not-hex')\n"
    elif broken == "exit":
        source = "import sys\nsys.stderr.write('kms unavailable')\nsys.exit(3)\n"
    elif broken == "short":
        source = "import sys\nsys.stdout.write('00' * 32)\n"
    path = tmp / f"signer-{broken or 'ok'}.py"
    path.write_text(source, encoding="utf-8")
    return [sys.executable, "-B", str(path)]


class CustodyModel(unittest.TestCase):
    def test_exposure_follows_the_store_kind(self):
        for kind, exposed in (("file", True), ("dpapi", True), ("kms", False), ("hsm", False)):
            with self.subTest(kind):
                custody = Custody(role="T", kid="t-1", purpose="p", store_kind=kind)
                self.assertEqual(custody.exposed, exposed)

    def test_unknown_store_kind_is_refused(self):
        with self.assertRaises(ValueError):
            Custody(role="T", kid="t-1", purpose="p", store_kind="magic")

    def test_rotation_overdue_is_a_warning_not_a_verdict(self):
        custody = Custody(role="R", kid="r-1", purpose="p", store_kind="kms",
                          rotation_days=118, rotation_max=90)
        self.assertEqual(custody.overdue_days, 28)
        # 기한을 넘겨도 노출 여부는 그대로다. 둘은 다른 축이다.
        self.assertFalse(custody.exposed)

    def test_boundary_note_states_the_consequence(self):
        weak = Custody(role="T", kid="t-1", purpose="p", store_kind="file").boundary_note()
        strong = Custody(role="M", kid="m-1", purpose="p", store_kind="hsm").boundary_note()
        self.assertIn("위조가 가능", weak)
        self.assertIn("위조는 불가능", strong)

    def test_summary_counts_exposure_not_safety(self):
        entries = [Custody(role=r, kid=f"{r}-1", purpose="p", store_kind=k, rotation_days=d)
                   for r, k, d in (("U", "hsm", 41), ("R", "kms", 118), ("T", "file", 135))]
        self.assertEqual(summarise(entries),
                         {"total": 3, "sealed": 2, "exposed": 1, "overdue": 2})


class ExternalSigner(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="itx-signer-"))
        self.key = KeyPair.from_name("m-remote", namespace="itx-keys-test")
        self.custody = Custody(role="M", kid=self.key.kid, purpose="영수증 서명",
                               store_kind="kms", store_detail="테스트 어댑터")

    def _signer(self, **kwargs) -> CommandSigner:
        return CommandSigner(kid=self.key.kid, public_key=self.key.public_key,
                             command=_helper(self.tmp, self.key.kid, self.key.seed,
                                             broken=kwargs.pop("broken", "")),
                             custody=self.custody, **kwargs)

    def test_external_process_produces_a_verifiable_signature(self):
        signer = self._signer()
        message = b"itx statement bytes"
        signature = signer.sign(message)
        from itx.crypto import verify
        self.assertTrue(verify(self.key.public_key, message, signature))

    def test_round_trip_latency_is_measured_not_assumed(self):
        signer = self._signer()
        signer.sign(b"x")
        self.assertGreater(self.custody.round_trip_ms, 0, "실측 왕복 지연이 기록되어야 한다")
        self.assertEqual(self.custody.sign_count, 1)

    def test_digest_form_sends_only_the_hash(self):
        """payload_form 이 화면에 그대로 나가므로, 실제로 무엇을 보내는지와 같아야 한다."""
        from itx.crypto import sha256

        signer = self._signer(payload_form=SENDS_DIGEST, verify_after_sign=False)
        message = b"a much longer statement body than the digest"
        self.assertEqual(signer._outbound(message), sha256(message))
        self.assertEqual(len(signer._outbound(message)), 32)
        # 순수 Ed25519 는 메시지 전체에 서명하므로, digest 형태의 서명은 메시지로 검증되지 않는다.
        signature = signer.sign(message)
        from itx.crypto import verify
        self.assertFalse(verify(self.key.public_key, message, signature))
        self.assertTrue(verify(self.key.public_key, sha256(message), signature))

    def test_message_form_is_the_default_for_pure_ed25519(self):
        signer = self._signer()
        self.assertEqual(signer.payload_form, SENDS_MESSAGE)
        self.assertEqual(signer._outbound(b"abc"), b"abc")

    def test_a_wrong_signature_from_the_adapter_is_caught_here(self):
        other = KeyPair.from_name("impostor", namespace="itx-keys-test")
        signer = CommandSigner(kid=self.key.kid, public_key=self.key.public_key,
                               command=_helper(self.tmp, other.kid, other.seed),
                               custody=self.custody)
        with self.assertRaises(SignerError):
            signer.sign(b"x")

    def test_adapter_failures_are_reported_not_swallowed(self):
        for broken in ("exit", "garbage", "short"):
            with self.subTest(broken), self.assertRaises(SignerError):
                self._signer(broken=broken).sign(b"x")

    def test_missing_command_is_reported(self):
        signer = CommandSigner(kid=self.key.kid, public_key=self.key.public_key,
                               command=["itx-no-such-signer-binary"], custody=self.custody)
        with self.assertRaises(SignerError):
            signer.sign(b"x")

    def test_probe_reports_without_raising(self):
        self.assertTrue(self._signer().probe()["ok"])
        self.assertFalse(self._signer(broken="exit").probe()["ok"])

    def test_signing_chain_marks_the_boundary_step(self):
        remote = signing_chain(self._signer())
        local = signing_chain(LocalKeySigner(self.key, Custody(
            role="T", kid=self.key.kid, purpose="p", store_kind="file")))
        self.assertEqual([s["inside"] for s in remote], [False, False, True, False])
        self.assertIn("반출 없음", remote[2]["sub"])
        self.assertIn("평문", local[2]["sub"])


class InventoryView(unittest.TestCase):
    CONFIG: ClassVar[dict] = {
        "role": "U", "log_id": "ts-1",
        "identities": {r: {"kid": f"{r.lower()}-key-01", "public_key": "00" * 32}
                       for r in "URMTW"},
        "key_custody": {
            "U": {"store_kind": "hsm", "store_detail": "YubiKey 5 · PIV 9c", "rotation_days": 41},
            "R": {"store_kind": "kms", "store_detail": "AWS KMS", "rotation_days": 118},
            "M": {"store_kind": "kms", "store_detail": "GCP Cloud KMS · HSM", "rotation_days": 22},
        },
    }

    def test_undeclared_keys_are_treated_as_local_files(self):
        """모르는 보관처를 안전하다고 적지 않는다."""
        custody = custody_from_config(self.CONFIG, "T")
        self.assertTrue(custody.exposed)
        self.assertIn(custody.store_kind, ("file", "dpapi"))

    def test_witness_is_not_independent_by_default(self):
        self.assertFalse(custody_from_config(self.CONFIG, "W").independent)

    def test_build_is_json_serialisable_for_the_screen(self):
        view = build(self.CONFIG)
        json.dumps(view, ensure_ascii=False)  # 화면으로 그대로 나가므로 직렬화되어야 한다
        # 회전 기록이 없는 T·W 는 기한 초과로 세지 않는다 — 모르는 것을 위반으로 적지 않는다.
        self.assertEqual(view["summary"], {"total": 5, "sealed": 3, "exposed": 2, "overdue": 1})
        self.assertEqual(len(view["keys"]), 5)
        self.assertTrue(all(len(k["chain"]) == 4 for k in view["keys"]))

    def test_overdue_rotation_appears_in_the_lineage(self):
        events = {e["kind"] for e in custody_from_config(self.CONFIG, "R").to_dict()["lineage"]}
        self.assertIn("overdue", events)

    def test_absent_anchors_stay_in_the_list(self):
        """결손을 지우면 화면이 「표준 대비 어디까지 왔는가」를 말하지 못한다."""
        tones = {a["title"]: a["tone"] for a in build(self.CONFIG)["anchors"]}
        self.assertEqual(tones["상위 CA · 인증 체인"], "absent")
        self.assertEqual(tones["독립 목격자"], "absent")


if __name__ == "__main__":
    unittest.main()
