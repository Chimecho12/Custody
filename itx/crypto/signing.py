"""Ed25519 서명.

`cryptography` 패키지가 있으면 그것을 쓰고, 없으면 표준 라이브러리만으로 동작하는
순수 Python 구현(RFC 8032, 확장 좌표)을 쓴다. 두 구현은 같은 키·서명 형식을 내므로
상호 검증된다 (tests/test_crypto.py).

순수 Python 구현은 교육·시뮬레이션용이다. 상수 시간 연산이 아니므로 실제 비밀키를
다루는 운영 환경에서는 검증된 라이브러리를 써야 한다.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

try:  # pragma: no cover - 환경에 따라 다름
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )

    HAS_CRYPTOGRAPHY = True
except ImportError:  # pragma: no cover
    HAS_CRYPTOGRAPHY = False

BACKEND = "cryptography" if HAS_CRYPTOGRAPHY else "pure-python"

# ---------------------------------------------------------------------------
# 순수 Python Ed25519 (RFC 8032 §5.1). 점은 확장 좌표 (X, Y, Z, T) 로 표현한다.
# ---------------------------------------------------------------------------
_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_I = pow(2, (_P - 1) // 4, _P)
_IDENT = (0, 1, 1, 0)


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _add(P, Q):
    X1, Y1, Z1, T1 = P
    X2, Y2, Z2, T2 = Q
    A = (Y1 - X1) * (Y2 - X2) % _P
    B = (Y1 + X1) * (Y2 + X2) % _P
    C = 2 * T1 * T2 * _D % _P
    D = 2 * Z1 * Z2 % _P
    E = B - A
    F = D - C
    G = D + C
    H = B + A
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)


def _mul(P, n: int):
    Q = _IDENT
    while n > 0:
        if n & 1:
            Q = _add(Q, P)
        P = _add(P, P)
        n >>= 1
    return Q


def _xrecover(y: int):
    xx = (y * y - 1) * _inv(_D * y * y + 1) % _P
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = x * _I % _P
    if (x * x - xx) % _P != 0:
        return None
    return x


_BY = 4 * _inv(5) % _P
_BX = _xrecover(_BY)
if _BX % 2 != 0:
    _BX = _P - _BX
_B = (_BX, _BY, 1, _BX * _BY % _P)


def _encode(P) -> bytes:
    X, Y, Z, _ = P
    zi = _inv(Z)
    x = X * zi % _P
    y = Y * zi % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decode(s: bytes):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    if y >= _P:
        return None
    x = _xrecover(y)
    if x is None:
        return None
    if x == 0 and sign == 1:
        return None
    if (x & 1) != sign:
        x = _P - x
    return (x, y, 1, x * y % _P)


def _equal(P, Q) -> bool:
    X1, Y1, Z1, _ = P
    X2, Y2, Z2, _ = Q
    return (X1 * Z2 - X2 * Z1) % _P == 0 and (Y1 * Z2 - Y2 * Z1) % _P == 0


def _expand(seed: bytes):
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def _pure_public_key(seed: bytes) -> bytes:
    a, _ = _expand(seed)
    return _encode(_mul(_B, a))


def _pure_sign(seed: bytes, msg: bytes) -> bytes:
    a, prefix = _expand(seed)
    A = _encode(_mul(_B, a))
    r = int.from_bytes(hashlib.sha512(prefix + msg).digest(), "little") % _L
    R = _encode(_mul(_B, r))
    h = int.from_bytes(hashlib.sha512(R + A + msg).digest(), "little") % _L
    s = (r + h * a) % _L
    return R + s.to_bytes(32, "little")


def _pure_verify(pub: bytes, msg: bytes, sig: bytes) -> bool:
    if len(sig) != 64 or len(pub) != 32:
        return False
    A = _decode(pub)
    R = _decode(sig[:32])
    if A is None or R is None:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= _L:
        return False
    h = int.from_bytes(hashlib.sha512(sig[:32] + pub + msg).digest(), "little") % _L
    return _equal(_mul(_B, s), _add(R, _mul(A, h)))


# ---------------------------------------------------------------------------
# 공개 인터페이스
# ---------------------------------------------------------------------------
def _public_key(seed: bytes) -> bytes:
    if HAS_CRYPTOGRAPHY:
        from cryptography.hazmat.primitives import serialization

        return Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    return _pure_public_key(seed)


def _sign(seed: bytes, msg: bytes) -> bytes:
    if HAS_CRYPTOGRAPHY:
        return Ed25519PrivateKey.from_private_bytes(seed).sign(msg)
    return _pure_sign(seed, msg)


def verify(public_key: bytes, msg: bytes, sig: bytes) -> bool:
    """서명 검증. 예외를 던지지 않고 불리언만 돌려준다."""
    if HAS_CRYPTOGRAPHY:
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(sig, msg)
            return True
        except (InvalidSignature, ValueError):
            return False
    return _pure_verify(public_key, msg, sig)


@dataclass(frozen=True)
class KeyPair:
    """서명 키. `kid` 는 진술 헤더에 실리는 키 식별자다."""

    kid: str
    seed: bytes
    public_key: bytes

    @classmethod
    def from_seed(cls, kid: str, seed: bytes) -> KeyPair:
        if len(seed) != 32:
            raise ValueError("seed must be 32 bytes")
        return cls(kid=kid, seed=seed, public_key=_public_key(seed))

    @classmethod
    def from_name(cls, kid: str, namespace: str = "itx-demo") -> KeyPair:
        """재현 가능한 데모 키. 실제 배포에서는 난수 시드를 써야 한다."""
        seed = hashlib.sha256(f"{namespace}:{kid}".encode()).digest()
        return cls.from_seed(kid, seed)

    @property
    def public_hex(self) -> str:
        return self.public_key.hex()

    def sign(self, msg: bytes) -> bytes:
        return _sign(self.seed, msg)
