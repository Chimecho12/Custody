"""Bounded evidence queue and retry behavior."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from itx.ts import RegistrationReceipt, ServiceUnavailable

from ..context import SimContext
from .third_party import ThirdParty


@dataclass
class QueueItem:
    kind: str  # "statement" | "private"
    sub: str
    payload: Any
    enqueued_at: int


class EvidenceQueue:
    def __init__(self, ctx: SimContext, owner: str, capacity: int = 100) -> None:
        self.ctx = ctx
        self.owner = owner
        self.capacity = capacity
        self.items: list[QueueItem] = []
        self.dropped: list[dict[str, Any]] = []
        self.receipts: dict[str, RegistrationReceipt] = {}  # statement_hash -> receipt
        # 보관 영수증. 감사자가 '약속된 항목이 지금도 로그에 있는가' 를 검사하는 유일한 근거다.
        self.held: list[dict[str, Any]] = []

    def enqueue(self, kind: str, sub: str, payload: Any) -> None:
        self.items.append(QueueItem(kind, sub, payload, self.ctx.now()))
        while len(self.items) > self.capacity:
            drop = self.items.pop(0)
            info = {"dropped_kind": drop.kind, "enqueued_at": drop.enqueued_at,
                    "content_type": getattr(drop.payload, "content_type", None)}
            self.dropped.append({"sub": drop.sub, **info})
            self.ctx.record(self.owner, "evidence_dropped", drop.sub, reason="queue saturated", **info)

    def flush(self, third_party: ThirdParty) -> int:
        """가능한 만큼 제출한다. T 가 죽어 있으면 남겨 둔다. 제출 수를 돌려준다."""
        sent = 0
        while self.items:
            item = self.items[0]
            try:
                if item.kind == "statement":
                    rc = third_party.submit(item.payload, self.ctx.now())
                    self.receipts[item.payload.statement_hash] = rc
                    self.held.append({"receipt": rc.to_dict(), "statement_hash": item.payload.statement_hash,
                                      "sub": item.sub, "content_type": item.payload.content_type, "holder": self.owner})
                    self.ctx.record(self.owner, "evidence_registered", item.sub,
                                    content_type=item.payload.content_type, leaf_index=rc.leaf_index,
                                    registered_at=rc.registered_at, queued_ms=self.ctx.now() - item.enqueued_at)
                else:
                    third_party.receive_private(item.sub, item.payload, self.ctx.now())
                    self.ctx.record(self.owner, "private_evidence_delivered", item.sub)
            except ServiceUnavailable:
                self.ctx.record(self.owner, "evidence_queued", item.sub, pending=len(self.items),
                                reason="third party unavailable")
                break
            self.items.pop(0)
            sent += 1
        return sent
