"""Portable audit inputs. Trust is supplied separately, never learned from an export."""
from __future__ import annotations

from itx import CHECKER_VERSION
from itx.audit import replay_audit
from itx.crypto import canonical_json, content_hash_hex
from itx.statements import CT_POLICY, SignedStatement
from itx.ts import MerkleTree, RegistrationReceipt, TransparencyLog, verify_receipt

from .common import ISS, policy_for

MAX_AUDIT_ENTRIES = 100000
MAX_AUDIT_BYTES = 64 * 1024 * 1024


def fingerprint(value):
    return content_hash_hex(canonical_json(value))


def trust_from_config(config):
    t = config["identities"]["T"]
    policy = SignedStatement(ISS["T"], "urn:itx:policy:" + config["log_id"], CT_POLICY,
                             t["kid"], config["created_at"], policy_for(config))
    return {"profile": "itx-audit-trust/1", "log_id": config["log_id"],
            "identities": config["identities"], "policy_hash": policy.statement_hash,
            "checker_version": CHECKER_VERSION, "model_hashes": config["model_hashes"],
            "receipt_profile": 1, "deployment_hash": config.get("deployment_hash")}


def verify_head(head, trust):
    t = trust["identities"]["T"]
    if (set(head) != {"log_id", "tree_size", "root_hash", "time", "ts_kid", "signature"}
            or head["log_id"] != trust["log_id"] or head["ts_kid"] != t["kid"]
            or type(head["tree_size"]) is not int or not 1 <= head["tree_size"] <= MAX_AUDIT_ENTRIES
            or type(head["time"]) is not int
            or not TransparencyLog.verify_tree_head(head, bytes.fromhex(t["public_key"]))):
        raise ValueError("checkpoint does not match the pinned T identity")


def fetch_export(peer, trust):
    export = peer.call("T", "audit_head", {}, timeout=3)
    t = trust["identities"]["T"]
    if any(export.get(k) != v for k, v in {"log_id": trust["log_id"], "policy_hash": trust["policy_hash"],
                                          "ts_public_key": t["public_key"], "ts_iss": t["iss"], "ts_kid": t["kid"]}.items()):
        raise ValueError("audit metadata differs from the pinned identity")
    verify_head(export["head"], trust)
    entries, total = [], 0
    while len(entries) < export["head"]["tree_size"]:
        page = peer.call("T", "audit_page", {"head": export["head"], "start": len(entries), "limit": 64}, timeout=5)
        values = page["entries"]
        if (not values or page["next"] != len(entries) + len(values)
                or len(values) > 64 or page["next"] > export["head"]["tree_size"]):
            raise ValueError("invalid or incomplete audit page")
        total += len(canonical_json(values))
        if total > MAX_AUDIT_BYTES:
            raise ValueError("audit export exceeds the 64 MiB local verification limit")
        entries.extend(values)
    export["entries"] = entries
    return export


def verify_export(export, trust, *, anchors=None, private=None, private_by_hash=None, held_receipts=None):
    if trust.get("checker_version") != CHECKER_VERSION or trust.get("receipt_profile") != 1:
        raise ValueError("unsupported pinned checker or receipt profile")
    t = trust["identities"]["T"]
    if (export["log_id"] != trust["log_id"] or export["ts_public_key"] != t["public_key"]
            or export["ts_kid"] != t["kid"] or export["ts_iss"] != t["iss"]
            or export["policy_hash"] != trust["policy_hash"]):
        raise ValueError("감사 자료가 사전에 고정한 T 신원·정책과 다릅니다.")
    verify_head(export["head"], trust)
    entries = export["entries"]
    if not entries or len(entries) != export["head"]["tree_size"]:
        raise ValueError("incomplete log export")
    tree, receipt_errors = MerkleTree(), []
    for index, entry in enumerate(entries):
        stmt = SignedStatement.from_dict(entry["statement"])
        tree.append(stmt.leaf_bytes())
        if entry["index"] != index:
            raise ValueError("log indexes are not contiguous")
        if trust.get("receipt_profile") == 1:
            try:
                rc = RegistrationReceipt.from_dict(entry["receipt"])
                valid, _ = verify_receipt(rc, stmt, bytes.fromhex(t["public_key"]))
                if (not valid or rc.log_id != trust["log_id"] or rc.ts_kid != t["kid"]
                        or rc.leaf_index != index or rc.tree_size != index + 1
                        or rc.registered_at != entry["registered_at"] or rc.root_hash != tree.root().hex()):
                    raise ValueError("receipt mismatch")
            except (ValueError, KeyError, TypeError):
                receipt_errors.append(index)
    first = SignedStatement.from_dict(entries[0]["statement"])
    if first.content_type != CT_POLICY or first.statement_hash != trust["policy_hash"]:
        raise ValueError("entry zero is not the pinned policy")
    report = replay_audit(export, anchors or [], private or {}, {}, trust["model_hashes"], private_by_hash,
                          held_receipts=held_receipts or [])
    report["receipt_errors"] = receipt_errors
    report["ok"] = report["ok"] and not receipt_errors
    report["private_scope"] = "partial" if report["compared_without"] else "complete"
    report["trust_fingerprint"] = fingerprint(trust)
    return report
