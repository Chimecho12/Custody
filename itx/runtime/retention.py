"""Explicit, previewed local content expiry; signed evidence and decisions remain."""
from .auditing import fingerprint
from .common import canonical_json, now_ms, seal


def pending_subs(agent):
    return {v.get("sub") or v.get("statement", {}).get("sub") for _, v in agent.store.pending()}


def preview(agent):
    cutoff = now_ms() - agent.config.get("retention_days", 30) * 86400000
    pending = pending_subs(agent)
    selected, withheld = [], 0
    for key, record in agent.store.items("request:"):
        if record["started_at"] >= cutoff or record.get("content_pruned_at"):
            continue
        if record["state"] == "pending" or record["sub"] in pending:
            withheld += 1
            continue
        selected.append({"key": key, "hash": fingerprint(record)})
    plan = {"records": selected, "created_at": now_ms(), "cutoff": cutoff}
    token = fingerprint(plan)
    agent.store.put("retention-preview", {**plan, "token": token})
    return {"token": token, "count": len(selected), "withheld_pending": withheld,
            "retention_days": agent.config.get("retention_days", 30),
            "effect": "수용·격리 본문과 로컬 비공개 감사 입력을 삭제합니다. 서명 증거·집행 기록은 유지합니다."}


def apply(agent, token):
    plan = agent.store.get("retention-preview")
    if not plan or token != plan["token"] or now_ms() - plan["created_at"] > 300000:
        raise ValueError("새 보관 정리 미리보기가 필요합니다.")
    pending = pending_subs(agent)
    changes, salts = [], set()
    for item in plan["records"]:
        record = agent.store.get(item["key"])
        if fingerprint(record) != item["hash"] or record["sub"] in pending:
            raise ValueError("기록이 변경되었습니다. 정리 대상을 다시 확인하세요.")
        if record.get("private"):
            salts.add(record["private"]["salt"])
        record.pop("private", None)
        record.pop("quarantined_body", None)
        record.update(response=None, content_pruned_at=now_ms())
        changes.append((item["key"], record))
    versions = [key for key, value in agent.store.items("private-version:") if value["salt"] in salts]
    with agent.store.lock, agent.store.db:
        for key, value in changes:
            agent.store.db.execute("UPDATE kv SET value=? WHERE key=?", (seal(canonical_json(value)), key))
        for key in versions:
            agent.store.db.execute("DELETE FROM kv WHERE key=?", (key,))
        agent.store.db.execute("DELETE FROM kv WHERE key='retention-preview'")
    return {"pruned_records": len(changes), "private_versions_removed": len(versions),
            "forensic_erasure_guaranteed": False}
