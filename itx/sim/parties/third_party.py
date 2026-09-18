"""Third-party registration, reconciliation and checkpoints."""
from __future__ import annotations

from typing import Any

from itx.crypto import KeyPair
from itx.reconcile import PrivateEvidence, ReconciliationEngine
from itx.statements import (
    ALL_CONTENT_TYPES,
    CT_CONTRACT,
    CT_MANIFEST,
    CT_OBSERVATION,
    CT_RECEIPT,
    CT_RELAY,
    CT_VERDICT,
    SignedStatement,
    issue,
)
from itx.statements.schemas import policy_payload
from itx.ts import CheckpointAnchor, RegistrationReceipt, ServiceUnavailable, TransparencyLog, TransparencyService

from ..context import TS_BASE_DELAY_MS, SimContext

SUB_PATTERN = r"^urn:itx:(req|policy):[0-9a-zA-Z:-]+$"

#: 역할별로 낼 수 있는 진술 유형. 등록 정책에 실려 로그·대조·감사에서 함께 강제된다.
#: 중개자는 중계 진술만 낸다 — 자기 키로 모델 영수증을 서명해 'M 이 처리했다' 를
#: 만들어 낼 수 없어야 한다.
ROLE_CONTENT_TYPES: dict[str, tuple[str, ...]] = {
    "U": (CT_CONTRACT, CT_OBSERVATION, CT_MANIFEST),
    "R": (CT_RELAY,),
    "M": (CT_RECEIPT,),
}


class ThirdParty:
    def __init__(
        self,
        ctx: SimContext,
        key: KeyPair,
        party_keys: dict[str, tuple[str, KeyPair]],  # role -> (iss, key)
        reference_model_hashes: dict[str, str],
        anchor: CheckpointAnchor | None = None,
        misjudge: bool = False,
        down: bool = False,
        extra_delay_ms: int = 0,
    ) -> None:
        self.ctx = ctx
        self.key = key
        self.iss = "urn:itx:party:third-party"
        trusted = {k.kid: {"iss": iss, "public_key": k.public_hex} for iss, k in party_keys.values()}
        issuer_content_types = {iss: list(ROLE_CONTENT_TYPES[role]) for role, (iss, _k) in party_keys.items()}
        policy = policy_payload(
            version=1, ts_id="ts-1", ts_iss=self.iss, allowed_content_types=list(ALL_CONTENT_TYPES),
            sub_pattern=SUB_PATTERN, trusted_keys=trusted, issuer_content_types=issuer_content_types,
        )
        self.log = TransparencyLog("ts-1", key, policy, ctx.now())
        self.service = TransparencyService(self.log, base_delay_ms=TS_BASE_DELAY_MS, down=down, extra_delay_ms=extra_delay_ms)
        self.engine = ReconciliationEngine(self.log.trusted, reference_model_hashes,
                                           self.log.policy_hash, self.log.trust_keys_version,
                                           self.log.issuer_content_types)
        self.anchor = anchor or CheckpointAnchor()
        self.private: dict[str, PrivateEvidence] = {}
        self.verdicts: dict[str, list[SignedStatement]] = {}
        self.misjudge = misjudge
        self.expected_parties: dict[str, list[str]] = {}

    # 장애 제어 ------------------------------------------------------------
    def set_down(self, down: bool) -> None:
        self.service.down = down
        self.ctx.record("T", "service_down" if down else "service_up")

    @property
    def down(self) -> bool:
        return self.service.down

    # 등록 API -------------------------------------------------------------
    def submit(self, stmt: SignedStatement, now: int) -> RegistrationReceipt:
        return self.service.submit(stmt, now)

    def receive_private(self, sub: str, ev: PrivateEvidence, now: int) -> None:
        if self.service.down:
            raise ServiceUnavailable("ts-1 is down")
        self.private[sub] = ev

    def lookup_contract(self, sub: str, now: int) -> SignedStatement | None:
        for e in self.service.statements_for(sub, visible_at=now):
            if e.statement.content_type == CT_CONTRACT:
                return e.statement
        return None

    # 대조 ----------------------------------------------------------------
    def reconcile(self, sub: str, expected_parties: list[str], now: int) -> dict[str, Any]:
        entries = [e for e in self.log.statements_for(sub, visible_at=now) if e.statement.content_type != CT_VERDICT]
        ev = self.engine.gather(sub, entries, self.private.get(sub), now)
        verdict = self.engine.reconcile(ev, expected_parties)
        if self.misjudge:
            # 잘못된 판정을 내는 T 를 모사한다. 독립 재실행이 이를 발견해야 한다.
            verdict["verification_status"] = "passed"
            verdict["discrepancies"] = []
            for eq in verdict["equations"].values():
                if eq["result"] == "fail":
                    eq["result"] = "pass"
                    eq["reason"] = "(T 오판) 일치"
            verdict["established_assurance"] = "air-local" if ev.receipt is not None else "none"
        return verdict

    def request_verdict(self, sub: str, expected_parties: list[str], now: int) -> tuple[dict[str, Any], SignedStatement | None]:
        """사용자(strict 모드)가 판정을 요청한다. 결정적(passed/failed)이면 서명·등록해 돌려주고,
        증거가 아직 모이지 않았으면 미서명 미리보기만 돌려준다."""
        if self.service.down:
            raise ServiceUnavailable("ts-1 is down")
        self.expected_parties[sub] = list(expected_parties)
        verdict = self.reconcile(sub, expected_parties, now)
        self.ctx.record("T", "verdict_requested", sub, status=verdict["verification_status"],
                        completeness=verdict["completeness"], cooperation_set=verdict["cooperation_set"])
        if verdict["verification_status"] in ("passed", "failed"):
            return verdict, self._register_verdict(sub, verdict, now)
        return verdict, None

    def finalize(self, sub: str, expected_parties: list[str], now: int) -> SignedStatement:
        self.expected_parties[sub] = list(expected_parties)
        verdict = self.reconcile(sub, expected_parties, now)
        return self._register_verdict(sub, verdict, now)

    def _register_verdict(self, sub: str, verdict: dict[str, Any], now: int) -> SignedStatement:
        stmt = issue(self.key, iss=self.iss, sub=sub, content_type=CT_VERDICT, payload=verdict, issued_at=now)
        rc = self.log.register(stmt, registered_at=now)
        self.verdicts.setdefault(sub, []).append(stmt)
        self.ctx.record("T", "verdict_issued", sub, verdict["attempt_id"], status=verdict["verification_status"],
                        codes=[d["code"] for d in verdict["discrepancies"]], leaf_index=rc.leaf_index,
                        misjudge=self.misjudge)
        return stmt

    # 자기 투명성 ------------------------------------------------------------
    def checkpoint(self, now: int) -> dict[str, Any]:
        head = self.log.tree_head(now)
        rec = self.anchor.anchor(head, now)
        self.ctx.record("T", "checkpoint_anchored", tree_size=rec["tree_size"], root_hash=rec["root_hash"][:16] + "…")
        return rec

    def self_audit(self) -> dict[str, Any]:
        return {
            "log_id": self.log.log_id,
            "tree_size": self.log.tree.size,
            "root_hash": self.log.tree.root().hex(),
            "anchors": self.anchor.verify_log(self.log),
            "submissions": self.service.submissions,
            "refusals": self.service.refusals,
            "policy_hash": self.log.policy_hash,
            "checker_version": self.engine.__class__.__module__,
        }
