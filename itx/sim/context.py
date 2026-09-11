"""시뮬레이션 시계, 난수, 시간선 기록."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

# 지연 상수 (시뮬레이션 ms). 실측이 아니라 시나리오 비교용 고정값이다.
HOP_MS = 20           # 한 홉의 네트워크 지연
RELAY_PROC_MS = 5     # 중개자 처리
SIGN_MS = 2           # 서명·해시
TS_BASE_DELAY_MS = 15  # 등록 왕복
STRICT_POLL_MS = 50   # strict 모드 폴링 간격
STRICT_DEADLINE_MS = 1500  # strict 모드 대기 기한


@dataclass
class Timeline:
    events: list[dict[str, Any]] = field(default_factory=list)

    def record(self, t: int, actor: str, kind: str, sub: str | None = None,
               attempt_id: str | None = None, **detail: Any) -> dict[str, Any]:
        ev = {
            "seq": len(self.events),
            "t": t,
            "actor": actor,
            "kind": kind,
            "sub": sub,
            "attempt_id": attempt_id,
            "detail": detail,
        }
        self.events.append(ev)
        return ev


class SimContext:
    def __init__(self, seed: int = 42, start_time: int = 0) -> None:
        self.seed = seed
        self.rng = random.Random(seed)
        self.t = start_time
        self.timeline = Timeline()

    # 시계 ----------------------------------------------------------------
    def now(self) -> int:
        return self.t

    def advance(self, ms: int) -> int:
        self.t += ms
        return self.t

    # 난수 ----------------------------------------------------------------
    def hex32(self) -> str:
        return self.rng.getrandbits(256).to_bytes(32, "big").hex()

    def short_id(self, n: int = 8) -> str:
        return self.rng.getrandbits(4 * n).to_bytes(n // 2, "big").hex()

    # 기록 ----------------------------------------------------------------
    def record(self, actor: str, kind: str, sub: str | None = None, attempt_id: str | None = None, **detail: Any):
        return self.timeline.record(self.t, actor, kind, sub, attempt_id, **detail)
