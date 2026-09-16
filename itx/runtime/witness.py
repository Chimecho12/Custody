"""An optional separately provisioned witness. It receives checkpoints, never prompts."""
from __future__ import annotations

from itx.crypto import canonical_json, verify
from itx.ts.merkle import verify_consistency

from .auditing import fingerprint, trust_from_config, verify_head
from .common import now_ms
from .service import Service


def verify_witness_receipt(receipt, trust):
    w = trust["identities"].get("W")
    if not w or set(receipt) != {"body", "signature"}:
        raise ValueError("no independently pinned witness identity")
    body = receipt["body"]
    if (body["profile"] != "itx-witness-receipt/1" or body["kid"] != w["kid"]
            or body["policy_hash"] != trust["policy_hash"] or type(body["sequence"]) is not int or body["sequence"] < 1
            or not verify(bytes.fromhex(w["public_key"]), canonical_json(body), bytes.fromhex(receipt["signature"]))):
        raise ValueError("invalid witness receipt")
    verify_head(body["head"], trust)
    return True


class WitnessService(Service):
    def handle(self, actor, op, payload):
        if op == "health":
            return super().handle(actor, op, payload)
        with self.lock:
            if op == "witness_status":
                return {"last_receipt": self.store.get("latest"), "scope": "checkpoints_only"}
            if op != "witness":
                raise ValueError("unsupported witness operation")
            trust = trust_from_config(self.config)
            head = payload["head"]
            verify_head(head, trust)
            if not now_ms() - 300000 <= head["time"] <= now_ms() + 5000:
                raise ValueError("stale or future checkpoint")
            old = self.store.get("latest")
            if old:
                before = old["body"]["head"]
                if head["tree_size"] < before["tree_size"]:
                    raise ValueError("checkpoint rollback")
                if head["tree_size"] == before["tree_size"]:
                    if head["root_hash"] != before["root_hash"]:
                        raise ValueError("T presented conflicting roots for one tree size")
                    return old
                proof = self.peer.call("T", "consistency", {"first": before["tree_size"], "second": head["tree_size"]})["proof"]
                if not verify_consistency(before["tree_size"], head["tree_size"], bytes.fromhex(before["root_hash"]),
                        bytes.fromhex(head["root_hash"]), [bytes.fromhex(p) for p in proof]):
                    raise ValueError("T history conflicts with the witnessed checkpoint")
            sequence = old["body"]["sequence"] + 1 if old else 1
            if sequence > self.config.get("max_log_entries", 100000):
                raise ValueError("witness ledger capacity reached")
            body = {"profile": "itx-witness-receipt/1", "kid": self.key.kid, "head": head,
                    "policy_hash": trust["policy_hash"], "observed_at": now_ms(), "sequence": sequence,
                    "previous_receipt_hash": fingerprint(old) if old else None}
            receipt = {"body": body, "signature": self.key.sign(canonical_json(body)).hex()}
            # Both writes commit together, so a crash cannot lose the ledger's head.
            from .common import seal
            with self.store.lock, self.store.db:
                for key in ("latest", f"receipt:{sequence:012d}"):
                    self.store.db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, seal(canonical_json(receipt))))
            return receipt
