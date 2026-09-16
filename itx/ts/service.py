"""등록 API 파사드 + 장애 주입.

가용성 실험(05 검토서 §7.2)을 위해 다음을 켜고 끌 수 있다.
- down: 등록 요청이 실패한다 (클라이언트 큐에 남는다).
- extra_delay_ms: 등록 지연. 등록 시각이 그만큼 늦어져 strict 모드의 대기가 길어진다.
"""
from __future__ import annotations

from typing import Any

from itx.statements import SignedStatement

from .log import LogEntry, RegistrationReceipt, TransparencyLog


class ServiceUnavailable(Exception):
    pass


class TransparencyService:
    def __init__(self, log: TransparencyLog, base_delay_ms: int = 15, down: bool = False, extra_delay_ms: int = 0) -> None:
        self.log = log
        self.base_delay_ms = base_delay_ms
        self.extra_delay_ms = extra_delay_ms
        self.down = down
        self.submissions = 0
        self.refusals = 0

    @property
    def total_delay_ms(self) -> int:
        return self.base_delay_ms + self.extra_delay_ms

    def submit(self, stmt: SignedStatement, now: int) -> RegistrationReceipt:
        if self.down:
            raise ServiceUnavailable(f"{self.log.log_id} is down")
        self.submissions += 1
        try:
            return self.log.register(stmt, registered_at=now + self.total_delay_ms)
        except Exception:
            self.refusals += 1
            raise

    def statements_for(self, sub: str, visible_at: int | None = None) -> list[LogEntry]:
        if self.down:
            raise ServiceUnavailable(f"{self.log.log_id} is down")
        return self.log.statements_for(sub, visible_at)

    def tree_head(self, now: int) -> dict[str, Any]:
        if self.down:
            raise ServiceUnavailable(f"{self.log.log_id} is down")
        return self.log.tree_head(now)
