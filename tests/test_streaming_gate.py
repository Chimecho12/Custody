"""청크 체인의 고정 벡터, 변조 검출 및 종료 후 재사용 차단을 검사한다."""
import hashlib
import struct
import unittest

from itx.enforce.streaming_gate import StreamingGate, StreamTamperedError


# h_0 = SHA256(UTF8(request_hash || nonce)), i는 1부터 시작하는 uint32_be.
REQUEST_HASH = "b0de366ba2b13f1307f332e12b2a8d7070efb0bd92239ff5eb980f8863aa9b79"
NONCE = "stream-nonce-01"
CHUNKS = (b"Hello, ", "세계".encode("utf-8"), b"!")
INITIAL_HASH = "dac441173838f08e7a83e560d22cfee9031da5662d02da1aa9146604eb9ddbcf"
CHUNK_HASHES = (
    "09a27a9ad80640da377edb5058c19f917d85ce5e9f645cecb65fe052d82dce20",
    "9a103b34fdbb6d01ef3fbef010f6b19f6b4baca76544c9a18447e839173cc04c",
    "b9c12db8c64b9270fa1169c6c142eeec91fc44e97ffd7900082fc63d5bd3bd0c",
)
ROOT_HASH = CHUNK_HASHES[-1]


def reference_root(chunks, request_hash=REQUEST_HASH, nonce=NONCE):
    digest = hashlib.sha256((request_hash + nonce).encode("utf-8")).digest()
    for index, chunk in enumerate(chunks, 1):
        digest = hashlib.sha256(digest + struct.pack(">I", index) + chunk).digest()
    return digest.hex()


class StreamingGateTest(unittest.TestCase):
    def make_gate(self, root=ROOT_HASH):
        return StreamingGate(root, REQUEST_HASH, NONCE)

    def assert_aborted(self, gate):
        # 올바른 청크를 재시도하거나 최종 해시를 제출해도 실패를 되돌릴 수 없다.
        with self.assertRaisesRegex(StreamTamperedError, "aborted"):
            gate.feed_chunk(2, CHUNKS[1])
        with self.assertRaisesRegex(StreamTamperedError, "aborted"):
            gate.finalize(ROOT_HASH)

    def test_normal_stream_passes_fixed_vector(self):
        for per_chunk_verification in (False, True):
            with self.subTest(per_chunk_verification=per_chunk_verification):
                gate = self.make_gate()
                for index, chunk in enumerate(CHUNKS, 1):
                    kwargs = {"expected_chunk_hash": CHUNK_HASHES[index - 1]} if per_chunk_verification else {}
                    self.assertIs(gate.feed_chunk(index, chunk, **kwargs), True)
                self.assertIs(gate.finalize(ROOT_HASH), True)

    def test_middle_payload_tampering_aborts_immediately_before_release(self):
        gate = self.make_gate()
        received, released = [], []

        def stream():
            for index, chunk in enumerate((CHUNKS[0], b"tampered", CHUNKS[2]), 1):
                received.append(index)
                yield index, chunk

        with self.assertRaisesRegex(StreamTamperedError, "chunk 2 chain digest mismatch"):
            for index, chunk in stream():
                gate.feed_chunk(index, chunk, expected_chunk_hash=CHUNK_HASHES[index - 1])
                released.append(chunk)

        # finalize를 기다리지 않고 두 번째 feed에서 중단: 세 번째 청크도 읽지 않는다.
        self.assertEqual(received, [1, 2])
        self.assertEqual(released, [CHUNKS[0]])
        self.assert_aborted(gate)

    def test_wrong_or_malformed_chunk_hash_aborts_immediately(self):
        for value in ("00" * 32, "invalid", " " * 64, b"00" * 32):
            with self.subTest(value=value):
                gate = self.make_gate()
                gate.feed_chunk(1, CHUNKS[0], expected_chunk_hash=CHUNK_HASHES[0])
                with self.assertRaises(StreamTamperedError):
                    gate.feed_chunk(2, CHUNKS[1], expected_chunk_hash=value)
                self.assert_aborted(gate)

    def test_empty_stream_matches_initial_hash(self):
        gate = self.make_gate(INITIAL_HASH)
        self.assertIs(gate.finalize(INITIAL_HASH), True)

    def test_empty_binary_and_split_utf8_chunks_preserve_exact_bytes(self):
        chunks = (b"", b"\x00\xff", b"\xec", b"\x84\xb8", b"[DONE]", b"\r\n")
        root = reference_root(chunks, nonce="nonce-한글")
        gate = StreamingGate(root, REQUEST_HASH, "nonce-한글")
        for index, chunk in enumerate(chunks, 1):
            self.assertIs(gate.feed_chunk(index, chunk), True)
        # feed_chunk는 SSE 파서가 아니므로 응답 본문의 [DONE] 바이트도 그대로 해싱한다.
        self.assertIs(gate.finalize(root), True)

    def test_sequence_errors_abort_before_the_bad_chunk_is_released(self):
        for prefix, wrong_index in (((), 2), ((1,), 1), ((1,), 3), ((1, 2), 1)):
            with self.subTest(prefix=prefix, wrong_index=wrong_index):
                gate = self.make_gate()
                released = []
                for index in prefix:
                    gate.feed_chunk(index, CHUNKS[index - 1])
                    released.append(CHUNKS[index - 1])
                with self.assertRaisesRegex(StreamTamperedError, "unexpected chunk index"):
                    gate.feed_chunk(wrong_index, b"unexpected")
                    released.append(b"unexpected")
                self.assertEqual(released, [CHUNKS[i - 1] for i in prefix])
                self.assert_aborted(gate)

    def test_invalid_indices_abort(self):
        for index in (-1, 0, 2**32, 1.0, True, "1", None):
            with self.subTest(index=index):
                gate = self.make_gate()
                with self.assertRaises(StreamTamperedError):
                    gate.feed_chunk(index, CHUNKS[0])
                self.assert_aborted(gate)

    def test_non_byte_chunks_abort(self):
        for chunk in ("text", None, bytearray(b"mutable")):
            with self.subTest(chunk=chunk):
                gate = self.make_gate()
                with self.assertRaisesRegex(StreamTamperedError, "chunk_bytes"):
                    gate.feed_chunk(1, chunk)
                self.assert_aborted(gate)

    def test_payload_tampering_without_chunk_hash_is_detected_at_finalize(self):
        gate = self.make_gate()
        for index, chunk in enumerate((CHUNKS[0], b"tampered", CHUNKS[2]), 1):
            self.assertIs(gate.feed_chunk(index, chunk), True)
        with self.assertRaisesRegex(StreamTamperedError, "chain digest"):
            gate.finalize(ROOT_HASH)
        self.assert_aborted(gate)

    def test_recomputed_tampered_done_hash_cannot_replace_receipt_root(self):
        chunks = (CHUNKS[0], b"tampered", CHUNKS[2])
        gate = self.make_gate()
        for index, chunk in enumerate(chunks, 1):
            gate.feed_chunk(index, chunk)
        with self.assertRaisesRegex(StreamTamperedError, "signed receipt root"):
            gate.finalize(reference_root(chunks))
        self.assert_aborted(gate)

    def test_missing_tail_or_extra_chunk_fails_finalization(self):
        for chunks in (CHUNKS[:-1], CHUNKS + (b"extra",)):
            with self.subTest(chunks=chunks):
                gate = self.make_gate()
                for index, chunk in enumerate(chunks, 1):
                    gate.feed_chunk(index, chunk)
                with self.assertRaisesRegex(StreamTamperedError, "chain digest"):
                    gate.finalize(ROOT_HASH)
                self.assert_aborted(gate)

    def test_wrong_request_or_nonce_cannot_replay_the_stream(self):
        for request_hash, nonce in (("00" * 32, NONCE), (REQUEST_HASH, "other-nonce")):
            with self.subTest(request_hash=request_hash, nonce=nonce):
                gate = StreamingGate(ROOT_HASH, request_hash, nonce)
                for index, chunk in enumerate(CHUNKS, 1):
                    gate.feed_chunk(index, chunk)
                with self.assertRaisesRegex(StreamTamperedError, "chain digest"):
                    gate.finalize(ROOT_HASH)

    def test_changed_chunk_boundaries_do_not_match_the_original_root(self):
        gate = self.make_gate()
        gate.feed_chunk(1, CHUNKS[0] + CHUNKS[1])
        gate.feed_chunk(2, CHUNKS[2])
        with self.assertRaises(StreamTamperedError):
            gate.finalize(ROOT_HASH)

    def test_wrong_done_hash_aborts_even_with_the_correct_stream(self):
        gate = self.make_gate()
        for index, chunk in enumerate(CHUNKS, 1):
            gate.feed_chunk(index, chunk)
        with self.assertRaisesRegex(StreamTamperedError, "signed receipt root"):
            gate.finalize("00" * 32)
        self.assert_aborted(gate)

    def test_malformed_root_and_final_hashes_are_rejected(self):
        for value in (None, b"00" * 32, "", "00" * 31, "00" * 33, "gg" * 32, " " * 64):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.make_gate(value)
                gate = self.make_gate()
                with self.assertRaises(StreamTamperedError):
                    gate.finalize(value)
                self.assert_aborted(gate)

    def test_hex_case_does_not_change_digest_identity(self):
        gate = self.make_gate(ROOT_HASH.upper())
        for index, chunk in enumerate(CHUNKS, 1):
            gate.feed_chunk(index, chunk)
        self.assertIs(gate.finalize(ROOT_HASH.upper()), True)

    def test_finalized_gate_rejects_more_data_and_repeated_finalization(self):
        gate = self.make_gate()
        for index, chunk in enumerate(CHUNKS, 1):
            gate.feed_chunk(index, chunk)
        self.assertIs(gate.finalize(ROOT_HASH), True)
        with self.assertRaisesRegex(StreamTamperedError, "finalized"):
            gate.feed_chunk(4, b"extra")
        with self.assertRaisesRegex(StreamTamperedError, "finalized"):
            gate.finalize(ROOT_HASH)


if __name__ == "__main__":
    unittest.main()
