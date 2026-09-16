"""제3자 구현으로 하는 교차 검증.

`conformance.py` 의 벡터는 이 저장소의 구현이 스스로를 검사한 결과다. 그것만으로는
「우리 디코더가 우리 인코더를 읽는다」는 순환을 벗어나지 못한다. 표준을 지켰다는
말이 의미를 가지려면 **남이 만든 구현**이 같은 바이트를 읽어야 한다.

두 라이브러리를 쓴다. 둘 다 이 저장소가 만들지 않았고 itx 를 알지도 못한다.

    cbor2    RFC 8949 인코더·디코더. 우리 바이트를 읽고, 자기 canonical 인코더로
             다시 쓴 결과가 바이트 단위로 같은지 본다. 결정적 인코딩의 교차 확인이다.
    pycose   RFC 9052 구현. Sig_structure 를 자기 방식으로 다시 만들어 서명을
             검증한다. 우리 서명 계산이 맞는지를 우리 코드 밖에서 확인하는 유일한 길이다.

둘 다 선택 의존성이다. 없으면 `absent` 로 남고 벡터 수에는 영향을 주지 않는다.
설치는 `pip install -e .[conformance]`.

**cosign 과 pyscitt 은 쓰지 않는다.** 처음에는 화면 초안을 따라 넣으려 했지만,
cosign 은 sigstore 번들·blob 서명을 검증하는 도구라서 단독 COSE_Sign1 을 받지
않고, pyscitt 은 CCF 로 도는 SCITT 서비스를 상대로 동작하므로 파일 하나만으로는
실행할 수 없다. 돌릴 수 없는 명령을 화면에 적어 두면 검증한 것처럼 보이기만 한다.

**버전 하나를 기록해 둔다.** pycose 1.1.0 은 cbor2 6.x 와 함께 쓰면 자기가 만든
COSE_Sign1 조차 디코딩하지 못한다 (cbor2 6 이 태그 값을 tuple 로 돌려주는데
pycose 는 list 를 기대한다). 우리 인코딩 문제가 아니므로 cbor2 는 5.x 로 고정한다.
"""
from __future__ import annotations

from typing import Any

from itx.crypto import KeyPair
from itx.statements import CT_RECEIPT, issue

from . import cbor as ourcbor
from . import profile

PASS, FAIL, ABSENT = "pass", "fail", "absent"

#: 이 확인이 무엇을 대상으로 하는지 사람이 재현할 수 있게 적어 둔다.
REPRODUCE = "python runtime.py conformance --external"


def _sample() -> tuple[KeyPair, Any, bytes]:
    key = KeyPair.from_name("conformance-m", namespace="itx-conformance")
    stmt = issue(key, iss="urn:itx:party:m", sub="att-conformance-0001",
                 content_type=CT_RECEIPT, issued_at=1178,
                 payload={"in_commit": "8f12c47a", "out_commit": "3a4f91be",
                          "attempt": "att-conformance-0001", "security_mode": "evaluation",
                          "attestation": "mock"})
    return key, stmt, profile.to_sign1(key, stmt)


def _version(name: str) -> str:
    import importlib.metadata as metadata

    try:
        return metadata.version(name)
    except Exception:
        return "unknown"


def _absent(tool: str, why: str) -> dict[str, Any]:
    return {"tool": tool, "version": "—", "state": ABSENT, "checks": [],
            "note": why, "command": REPRODUCE}


def check_cbor2() -> dict[str, Any]:
    """RFC 8949 결정적 인코딩을 남의 인코더와 대조한다."""
    try:
        import cbor2
    except ImportError:
        return _absent("cbor2", "설치되지 않음 — pip install -e .[conformance]")

    _key, _stmt, signed = _sample()
    checks = []

    def record(label: str, ok: bool, detail: str = "") -> None:
        checks.append({"label": label, "state": PASS if ok else FAIL, "detail": detail})

    try:
        loaded = cbor2.loads(signed)
        record("우리 바이트를 디코딩", getattr(loaded, "tag", None) == 18,
               f"tag {getattr(loaded, 'tag', None)}")
        # canonical=True 가 RFC 8949 §4.2 의 결정적 인코딩이다. 같은 바이트가 나와야 한다.
        record("canonical 재인코딩이 바이트 동일", cbor2.dumps(loaded, canonical=True) == signed)
        record("우리 디코더와 같은 값으로 읽음",
               cbor2.loads(signed).value[2] == ourcbor.decode(signed).value[2])
    except Exception as error:
        record("실행", False, f"{type(error).__name__}: {error}")

    failed = [c for c in checks if c["state"] == FAIL]
    return {"tool": "cbor2", "version": _version("cbor2"),
            "state": FAIL if failed else PASS, "checks": checks,
            "command": REPRODUCE,
            "note": "RFC 8949 결정적 인코딩 교차 확인" if not failed else failed[0]["detail"]}


def check_pycose() -> dict[str, Any]:
    """RFC 9052 서명을 남의 구현이 검증하는지 본다. 이 확인만 순환을 벗어난다."""
    try:
        from pycose.keys import OKPKey
        from pycose.keys.curves import Ed25519
        from pycose.messages import Sign1Message
    except ImportError:
        return _absent("pycose", "설치되지 않음 — pip install -e .[conformance]")

    key, stmt, signed = _sample()
    checks = []

    def record(label: str, ok: bool, detail: str = "") -> None:
        checks.append({"label": label, "state": PASS if ok else FAIL, "detail": detail})

    try:
        cose_key = OKPKey(crv=Ed25519, x=key.public_key, optional_params={"ALG": "EDDSA"})
        message = Sign1Message.decode(signed)
        message.key = cose_key
        record("COSE_Sign1 구조 디코딩", True)
        record("서명 검증", message.verify_signature())
        record("payload 가 우리 CBOR 과 동일", message.payload == ourcbor.encode(stmt.payload))
        record("CWT 클레임(라벨 15) 보존",
               message.phdr.get(15, {}).get(2) == stmt.sub)
        # 음성 벡터: 서명 1비트를 바꾸면 거부해야 한다. 통과시키면 검증이 무의미하다.
        tampered = bytearray(signed)
        tampered[-1] ^= 0x01
        broken = Sign1Message.decode(bytes(tampered))
        broken.key = cose_key
        record("변조된 서명 거부", not broken.verify_signature())
    except Exception as error:
        record("실행", False, f"{type(error).__name__}: {error}")

    failed = [c for c in checks if c["state"] == FAIL]
    return {"tool": "pycose", "version": _version("pycose"),
            "state": FAIL if failed else PASS, "checks": checks,
            "command": REPRODUCE,
            "note": "RFC 9052 서명을 제3자 구현이 검증" if not failed else failed[0]["detail"]}


def run() -> dict[str, Any]:
    """두 도구를 돌리고 결과를 낸다. 하나라도 실패하면 주장 상태가 내려간다."""
    tools = [check_cbor2(), check_pycose()]
    states = {t["state"] for t in tools}
    if FAIL in states:
        claim, summary = "mock_result", "제3자 구현이 우리 출력을 거부했다 — 회귀다"
    elif states == {PASS}:
        claim, summary = "verified_external", "제3자 구현 2종이 우리 출력을 검증했다"
    elif PASS in states:
        claim, summary = "verified_external", "일부 도구만 설치되어 있다"
    else:
        claim, summary = "planned", "교차 검증 도구가 설치되지 않았다 — 결과 미확인"
    return {"tools": tools, "claim_status": claim, "summary": summary,
            "reproduce": REPRODUCE,
            "note": ("cosign 과 pyscitt 은 대상이 다르다 — cosign 은 sigstore 번들을, "
                     "pyscitt 은 CCF 로 도는 SCITT 서비스를 상대한다. 파일 하나로는 실행할 수 없다.")}
