"""암호 기반 계층 검사: RFC 8032 시험 벡터, 정규화 결정성, 커밋."""
import unittest

from itx.crypto import KeyPair, canonical_json, commit_hex, content_hash_hex, sha256_hex, signing, verify
from itx.crypto.canonical import CanonicalizationError

# RFC 8032 §7.1 TEST 1~3 (seed, public key, message, signature)
RFC8032_VECTORS = [
    (
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
    ),
    (
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "72",
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    ),
    (
        "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
        "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
        "af82",
        "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a",
    ),
]


class Ed25519PureTest(unittest.TestCase):
    def test_rfc8032_vectors(self):
        for seed, pk, msg, sig in RFC8032_VECTORS:
            seed_b, msg_b = bytes.fromhex(seed), bytes.fromhex(msg)
            self.assertEqual(signing._pure_public_key(seed_b).hex(), pk)
            self.assertEqual(signing._pure_sign(seed_b, msg_b).hex(), sig)
            self.assertTrue(signing._pure_verify(bytes.fromhex(pk), msg_b, bytes.fromhex(sig)))
            self.assertFalse(signing._pure_verify(bytes.fromhex(pk), msg_b + b"x", bytes.fromhex(sig)))

    def test_backend_roundtrip(self):
        kp = KeyPair.from_name("test-key")
        sig = kp.sign(b"hello")
        self.assertTrue(verify(kp.public_key, b"hello", sig))
        self.assertFalse(verify(kp.public_key, b"hellO", sig))
        # 순수 구현과 현재 백엔드는 상호 검증돼야 한다.
        self.assertTrue(signing._pure_verify(kp.public_key, b"hello", sig))
        self.assertEqual(signing._pure_public_key(kp.seed), kp.public_key)

    def test_malformed_inputs(self):
        kp = KeyPair.from_name("k")
        self.assertFalse(verify(kp.public_key, b"m", b"\x00" * 63))
        self.assertFalse(verify(b"\x00" * 31, b"m", b"\x00" * 64))


class CanonicalTest(unittest.TestCase):
    def test_order_independence(self):
        a = canonical_json({"b": 1, "a": {"y": [1, 2], "x": "한글"}})
        b = canonical_json({"a": {"x": "한글", "y": [1, 2]}, "b": 1})
        self.assertEqual(a, b)
        self.assertEqual(a, '{"a":{"x":"한글","y":[1,2]},"b":1}'.encode())

    def test_rejects_float_and_nonascii_key(self):
        with self.assertRaises(CanonicalizationError):
            canonical_json({"a": 1.5})
        with self.assertRaises(CanonicalizationError):
            canonical_json({"키": 1})


class CommitTest(unittest.TestCase):
    def test_commit_depends_on_salt(self):
        h = content_hash_hex(canonical_json({"q": "hello"}))
        c1 = commit_hex("00" * 32, h)
        c2 = commit_hex("01" * 32, h)
        self.assertNotEqual(c1, c2)
        self.assertEqual(len(c1), 64)
        self.assertEqual(sha256_hex(b""), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")


if __name__ == "__main__":
    unittest.main()
