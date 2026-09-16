"""서명자 추상화 — 사설키를 이 프로세스가 쥐는가, 남이 쥐는가.

지금까지 서명은 `KeyPair.sign` 하나였고, 그 말은 사설키가 언제나 이 프로세스의
메모리에 있었다는 뜻이다. 한계 14 가 가리키는 자리다.

`Signer` 는 그 자리를 둘로 가른다.

    LocalKeySigner   사설키가 이 프로세스에 있다 (기존 동작)
    CommandSigner    외부 프로그램이 서명한다 — 사설키는 이 프로세스에 없다

`CommandSigner` 는 KMS·HSM 어댑터를 붙이는 지점이다. 자격 증명이나 SDK 를 이
저장소에 넣지 않고도 실제로 동작한다. `aws kms sign`, `gcloud kms asymmetric-sign`,
YubiKey PIV 도구를 감싼 스크립트를 명령으로 주면 된다.

**정직하게 적어야 하는 것 하나.** 순수 Ed25519(RFC 8032 PureEdDSA)는 해시가 아니라
메시지 전체에 서명한다. 따라서 「해시만 전송」은 Ed25519ph 나 ECDSA 처럼 prehash 를
쓰는 경우에만 참이다. 어느 쪽인지는 `payload_form` 에 남기고 화면에 그대로 표시한다.
사설키가 나가지 않는 것과 본문이 나가지 않는 것은 다른 문제다.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Protocol

from itx.crypto import KeyPair, sha256, verify

from .custody import Custody

#: 외부 서명자에게 무엇을 보내는가.
SENDS_MESSAGE = "message"   # 메시지 전체 (순수 Ed25519)
SENDS_DIGEST = "digest"     # 해시만 (Ed25519ph · ECDSA 등 prehash 방식)


class SignerError(RuntimeError):
    pass


class Signer(Protocol):
    kid: str
    public_key: bytes
    custody: Custody

    def sign(self, message: bytes) -> bytes: ...


@dataclass
class LocalKeySigner:
    """기존 동작. 사설키가 이 프로세스 메모리에 평문으로 존재한다."""

    key: KeyPair
    custody: Custody

    @property
    def kid(self) -> str:
        return self.key.kid

    @property
    def public_key(self) -> bytes:
        return self.key.public_key

    def sign(self, message: bytes) -> bytes:
        return self.key.sign(message)


@dataclass
class CommandSigner:
    """외부 프로그램에 서명을 맡긴다. 사설키는 이 프로세스에 없다.

    프로토콜은 의도적으로 가장 단순한 형태다 — stdin 으로 16진 문자열 한 줄을 주고,
    stdout 에서 16진 서명 한 줄을 받는다. 셸 스크립트로도 어댑터를 쓸 수 있어야
    새 보관처를 붙이는 비용이 낮아진다.
    """

    kid: str
    public_key: bytes
    command: list[str]
    custody: Custody
    payload_form: str = SENDS_MESSAGE
    timeout_s: float = 20.0
    #: 검증까지 해서 외부 서명자가 엉뚱한 값을 줬을 때 그 자리에서 잡는다.
    verify_after_sign: bool = True

    def __post_init__(self) -> None:
        if self.payload_form not in (SENDS_MESSAGE, SENDS_DIGEST):
            raise ValueError(f"알 수 없는 전송 형태: {self.payload_form}")
        if not self.command:
            raise ValueError("서명 명령이 비어 있습니다")

    def _outbound(self, message: bytes) -> bytes:
        return message if self.payload_form == SENDS_MESSAGE else sha256(message)

    def sign(self, message: bytes) -> bytes:
        payload = self._outbound(message)
        started = time.perf_counter()
        try:
            done = subprocess.run(
                self.command, input=payload.hex() + "\n", capture_output=True,
                text=True, timeout=self.timeout_s, check=False)
        except FileNotFoundError as error:
            raise SignerError(f"서명 명령을 찾을 수 없습니다: {self.command[0]}") from error
        except subprocess.TimeoutExpired as error:
            raise SignerError(f"서명 명령이 {self.timeout_s}초 안에 끝나지 않았습니다") from error
        elapsed_ms = round((time.perf_counter() - started) * 1000)

        if done.returncode != 0:
            raise SignerError(f"서명 명령 실패 (exit {done.returncode}): {done.stderr.strip()[:200]}")
        try:
            signature = bytes.fromhex(done.stdout.strip())
        except ValueError as error:
            raise SignerError("서명 명령이 16진 서명을 내지 않았습니다") from error
        if len(signature) != 64:
            raise SignerError(f"Ed25519 서명은 64바이트여야 합니다 (받은 값 {len(signature)}바이트)")
        if self.verify_after_sign and not verify(self.public_key, message, signature):
            raise SignerError("외부 서명자가 낸 서명이 고정된 공개키로 검증되지 않습니다")

        # 실측된 왕복 지연을 계보에 남긴다. KMS 도입의 실제 대가는 지연이므로 숨기지 않는다.
        self.custody.round_trip_ms = elapsed_ms
        self.custody.sign_count += 1
        return signature

    def probe(self) -> dict[str, object]:
        """설정만 보고 한 번 서명해 어댑터가 실제로 도는지 확인한다."""
        try:
            self.sign(b"itx-signer-probe")
        except SignerError as error:
            return {"ok": False, "error": str(error), "round_trip_ms": None}
        return {"ok": True, "error": None, "round_trip_ms": self.custody.round_trip_ms}


def signing_chain(signer: Signer) -> list[dict[str, object]]:
    """원격 서명 경로 그림의 4단계. `inside` 가 굵은 테두리 구간이다."""
    custody = signer.custody
    if isinstance(signer, CommandSigner) and signer.payload_form == SENDS_DIGEST:
        second = ("Sign 요청", "해시 32 B 만 전달", "네트워크")
    elif isinstance(signer, CommandSigner):
        second = ("Sign 요청", "서명 대상 바이트 전달", "네트워크")
    else:
        second = ("키 파일 복호", "사용자 범위 복호", "로컬")

    third = (("외부 서명자 내부 서명", "사설키 반출 없음", custody.store_label)
             if not custody.exposed
             else ("프로세스 내 서명", "사설키가 메모리에 평문 존재", "이 프로세스"))
    return [
        {"title": "해시 계산", "sub": "서명 대상 커밋", "at": "로컬", "inside": False},
        {"title": second[0], "sub": second[1], "at": second[2], "inside": False},
        {"title": third[0], "sub": third[1], "at": third[2], "inside": True},
        {"title": "서명값 회수", "sub": "64 B Ed25519", "at": "로컬", "inside": False},
    ]
