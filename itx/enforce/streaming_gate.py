"""SSE에서 추출한 응답 청크의 순서와 SHA-256 누적 해시를 검증한다.

request_hash와 nonce는 전달된 문자열 그대로 UTF-8로 인코딩해 h_0를 만든다.
청크 번호는 1부터 시작하며, 이전 해시는 hex 문자열이 아닌 32바이트 다이제스트다.
기대 해시는 64자리 hex 문자열이다. [DONE]은 응답 청크에 포함하지 않고 그 이벤트의
최종 해시를 finalize에 전달한다.

expected_root_hash는 호출자가 모델 영수증의 서명과 요청 결합을 검증한 뒤 얻은
streaming_root_digest여야 한다. 이 모듈은 SSE 파싱이나 영수증 서명 검증을 맡지 않는다.
호출자는 예외 발생 시 전송 연결을 닫고 스트림 소비를 중단해야 한다.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import NoReturn


class StreamTamperedError(ValueError):
    """스트림 검증 실패 또는 종료된 검증기의 재사용."""


def _digest_from_hex(value: str, name: str) -> bytes:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{name} must be a 64-character SHA-256 hex digest")
    try:
        digest = bytes.fromhex(value)
    except ValueError:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from None
    if len(digest) != 32:
        raise ValueError(f"{name} must encode exactly 32 bytes")
    return digest


class StreamingGate:
    """실패하면 이후 feed_chunk와 finalize 호출도 모두 거부하는 검증기.

    feed_chunk의 성공만으로 전체 스트림의 무결성이 확정되지는 않는다.
    최종 수용 전에 반드시 [DONE]의 해시로 finalize를 호출해야 한다.

    내용 변조의 즉시 검출에는 선택 인자 expected_chunk_hash로 해당 청크까지의
    신뢰된 누적 해시를 제공해야 한다. 공격자가 청크와 기대 해시를 함께 바꿀 수 있는
    경로에서 받은 값은 인증 근거가 아니다. 기대 해시가 없으면 순서 오류만 즉시 검출하며,
    내용 검증은 finalize에서 완료된다. 이 경우 호출자는 성공적인 finalize 전까지
    응답을 버퍼링해야 한다.
    """

    def __init__(self, expected_root_hash: str, request_hash: str, nonce: str) -> None:
        self._expected_root = _digest_from_hex(expected_root_hash, "expected_root_hash")
        if not isinstance(request_hash, str) or not isinstance(nonce, str):
            raise TypeError("request_hash and nonce must be strings")
        self._chain_hash = hashlib.sha256(
            request_hash.encode("utf-8") + nonce.encode("utf-8")
        ).digest()
        self._next_index = 1
        self._failed = False
        self._finalized = False

    def _abort(self, message: str) -> NoReturn:
        self._failed = True
        raise StreamTamperedError(message)

    def _ensure_open(self) -> None:
        if self._failed:
            raise StreamTamperedError("stream has been aborted")
        if self._finalized:
            raise StreamTamperedError("stream has already been finalized")

    def feed_chunk(
        self, index: int, chunk_bytes: bytes, *, expected_chunk_hash: str | None = None,
    ) -> bool:
        """청크 번호와 (제공된 경우) 기대 h_i를 검증한 후 체인을 진행한다."""
        self._ensure_open()
        if type(index) is not int or not 1 <= index <= 0xFFFFFFFF:
            self._abort("chunk index must be an integer in [1, 2**32 - 1]")
        if index != self._next_index:
            self._abort(f"unexpected chunk index: expected {self._next_index}, got {index}")
        if not isinstance(chunk_bytes, bytes):
            self._abort("chunk_bytes must be bytes")

        hasher = hashlib.sha256(self._chain_hash)
        hasher.update(index.to_bytes(4, "big"))
        hasher.update(chunk_bytes)
        candidate = hasher.digest()
        if expected_chunk_hash is not None:
            try:
                expected = _digest_from_hex(expected_chunk_hash, "expected_chunk_hash")
            except ValueError as exc:
                self._abort(str(exc))
            if not hmac.compare_digest(candidate, expected):
                self._abort(f"chunk {index} chain digest mismatch")

        self._chain_hash = candidate
        self._next_index += 1
        return True

    def finalize(self, expected_final_hash: str) -> bool:
        """계산된 체인 == [DONE]의 해시 == 서명된 영수증의 루트일 때 종료한다."""
        self._ensure_open()
        try:
            final_hash = _digest_from_hex(expected_final_hash, "expected_final_hash")
        except ValueError as exc:
            self._abort(str(exc))
        if not hmac.compare_digest(final_hash, self._expected_root):
            self._abort("final digest does not match the signed receipt root")
        if not hmac.compare_digest(self._chain_hash, final_hash):
            self._abort("stream chain digest does not match the final digest")
        self._finalized = True
        return True
