"""추가 전용 투명성 로그와 등록 영수증.

- 등록 정책(RFC 9943 §5.1.1): 서명 검증, sub 형식, content_type, 발행자 권한, 스키마.
  정책 자체를 0번 진술로 등록한다. 키 소유 확인(kid↔iss)과 발행자 권한(iss↔content_type)은
  다른 검사다. 전자만 하면 신뢰 목록에 오른 중개자가 자기 키로 모델 영수증·판정을 서명할 수 있다.
- 등록 영수증(RFC 9942 의 COSE Receipt 에 대응): 리프 인덱스·트리 크기·루트·포함 증명·
  등록 시각을 TS 키로 서명. 등록 시각은 "늦어도 이 시각에 존재했다"는 상한이다.
- 같은 (iss, sub, content_type) 의 재등록은 정정 진술로 허용한다 (§6.3).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from itx.crypto import KeyPair, canonical_json, verify
from itx.statements import CT_POLICY, CT_VERDICT, SignedStatement, issue, validate_payload

from .merkle import MerkleTree, leaf_hash, verify_inclusion

#: TS 자신이 낼 수 있는 진술. 정책(0번)과 판정뿐이다.
TS_CONTENT_TYPES = (CT_POLICY, CT_VERDICT)


class RegistrationRefused(Exception):
    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass
class RegistrationReceipt:
    log_id: str
    leaf_index: int
    tree_size: int
    root_hash: str
    leaf_hash: str
    registered_at: int
    ts_kid: str
    inclusion_proof: list[str] = field(default_factory=list)
    signature: str = ""

    def signed_bytes(self) -> bytes:
        return canonical_json(
            {
                "log_id": self.log_id,
                "leaf_index": self.leaf_index,
                "tree_size": self.tree_size,
                "root_hash": self.root_hash,
                "leaf_hash": self.leaf_hash,
                "registered_at": self.registered_at,
                "ts_kid": self.ts_kid,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "log_id": self.log_id,
            "leaf_index": self.leaf_index,
            "tree_size": self.tree_size,
            "root_hash": self.root_hash,
            "leaf_hash": self.leaf_hash,
            "registered_at": self.registered_at,
            "ts_kid": self.ts_kid,
            "inclusion_proof": list(self.inclusion_proof),
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RegistrationReceipt:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__})  # type: ignore[arg-type]


def verify_receipt(receipt: RegistrationReceipt, statement: SignedStatement, ts_public_key: bytes) -> tuple[bool, str]:
    """영수증 서명과 포함 증명을 검사한다. (ok, reason)"""
    if not verify(ts_public_key, receipt.signed_bytes(), bytes.fromhex(receipt.signature or "00")):
        return False, "receipt signature invalid"
    lh = leaf_hash(statement.leaf_bytes())
    if lh.hex() != receipt.leaf_hash:
        return False, "leaf hash mismatch (statement differs from registered bytes)"
    ok = verify_inclusion(
        receipt.leaf_index,
        receipt.tree_size,
        lh,
        [bytes.fromhex(p) for p in receipt.inclusion_proof],
        bytes.fromhex(receipt.root_hash),
    )
    return (True, "ok") if ok else (False, "inclusion proof invalid")


@dataclass
class LogEntry:
    index: int
    statement: SignedStatement
    registered_at: int
    leaf_hash: str


class TransparencyLog:
    def __init__(self, log_id: str, key: KeyPair, policy: dict[str, Any], now: int) -> None:
        self.log_id = log_id
        self.key = key
        self.tree = MerkleTree()
        self.entries: list[LogEntry] = []
        self.policy = policy
        self.ts_iss = policy["ts_iss"]
        self._sub_re = re.compile(policy["sub_pattern"])
        self._allowed_ct = set(policy["allowed_content_types"]) | {CT_POLICY}
        # kid -> (iss, public_key)
        self.trusted: dict[str, tuple[str, bytes]] = {
            kid: (info["iss"], bytes.fromhex(info["public_key"])) for kid, info in policy["trusted_keys"].items()
        }
        self.trusted[key.kid] = (self.ts_iss, key.public_key)
        # iss -> 그 발행자가 낼 수 있는 진술 유형. TS 자신은 정책·판정만 낸다.
        self.issuer_content_types: dict[str, tuple[str, ...]] = {
            iss: tuple(cts) for iss, cts in policy["issuer_content_types"].items()
        }
        self.issuer_content_types[self.ts_iss] = TS_CONTENT_TYPES
        self.trust_keys_version = f"{log_id}/keys-v{policy['version']}"
        self.policy_statement = issue(
            key, iss=self.ts_iss, sub=f"urn:itx:policy:{log_id}", content_type=CT_POLICY,
            payload=policy, issued_at=now,
        )
        self.policy_hash = self.policy_statement.statement_hash
        self._append(self.policy_statement, now)

    # -- 등록 ------------------------------------------------------------------
    def check_policy(self, stmt: SignedStatement) -> list[str]:
        errors: list[str] = []
        if stmt.content_type not in self._allowed_ct:
            errors.append(f"content_type not allowed: {stmt.content_type}")
        if not self._sub_re.match(stmt.sub):
            errors.append(f"sub does not match policy pattern: {stmt.sub}")
        key = self.trusted.get(stmt.kid)
        if key is None:
            errors.append(f"unknown kid {stmt.kid}")
        else:
            iss, pub = key
            if iss != stmt.iss:
                errors.append(f"kid {stmt.kid} is not bound to iss {stmt.iss}")
            elif not stmt.verify_with(pub):
                errors.append("signature invalid")
        # 키 소유와 별개로, 그 발행자가 이 유형의 진술을 낼 권한이 있는가.
        if stmt.content_type not in self.issuer_content_types.get(stmt.iss, ()):
            errors.append(f"iss {stmt.iss} may not issue {stmt.content_type}")
        errors.extend(validate_payload(stmt.content_type, stmt.payload))
        return errors

    def register(self, stmt: SignedStatement, registered_at: int) -> RegistrationReceipt:
        errors = self.check_policy(stmt)
        if errors:
            raise RegistrationRefused(errors)
        return self._append(stmt, registered_at)

    def _append(self, stmt: SignedStatement, registered_at: int) -> RegistrationReceipt:
        idx = self.tree.append(stmt.leaf_bytes())
        lh = self.tree.leaf(idx)
        self.entries.append(LogEntry(index=idx, statement=stmt, registered_at=registered_at, leaf_hash=lh.hex()))
        receipt = RegistrationReceipt(
            log_id=self.log_id,
            leaf_index=idx,
            tree_size=self.tree.size,
            root_hash=self.tree.root().hex(),
            leaf_hash=lh.hex(),
            registered_at=registered_at,
            ts_kid=self.key.kid,
            inclusion_proof=[p.hex() for p in self.tree.inclusion_proof(idx)],
        )
        receipt.signature = self.key.sign(receipt.signed_bytes()).hex()
        return receipt

    # -- 조회·감사 API ---------------------------------------------------------
    def tree_head(self, now: int) -> dict[str, Any]:
        head = {
            "log_id": self.log_id,
            "tree_size": self.tree.size,
            "root_hash": self.tree.root().hex(),
            "time": now,
            "ts_kid": self.key.kid,
        }
        head["signature"] = self.key.sign(canonical_json(head)).hex()
        return head

    @staticmethod
    def verify_tree_head(head: dict[str, Any], ts_public_key: bytes) -> bool:
        body = {k: v for k, v in head.items() if k != "signature"}
        return verify(ts_public_key, canonical_json(body), bytes.fromhex(head.get("signature", "00")))

    def root_at(self, size: int) -> str:
        return self.tree.root_at(size).hex()

    def consistency_proof(self, first: int, second: int | None = None) -> list[str]:
        return [p.hex() for p in self.tree.consistency_proof(first, second)]

    def inclusion_proof(self, index: int, size: int | None = None) -> list[str]:
        return [p.hex() for p in self.tree.inclusion_proof(index, size)]

    def statements_for(self, sub: str, visible_at: int | None = None) -> list[LogEntry]:
        return [
            e for e in self.entries
            if e.statement.sub == sub and (visible_at is None or e.registered_at <= visible_at)
        ]

    def export(self, now: int) -> dict[str, Any]:
        """감사자에게 넘기는 전체 재생 자료 (RFC 9943 §5.1.1.2)."""
        return {
            "log_id": self.log_id,
            "ts_kid": self.key.kid,
            "ts_public_key": self.key.public_hex,
            "ts_iss": self.ts_iss,
            "policy_hash": self.policy_hash,
            "trust_keys_version": self.trust_keys_version,
            "entries": [
                {"index": e.index, "registered_at": e.registered_at, "statement": e.statement.to_dict()}
                for e in self.entries
            ],
            "head": self.tree_head(now),
        }

    # -- 악성 운영자 모사 (시나리오 전용) --------------------------------------
    def drop_sub(self, sub: str) -> list[int]:
        """운영자가 어떤 요청의 항목을 전부 빼고 로그를 다시 꾸미는 상황. 남은 항목을 0 부터
        다시 번호 매기고 트리를 새로 계산하므로 트리·헤드 서명·재실행은 전부 자기 일관적이다.
        빠진 항목을 드러내는 것은 제출자가 보관한 등록 영수증뿐이다. 뺀 원래 인덱스를 돌려준다."""
        removed = [e.index for e in self.entries if e.statement.sub == sub]
        kept = [e for e in self.entries if e.statement.sub != sub]
        self.tree = MerkleTree()
        self.entries = []
        for e in kept:
            idx = self.tree.append(e.statement.leaf_bytes())
            self.entries.append(LogEntry(index=idx, statement=e.statement, registered_at=e.registered_at,
                                         leaf_hash=self.tree.leaf(idx).hex()))
        return removed

    def tamper_entry(self, index: int, new_statement: SignedStatement) -> None:
        """운영자가 과거 항목을 몰래 바꾸는 상황. 트리·헤드는 다시 계산되므로 트리 자체는
        깨지지 않는다. 외부 앵커와 이전에 발급된 영수증만이 변경을 드러낸다."""
        e = self.entries[index]
        e.statement = new_statement
        self.tree.replace_leaf(index, new_statement.leaf_bytes())
        e.leaf_hash = self.tree.leaf(index).hex()
