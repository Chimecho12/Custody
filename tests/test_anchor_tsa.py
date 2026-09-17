"""실제 OpenSSL TSA 서명을 사용한다. 공개 TSA나 외부 네트워크에 접속하지 않는다."""
import copy
from email.message import Message
import hashlib
from http.client import IncompleteRead
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from itx.audit import replay_audit
from itx.audit.anchor_tsa import (
    DEFAULT_TSA_URL, MAX_RESPONSE_BYTES, TSAAnchor, TSAError,
    build_timestamp_request, request_timestamp, verify_timestamp_response, verify_tsa_anchor,
)
from itx.sim.model import reference_hashes
from itx.sim.runner import run_scenario
from itx.sim.scenarios import scenario_by_id


ROOT = "ab" * 32
NONCE = 0x80FF
OPENSSL = shutil.which("openssl")


class TimestampRequestTest(unittest.TestCase):
    def test_sha256_request_matches_der_vector_without_double_hashing(self):
        # INTEGER 0x80ff 앞에 00을 붙여 음수가 되지 않게 하고 certReq=TRUE를 요청한다.
        expected = bytes.fromhex(
            "303e0201013031300d060960864801650304020105000420"
            + ROOT + "02030080ff0101ff")
        self.assertEqual(build_timestamp_request(ROOT, NONCE), expected)

    def test_random_nonce_is_included_by_default(self):
        with patch("itx.audit.anchor_tsa.secrets.randbits", return_value=NONCE):
            self.assertEqual(build_timestamp_request(ROOT), build_timestamp_request(ROOT, NONCE))

    def test_invalid_root_or_nonce_is_rejected(self):
        for root in (None, "", "ab" * 31, "ab" * 33, "zz" * 32, " " * 64):
            with self.subTest(root=root), self.assertRaises(TSAError):
                build_timestamp_request(root, NONCE)
        for nonce in (-1, 0, True, "1", 1.0, 2**160):
            with self.subTest(nonce=nonce), self.assertRaises(TSAError):
                build_timestamp_request(ROOT, nonce)

    def test_bad_der_denied_and_modified_grants_are_rejected_before_openssl(self):
        cases = (b"", b"\x30\x80\x00\x00", b"\x30\x82\x00\x01\x00",
                 b"\x30\x7f", bytes.fromhex("30053003020102"),
                 bytes.fromhex("30053003020101"), b"\x30\x2c\x30\x2a\x02\x28" + b"\x01" * 40,
                 b"x" * (MAX_RESPONSE_BYTES + 1))
        with patch("itx.audit.anchor_tsa.subprocess.run") as run:
            for response in cases:
                with self.subTest(response=response[:20]), self.assertRaises(TSAError):
                    verify_timestamp_response(response, ROOT, ca_file="unused.pem")
            run.assert_not_called()


class _Reply(io.BytesIO):
    def __init__(self, data, content_type="application/timestamp-reply", status=200):
        super().__init__(data)
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type


@unittest.skipUnless(OPENSSL, "RFC 3161 signature fixtures require OpenSSL")
class TSAAnchorTest(unittest.TestCase):
    @classmethod
    def command(cls, *args):
        result = subprocess.run([OPENSSL, *map(str, args)], cwd=cls.work,
                                stdin=subprocess.DEVNULL, capture_output=True, timeout=20,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise AssertionError(result.stderr.decode("utf-8", errors="replace"))
        return result.stdout

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="itx-test-tsa-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.work = Path(cls.temp.name)
        cls.ca = cls.work / "ca.pem"
        for name in ("ca", "untrusted"):
            cls.command("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256",
                        "-days", "2", "-subj", f"/CN=ITX Test {name}",
                        "-keyout", f"{name}.key", "-out", f"{name}.pem",
                        "-addext", "basicConstraints=critical,CA:TRUE",
                        "-addext", "keyUsage=critical,keyCertSign,cRLSign")
        cls.command("req", "-new", "-newkey", "rsa:2048", "-nodes",
                    "-subj", "/CN=ITX Test TSA", "-keyout", "tsa.key", "-out", "tsa.csr")
        (cls.work / "tsa.ext").write_text(
            "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n"
            "extendedKeyUsage=critical,timeStamping\nsubjectKeyIdentifier=hash\n"
            "authorityKeyIdentifier=keyid,issuer\n", encoding="ascii")
        cls.command("x509", "-req", "-in", "tsa.csr", "-CA", "ca.pem", "-CAkey", "ca.key",
                    "-set_serial", "2", "-days", "2", "-sha256", "-extfile", "tsa.ext", "-out", "tsa.pem")
        (cls.work / "serial").write_text("01\n", encoding="ascii")
        cls.config = cls.work / "tsa.cnf"
        # 절대 경로를 사용해 애플리케이션의 현재 작업 디렉터리와 무관하게 서명한다.
        cls.config.write_text(
            "[tsa]\ndefault_tsa=local_tsa\n[local_tsa]\n"
            f"serial={cls.work.as_posix()}/serial\n"
            f"signer_cert={cls.work.as_posix()}/tsa.pem\n"
            f"signer_key={cls.work.as_posix()}/tsa.key\n"
            f"certs={cls.ca.as_posix()}\n"
            "signer_digest=sha256\ndefault_policy=1.2.3.4.1\nother_policies=1.2.3.4.2\n"
            "digests=sha256\naccuracy=secs:1,millisecs:500\nclock_precision_digits=3\n"
            "ordering=yes\ntsa_name=yes\ness_cert_id_chain=yes\ness_cert_id_alg=sha256\n",
            encoding="utf-8")
        cls.response = cls.sign(ROOT, NONCE)
        cls.export = run_scenario(scenario_by_id("S01"), "protect", seed=42)["log_export"]
        cls.checkpoint_response = cls.sign(cls.export["head"]["root_hash"], NONCE)

    @classmethod
    def sign(cls, root, nonce):
        (cls.work / "request.tsq").write_bytes(build_timestamp_request(root, nonce))
        cls.command("ts", "-reply", "-config", cls.config,
                    "-queryfile", cls.work / "request.tsq", "-out", cls.work / "response.tsr")
        return (cls.work / "response.tsr").read_bytes()

    def setUp(self):
        self.output = tempfile.TemporaryDirectory(prefix="itx-tsa-anchor-")
        self.addCleanup(self.output.cleanup)
        self.path = Path(self.output.name) / "anchors.json"

    def verified(self, response=None, root=ROOT, **kwargs):
        return verify_timestamp_response(self.response if response is None else response, root,
                                         ca_file=kwargs.pop("ca_file", self.ca), nonce=NONCE,
                                         openssl=OPENSSL, **kwargs)

    def anchor_checkpoint(self):
        anchor = TSAAnchor(self.path, ca_file=self.ca, openssl=OPENSSL)
        with patch("itx.audit.anchor_tsa.secrets.randbits", return_value=NONCE), \
                patch("itx.audit.anchor_tsa.build_opener") as opener:
            opener.return_value.open.return_value = _Reply(self.checkpoint_response)
            record = anchor.anchor(self.export["head"], now=123)
        return anchor, record

    def test_real_signed_response_verifies_and_extracts_tst_info(self):
        info = self.verified()
        self.assertEqual(info["root_hash"], ROOT)
        self.assertEqual(info["tsa_nonce"], "80ff")
        self.assertEqual(info["policy_oid"], "1.2.3.4.1")
        self.assertGreater(info["timestamp_ms"], 0)
        self.assertRegex(info["gen_time"], r"^\d{14}(\.\d+)?Z$")
        # 서명과 CA 검증을 그대로 수행하며 원래 nonce를 모르는 독립 조회도 지원한다.
        self.assertEqual(verify_timestamp_response(self.response, ROOT, ca_file=self.ca,
                                                  openssl=OPENSSL), info)

    def test_openssl_can_decode_the_python_generated_request(self):
        query = self.work / "python.tsq"
        query.write_bytes(build_timestamp_request(ROOT, NONCE))
        text = self.command("ts", "-query", "-in", query, "-text").decode()
        self.assertIn("sha256", text)
        self.assertIn("0x80FF", text)
        self.assertIn("Certificate required: yes", text)

    def test_wrong_root_nonce_and_untrusted_ca_are_rejected(self):
        with self.assertRaisesRegex(TSAError, "messageImprint"):
            self.verified(root="cd" * 32)
        with self.assertRaisesRegex(TSAError, "nonce"):
            verify_timestamp_response(self.response, ROOT, ca_file=self.ca, nonce=NONCE + 1)
        with self.assertRaisesRegex(TSAError, "certificate chain"):
            self.verified(ca_file=self.work / "untrusted.pem")
        with self.assertRaisesRegex(TSAError, "trusted TSA CA"):
            self.verified(ca_file=None)

    def test_signature_and_signed_time_tampering_are_rejected(self):
        damaged_signature = self.response[:-1] + bytes([self.response[-1] ^ 1])
        with self.assertRaisesRegex(TSAError, "signature"):
            self.verified(response=damaged_signature)
        time = self.verified()["gen_time"].encode()
        replacement = (b"1" if time[:1] != b"1" else b"2") + time[1:]
        damaged_time = self.response.replace(time, replacement, 1)
        with self.assertRaisesRegex(TSAError, "signature"):
            self.verified(response=damaged_time)

    def test_trailing_truncated_wrong_content_and_algorithm_are_rejected(self):
        for response in (self.response + b"\x00", self.response[:-10],
                         self.response.replace(bytes.fromhex("2a864886f70d0109100104"),
                                               bytes.fromhex("2a864886f70d0109100105"), 1),
                         self.response.replace(bytes.fromhex("608648016503040201"),
                                               bytes.fromhex("608648016503040202"))):
            with self.subTest(response=response[:10]), self.assertRaises(TSAError):
                self.verified(response=response)

    def test_http_post_uses_rfc3161_headers_and_der_body(self):
        with patch("itx.audit.anchor_tsa.secrets.randbits", return_value=NONCE), \
                patch("itx.audit.anchor_tsa.build_opener") as opener:
            opener.return_value.open.return_value = _Reply(self.response)
            raw, info = request_timestamp(ROOT, ca_file=self.ca, openssl=OPENSSL, timeout=4)
            call = opener.return_value.open.call_args
            request = call.args[0]
            self.assertEqual(request.full_url, DEFAULT_TSA_URL)
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(request.get_header("Content-type"), "application/timestamp-query")
            self.assertEqual(request.get_header("Accept"), "application/timestamp-reply")
            self.assertEqual(request.data, build_timestamp_request(ROOT, NONCE))
            self.assertEqual(call.kwargs["timeout"], 4)
            self.assertEqual(raw, self.response)
            self.assertEqual(info["root_hash"], ROOT)

    def test_http_errors_bad_content_and_oversize_responses_are_rejected(self):
        for reply in (_Reply(self.response, "text/html"), _Reply(self.response, status=500),
                      _Reply(b"x" * (MAX_RESPONSE_BYTES + 1))):
            with self.subTest(reply=reply), patch("itx.audit.anchor_tsa.build_opener") as opener:
                opener.return_value.open.return_value = reply
                with self.assertRaises(TSAError):
                    request_timestamp(ROOT, ca_file=self.ca)
        for error in (URLError("offline"), TimeoutError("timeout"), IncompleteRead(b"partial"),
                      HTTPError(DEFAULT_TSA_URL, 302, "redirect", {}, None)):
            with self.subTest(error=error), patch("itx.audit.anchor_tsa.build_opener") as opener:
                opener.return_value.open.side_effect = error
                with self.assertRaisesRegex(TSAError, "HTTP request failed"):
                    request_timestamp(ROOT, ca_file=self.ca)

    def test_invalid_url_timeout_and_missing_openssl_fail_closed(self):
        for url in ("file:///tmp/token", "https://user:pass@example.test/", "https://example.test/#token"):
            with self.subTest(url=url), self.assertRaises(TSAError):
                request_timestamp(ROOT, ca_file=self.ca, tsa_url=url)
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.subTest(timeout=timeout), self.assertRaises(TSAError):
                self.verified(timeout=timeout)
        with patch("itx.audit.anchor_tsa.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(TSAError, "could not complete"):
                self.verified()
        with patch("itx.audit.anchor_tsa.subprocess.run", side_effect=subprocess.TimeoutExpired("openssl", 1)):
            with self.assertRaisesRegex(TSAError, "could not complete"):
                self.verified()

    def test_anchor_persists_verified_response_and_preserves_prior_records(self):
        anchor, record = self.anchor_checkpoint()
        self.assertEqual(anchor.records, [record])
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), [record])
        self.assertEqual((anchor.token_dir / record["tsr_file"]).read_bytes(), self.checkpoint_response)
        self.assertEqual(record["requested_at"], 123)
        self.assertEqual(record["anchored_at"], record["timestamp_ms"])
        self.assertNotEqual(record["anchored_at"], record["requested_at"])
        restored = TSAAnchor(self.path, ca_file=self.ca, openssl=OPENSSL)
        self.assertEqual(restored.records, [record])
        with patch("itx.audit.anchor_tsa.secrets.randbits", return_value=NONCE), \
                patch("itx.audit.anchor_tsa.build_opener") as opener:
            opener.return_value.open.return_value = _Reply(self.checkpoint_response)
            restored.anchor(self.export["head"], 456)
        self.assertEqual(len(json.loads(self.path.read_text(encoding="utf-8"))), 2)

    def test_failed_response_does_not_create_an_anchor_or_token(self):
        anchor = TSAAnchor(self.path, ca_file=self.ca, openssl=OPENSSL)
        with patch("itx.audit.anchor_tsa.build_opener") as opener:
            opener.return_value.open.return_value = _Reply(bytes.fromhex("30053003020102"))
            with self.assertRaises(TSAError):
                anchor.anchor(self.export["head"], 123)
        self.assertEqual(anchor.records, [])
        self.assertFalse(self.path.exists())
        self.assertFalse(anchor.token_dir.exists())

    def test_independent_replay_verifies_saved_token_without_network(self):
        anchor, record = self.anchor_checkpoint()
        with patch("itx.audit.anchor_tsa.build_opener") as opener:
            report = replay_audit(self.export, [record], {}, {}, reference_hashes(),
                                  tsa_ca_file=self.ca, tsa_token_dir=anchor.token_dir, tsa_openssl=OPENSSL)
            opener.assert_not_called()
        self.assertTrue(report["ok"], report)
        self.assertTrue(report["anchors"][0]["tsa_verified"])
        self.assertEqual(report["anchors"][0]["gen_time"], record["gen_time"])

    def test_replay_rejects_missing_trust_token_and_modified_metadata(self):
        anchor, record = self.anchor_checkpoint()
        for field, value in (("gen_time", "20000101000000Z"), ("anchored_at", 1),
                             ("tsa_nonce", "ff"), ("witness", "mock-file-witness"),
                             ("tsr_file", "../secret.tsr")):
            modified = dict(record, **{field: value})
            with self.subTest(field=field):
                report = replay_audit(self.export, [modified], {}, {}, reference_hashes(),
                                      tsa_ca_file=self.ca, tsa_token_dir=anchor.token_dir, tsa_openssl=OPENSSL)
                self.assertFalse(report["ok"])
                self.assertFalse(report["anchors"][0]["tsa_verified"])
        report = replay_audit(self.export, [record], {}, {}, reference_hashes())
        self.assertFalse(report["ok"])
        (anchor.token_dir / record["tsr_file"]).unlink()
        with self.assertRaises(TSAError):
            verify_tsa_anchor(record, ca_file=self.ca, token_dir=anchor.token_dir, openssl=OPENSSL)

    def test_rehashed_corrupt_token_still_requires_a_valid_signature(self):
        anchor, record = self.anchor_checkpoint()
        token = self.checkpoint_response[:-1] + bytes([self.checkpoint_response[-1] ^ 1])
        filename = hashlib.sha256(token).hexdigest() + ".tsr"
        (anchor.token_dir / filename).write_bytes(token)
        with self.assertRaisesRegex(TSAError, "signature"):
            verify_tsa_anchor(dict(record, tsr_file=filename), ca_file=self.ca,
                              token_dir=anchor.token_dir, openssl=OPENSSL)

    def test_tsa_anchor_detects_rewritten_log_even_with_a_new_local_signature(self):
        from itx.crypto import canonical_json
        from itx.sim.runner import _keys
        from itx.statements import SignedStatement
        from itx.ts import MerkleTree

        anchor, record = self.anchor_checkpoint()
        changed = copy.deepcopy(self.export)
        changed["entries"][0]["statement"]["payload"]["version"] += 1
        tree = MerkleTree()
        for entry in changed["entries"]:
            tree.append(SignedStatement.from_dict(entry["statement"]).leaf_bytes())
        changed["head"]["root_hash"] = tree.root().hex()
        unsigned = {key: value for key, value in changed["head"].items() if key != "signature"}
        changed["head"]["signature"] = _keys(42)["T"].sign(canonical_json(unsigned)).hex()
        report = replay_audit(changed, [record], {}, {}, reference_hashes(),
                              tsa_ca_file=self.ca, tsa_token_dir=anchor.token_dir, tsa_openssl=OPENSSL)
        self.assertTrue(report["head_signature_valid"])
        self.assertFalse(report["anchors"][0]["ok"])
        self.assertFalse(report["anchors"][0]["root_matches"])
        self.assertTrue(report["anchors"][0]["tsa_verified"])
        self.assertFalse(report["ok"])


if __name__ == "__main__":
    unittest.main()
