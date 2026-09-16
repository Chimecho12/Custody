"""CBOR · COSE_Sign1 검증.

CBOR 인코더는 RFC 8949 부록 A 의 시험 벡터로 검사한다. 제3자 라이브러리를 쓰지
않는 저장소이므로, 「우리 디코더가 우리 인코더를 읽는다」는 순환 검사만으로는
부족하다. 표준 문서가 직접 적어 둔 바이트와 대조해야 한다.
"""
from __future__ import annotations

import unittest

from itx.cose import cbor, conformance, profile, sign1
from itx.crypto import KeyPair
from itx.statements import CT_RECEIPT, issue

#: RFC 8949 부록 A. (값, 16진 인코딩) — 이 프로파일이 허용하는 타입만 옮겼다.
RFC8949_VECTORS = [
    (0, "00"), (1, "01"), (10, "0a"), (23, "17"), (24, "1818"), (25, "1819"),
    (100, "1864"), (1000, "1903e8"), (1000000, "1a000f4240"), (1000000000000, "1b000000e8d4a51000"),
    (-1, "20"), (-10, "29"), (-100, "3863"), (-1000, "3903e7"),
    (False, "f4"), (True, "f5"), (None, "f6"),
    (b"", "40"), (b"\x01\x02\x03\x04", "4401020304"),
    ("", "60"), ("a", "6161"), ("IETF", "6449455446"), ('"\\', "62225c"),
    ("ü", "62c3bc"), ("水", "63e6b0b4"),
    ([], "80"), ([1, 2, 3], "83010203"), ([1, [2, 3], [4, 5]], "8301820203820405"),
    ({}, "a0"), ({1: 2, 3: 4}, "a201020304"),
    ({"a": 1, "b": [2, 3]}, "a26161016162820203"),
    (["a", {"b": "c"}], "826161a161626163"),
    ({"a": "A", "b": "B", "c": "C", "d": "D", "e": "E"},
     "a56161614161626142616361436164614461656145"),
]


class DeterministicCBOR(unittest.TestCase):
    def test_rfc8949_appendix_a_vectors(self):
        for value, expected in RFC8949_VECTORS:
            with self.subTest(value=value):
                self.assertEqual(cbor.encode(value).hex(), expected)
                self.assertEqual(cbor.decode(bytes.fromhex(expected)), value)

    def test_map_keys_sort_by_encoded_bytes_not_codepoints(self):
        """RFC 8949 §4.2.1 은 인코딩된 키 바이트로 정렬한다 — 짧은 키가 먼저 온다.

        JSON 쪽(itx.crypto.canonical)은 코드포인트로 정렬하므로 두 순서가 다를 수
        있다. 같은 내용을 두 인코딩으로 낼 때 이 차이를 잊으면 한쪽만 결정적이 된다.
        """
        self.assertEqual(cbor.encode({"aa": 1, "b": 2}), cbor.encode({"b": 2, "aa": 1}))
        first_key = cbor.encode({"aa": 1, "b": 2})[1:3]
        self.assertEqual(first_key, b"\x61b", "짧은 키 'b' 가 'aa' 보다 먼저여야 한다")

    def test_encoding_is_independent_of_insertion_order(self):
        left = {"z": 1, "a": {"y": 2, "b": 3}, "m": [1, 2]}
        right = {"m": [1, 2], "a": {"b": 3, "y": 2}, "z": 1}
        self.assertEqual(cbor.encode(left), cbor.encode(right))

    def test_round_trip_is_byte_identical(self):
        value = {"leaf": b"\x71\xc0", "tree_size": 18402, "path": [b"\x2c", b"\x7f"], "ok": True}
        encoded = cbor.encode(value)
        self.assertEqual(cbor.encode(cbor.decode(encoded)), encoded)

    def test_rejects_non_deterministic_input(self):
        # 최소 길이가 아닌 인자, 무한 길이, 부동소수, 중복 키, 정렬 위반 — 전부 거부한다.
        cases = {
            "non-minimal int": "1817",          # 23 을 1바이트 인자로 쓴 것
            "indefinite bstr": "5f4101ff",      # 무한 길이 바이트열
            "float16": "f93c00",                # 1.0
            "duplicate key": "a2616101616102",  # {"a":1,"a":2}
            "unsorted map": "a262626201616102",  # {"bb":1,"a":2} — "a" 가 먼저여야 한다
        }
        for name, raw in cases.items():
            with self.subTest(name), self.assertRaises(cbor.CBORError):
                cbor.decode(bytes.fromhex(raw))

    def test_rejects_float_on_encode(self):
        with self.assertRaises(cbor.CBORError):
            cbor.encode({"ratio": 0.5})

    def test_rejects_trailing_bytes(self):
        with self.assertRaises(cbor.CBORError):
            cbor.decode(cbor.encode(1) + b"\x01")


class COSESign1(unittest.TestCase):
    def setUp(self):
        self.key = KeyPair.from_name("m-test", namespace="itx-cose-test")
        self.stmt = issue(self.key, iss="urn:itx:party:m", sub="att-test-0001",
                          content_type=CT_RECEIPT, issued_at=1178,
                          payload={"in_commit": "aa", "out_commit": "bb", "attempt": "att-test-0001"})
        self.signed = profile.to_sign1(self.key, self.stmt)

    def test_signature_covers_the_sig_structure_not_the_payload(self):
        """RFC 9052 §4.4. 헤더를 바꾸면 payload 가 같아도 검증이 깨져야 한다."""
        parsed = sign1.parse(self.signed)
        sign1.verify_signature(self.signed, self.key.public_key)

        swapped = dict(parsed["header"])
        swapped[sign1.HDR_CONTENT_TYPE] = "application/evil"
        body = list(cbor.decode(self.signed).value)
        body[0] = cbor.encode(swapped)
        forged = cbor.encode(cbor.Tagged(sign1.TAG_SIGN1, body))
        with self.assertRaises(sign1.COSEError):
            sign1.verify_signature(forged, self.key.public_key)

    def test_round_trip_restores_the_statement(self):
        restored = profile.from_sign1(self.signed, self.key.public_key)
        for field in ("iss", "sub", "content_type", "kid", "issued_at", "payload"):
            self.assertEqual(getattr(restored, field), getattr(self.stmt, field), field)

    def test_cose_signature_differs_from_the_json_signature(self):
        """두 인코딩은 서명 대상 바이트가 다르다. 같으면 오히려 구현이 틀린 것이다."""
        restored = profile.from_sign1(self.signed, self.key.public_key)
        self.assertNotEqual(restored.signature, self.stmt.signature)
        self.assertTrue(self.stmt.verify_with(self.key.public_key))

    def test_refuses_to_reissue_another_partys_statement(self):
        other = KeyPair.from_name("r-test", namespace="itx-cose-test")
        with self.assertRaises(sign1.COSEError):
            profile.to_sign1(other, self.stmt)

    def test_wrong_public_key_is_rejected(self):
        other = KeyPair.from_name("r-test", namespace="itx-cose-test")
        with self.assertRaises(sign1.COSEError):
            sign1.verify_signature(self.signed, other.public_key)

    def test_encodings_gives_both_views_of_one_statement(self):
        both = profile.encodings(self.key, self.stmt)
        self.assertIn('"sub"', both["json"])
        self.assertTrue(both["cose_hex"].startswith("d2 84"))  # tag 18, 4요소 배열
        self.assertIn("18(", both["cose_diagnostic"])
        self.assertGreater(both["json_bytes"], both["cose_bytes"], "CBOR 가 JSON 보다 작아야 한다")
        self.assertTrue(all(row["state"] == "pass" for row in both["structure"]))


class ConformanceSuite(unittest.TestCase):
    def test_every_vector_runs_and_none_fails(self):
        report = conformance.run()
        self.assertEqual(report["totals"]["fail"], 0,
                         [i for g in report["groups"] for i in g["items"] if i["state"] == "fail"])
        self.assertGreater(report["totals"]["pass"], 0)
        self.assertEqual(report["totals"]["total"],
                         sum(report["totals"][s] for s in ("pass", "partial", "absent", "fail")))

    def test_unimplemented_areas_stay_visible(self):
        """결손은 지우지 않는다. 화면이 「표준 대비 어디까지 왔는가」를 말해야 한다."""
        report = conformance.run()
        absent = {i["id"] for g in report["groups"] for i in g["items"] if i["state"] == "absent"}
        self.assertTrue({"gs-01", "gs-03", "te-02"} <= absent)

    def test_external_tool_results_are_not_claimed(self):
        """이 저장소는 pyscitt·cosign 을 돌리지 않는다. 돌린 척하면 안 된다."""
        report = conformance.run()
        self.assertTrue(report["external_tools"])
        for tool in report["external_tools"]:
            self.assertEqual(tool["state"], "absent", tool["tool"])

    def test_negative_vectors_are_present_in_each_runnable_group(self):
        """거부 검사가 없으면 아무것도 거부하지 않는 구현이 만점을 받는다."""
        report = conformance.run(groups=("cose", "cbor", "merkle"))
        for group in report["groups"]:
            labels = " ".join(i["label"] + i["note"] for i in group["items"])
            self.assertIn("거부", labels, f"{group['key']} 에 음성 벡터가 없다")


if __name__ == "__main__":
    unittest.main()
