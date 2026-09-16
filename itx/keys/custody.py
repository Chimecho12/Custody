"""키 보관 형태와 평문 노출.

화면이 묻는 질문은 「어디에 보관하는가」가 아니라 **「사설키가 이 기계 밖으로
나가는가」**다. 보관처 이름(YubiKey · AWS KMS · 로컬 파일)은 그 답을 추론하기 위한
근거일 뿐이므로, 판단은 `exposure` 한 칸으로 모은다.

약한 보관처는 **위반이 아니라 운영 위험**이다. 판정 색(pass/fail)을 쓰지 않고
경고 등급으로만 표시한다 — 로컬 파일 키로 만든 서명도 암호학적으로는 유효하다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: 사설키가 서명 순간 프로세스 메모리에 평문으로 존재하는가.
EXPOSED = "plaintext_in_memory"
SEALED = "never_exposed"

#: 보관처 종류. 새 어댑터를 붙일 때 여기에만 추가한다.
STORE_KINDS = {
    "file":   {"label": "로컬 파일", "exposure": EXPOSED,
               "note": "서명 시 프로세스 메모리에 로드"},
    "dpapi":  {"label": "로컬 파일 · DPAPI", "exposure": EXPOSED,
               "note": "사용자 범위 암호화 · 서명 시 평문 로드"},
    "kms":    {"label": "원격 KMS", "exposure": SEALED,
               "note": "해시만 전송 · 서명은 KMS 내부"},
    "hsm":    {"label": "HSM · 스마트카드", "exposure": SEALED,
               "note": "토큰 내부 서명 · 반출 불가"},
}

#: 기본 회전 주기. 초과는 판정이 아니라 운영 경고다.
DEFAULT_ROTATION_DAYS = 90


@dataclass
class LineageEvent:
    """키 수명 주기의 한 사건. 요청 판정과는 다른 시간축에 있다."""

    kind: str          # created · anchored · rotated · overdue · revoked · planned
    title: str
    at: str            # ISO 날짜 문자열, 또는 '—'
    body: str
    meta: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "title": self.title, "at": self.at,
                "body": self.body, "meta": self.meta}


@dataclass
class Custody:
    """한 서명 키의 보관 상태."""

    role: str
    kid: str
    purpose: str
    store_kind: str
    store_detail: str = ""
    rotation_days: int = 0
    rotation_max: int = DEFAULT_ROTATION_DAYS
    sign_count: int = 0
    #: 원격 서명 1회당 왕복 지연(ms). 0 이면 로컬 서명이라 왕복이 없다.
    round_trip_ms: int = 0
    lineage: list[LineageEvent] = field(default_factory=list)
    independent: bool = True

    def __post_init__(self) -> None:
        if self.store_kind not in STORE_KINDS:
            raise ValueError(f"알 수 없는 보관처 종류: {self.store_kind}")

    @property
    def exposure(self) -> str:
        return STORE_KINDS[self.store_kind]["exposure"]

    @property
    def exposed(self) -> bool:
        return self.exposure == EXPOSED

    @property
    def overdue_days(self) -> int:
        return max(0, self.rotation_days - self.rotation_max)

    @property
    def store_label(self) -> str:
        detail = self.store_detail or STORE_KINDS[self.store_kind]["label"]
        return detail

    def boundary_note(self) -> str:
        """원격 서명 경로 그림 아래에 붙는 한 문장. 이 화면의 결론이다."""
        if self.exposed:
            return ("굵은 테두리 구간에서 사설키가 프로세스 메모리에 평문으로 존재합니다. "
                    "이 기계가 장악되면 서명 위조가 가능합니다.")
        return ("굵은 테두리 구간 밖으로 사설키가 나가지 않습니다. "
                "이 기계가 장악되어도 서명 위조는 불가능합니다.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role, "kid": self.kid, "purpose": self.purpose,
            "store_kind": self.store_kind, "store_label": self.store_label,
            "exposure": self.exposure, "exposed": self.exposed,
            "exposure_note": STORE_KINDS[self.store_kind]["note"],
            "rotation_days": self.rotation_days, "rotation_max": self.rotation_max,
            "overdue_days": self.overdue_days, "sign_count": self.sign_count,
            "round_trip_ms": self.round_trip_ms, "independent": self.independent,
            "boundary": self.boundary_note(),
            "lineage": [e.to_dict() for e in self.lineage],
        }


def summarise(entries: list[Custody]) -> dict[str, int]:
    """화면 머리의 세 숫자. 「몇 개가 안전한가」가 아니라 「몇 개가 노출되는가」를 센다."""
    exposed = sum(1 for c in entries if c.exposed)
    return {
        "total": len(entries),
        "sealed": len(entries) - exposed,
        "exposed": exposed,
        "overdue": sum(1 for c in entries if c.overdue_days > 0),
    }
