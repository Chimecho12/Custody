"""서명 키 보관 — 사설키가 이 프로세스 밖에 있을 수 있게 한다.

한계 14 가 가리키던 자리다. 지금까지 서명은 `KeyPair.sign` 하나였고, 그것은
사설키가 언제나 이 프로세스 메모리에 있었다는 뜻이었다.
"""
from .custody import EXPOSED, SEALED, STORE_KINDS, Custody, LineageEvent, summarise
from .inventory import anchors, build, custody_from_config
from .signer import (
    SENDS_DIGEST,
    SENDS_MESSAGE,
    CommandSigner,
    LocalKeySigner,
    Signer,
    SignerError,
    signing_chain,
)

__all__ = [
    "EXPOSED",
    "SEALED",
    "SENDS_DIGEST",
    "SENDS_MESSAGE",
    "STORE_KINDS",
    "CommandSigner",
    "Custody",
    "LineageEvent",
    "LocalKeySigner",
    "Signer",
    "SignerError",
    "anchors",
    "build",
    "custody_from_config",
    "signing_chain",
    "summarise",
]
