"""「키 · 신뢰 기준점」 화면이 그리는 값.

두 부분으로 이루어진다.

1. **서명 키 인벤토리** — 각 역할의 키가 어떤 보관처에 있고 평문으로 노출되는가.
2. **신뢰 기준점** — U 가 무엇을 근거로 상대 키를 믿는가. 이 목록이 판정 전체의
   뿌리이므로, 비어 있는 항목을 지우지 않고 결손으로 남긴다.

값은 배포 설정에서 읽는다. 설정에 보관처 정보가 없으면 기존 동작대로 로컬 파일
키이므로 `dpapi`(Windows) 또는 `file` 로 본다 — 모르는 것을 안전하다고 적지 않는다.
"""
from __future__ import annotations

import os
from typing import Any

from .custody import Custody, LineageEvent, summarise

ROLE_PURPOSE = {
    "U": "요청 계약 서명 · 로컬 검증",
    "R": "중계 진술 서명",
    "M": "실행 영수증 서명",
    "T": "원장 트리 헤드 서명",
    "W": "목격자 일관성 증명 서명",
}


def _default_store_kind() -> str:
    return "dpapi" if os.name == "nt" else "file"


def custody_from_config(config: dict[str, Any], role: str) -> Custody:
    """한 역할의 보관 상태. `key_custody` 항목이 있으면 그것을, 없으면 로컬 파일로 본다."""
    identity = config.get("identities", {}).get(role, {})
    declared = (config.get("key_custody") or {}).get(role, {})
    store_kind = declared.get("store_kind") or _default_store_kind()
    local_role = config.get("role")
    return Custody(
        role=role,
        kid=identity.get("kid", f"{role.lower()}-unknown"),
        purpose=ROLE_PURPOSE.get(role, "서명"),
        store_kind=store_kind,
        store_detail=declared.get("store_detail", ""),
        rotation_days=int(declared.get("rotation_days", 0)),
        rotation_max=int(declared.get("rotation_max", 90)),
        sign_count=int(declared.get("sign_count", 0)),
        round_trip_ms=int(declared.get("round_trip_ms", 0)),
        # W 가 T 와 같은 호스트에 있으면 독립 목격자가 아니다 (한계 11).
        independent=bool(declared.get("independent", role != "W")),
        lineage=_lineage(config, role, store_kind, local_role),
    )


def _lineage(config: dict[str, Any], role: str, store_kind: str,
             local_role: str | None) -> list[LineageEvent]:
    """계보. 확인할 수 없는 것은 지어내지 않고 '기록 없음' 으로 둔다."""
    declared = (config.get("key_custody") or {}).get(role, {})
    events = [
        LineageEvent(
            kind="created" if store_kind in ("hsm", "kms") else "software",
            title="키 생성",
            at=declared.get("created_at", "—"),
            body=("보관처 내부에서 생성했습니다. 사설키는 생성 시점부터 외부에 존재한 적이 없습니다."
                  if store_kind in ("hsm", "kms")
                  else "소프트웨어로 생성했습니다. 참조 구현의 평가용 설정입니다."),
            meta=declared.get("created_meta", ""),
        ),
        LineageEvent(
            kind="anchored" if config.get("log_id") else "self",
            title="신뢰 기준점 등록",
            at=declared.get("anchored_at", "—"),
            body=("T 원장에 공개키를 등록했습니다."
                  if config.get("log_id")
                  else "자기 서명입니다. 상위 기준점이 없습니다."),
            meta=f"log {config['log_id']}" if config.get("log_id") else "self-signed · 상위 CA 없음",
        ),
    ]
    rotation_days = int(declared.get("rotation_days", 0))
    rotation_max = int(declared.get("rotation_max", 90))
    if rotation_days > rotation_max:
        events.append(LineageEvent(
            kind="overdue", title="회전 기한 초과", at=declared.get("rotation_due", "—"),
            body=(f"{rotation_max}일 주기를 {rotation_days - rotation_max}일 초과했습니다. "
                  "판정에는 영향이 없으나 운영 위험으로 표시합니다."),
            meta=f"초과 {rotation_days - rotation_max}일"))
    elif rotation_days:
        events.append(LineageEvent(
            kind="planned", title="회전 예정", at=declared.get("rotation_due", "—"),
            body=f"{rotation_max}일 주기. 다음 회전까지 {rotation_max - rotation_days}일 남았습니다.",
            meta=f"경과 {rotation_days}일"))
    events.append(LineageEvent(
        kind="none", title="폐기 이력", at="—",
        body="폐기 기록이 없습니다." if role != local_role else "이 기계의 현재 키입니다.",
        meta=""))
    return events


def anchors(config: dict[str, Any]) -> list[dict[str, Any]]:
    """신뢰 기준점 카드. 미실행 항목은 결손으로 남긴다 — 빈칸이나 초록이 아니다."""
    identities = config.get("identities", {})
    peers = [r for r in "RMTW" if r in identities]
    witness_independent = bool((config.get("key_custody") or {}).get("W", {}).get("independent"))
    return [
        {"title": "U 로컬 기준점 목록", "tag": "운영 중", "tone": "present",
         "body": "U 가 신뢰하는 공개키 목록입니다. 이 목록에 없는 키의 서명은 어떤 등식도 통과하지 못합니다.",
         "rows": [("항목 수", f"{len(peers)} ({' · '.join(peers)})"),
                  ("보관", "배포 설정에 고정 · 읽기 전용"),
                  ("갱신", "배포 합의 서명으로만")]},
        {"title": "T 원장 등록 영수증", "tag": "운영 중" if config.get("log_id") else "미실행",
         "tone": "present" if config.get("log_id") else "absent",
         "body": "각 키가 언제 등록되었는지를 원장 리프로 증명합니다. 키 교체 시점 이후의 서명만 유효합니다.",
         "rows": [("증명 방식", "RFC 9162 포함 증명"),
                  ("로그", str(config.get("log_id", "없음"))),
                  ("앵커", "파일 기반 모사 — 한계 6")]},
        {"title": "상위 CA · 인증 체인", "tag": "미실행", "tone": "absent",
         "body": "키를 조직 신원에 묶는 상위 체인이 없습니다. 현재는 키 자체가 최종 기준점입니다.",
         "rows": [("체인 길이", "1 (자기 서명)"), ("조직 바인딩", "not_evaluable"),
                  ("권장", "X.509 또는 SPIFFE 연동")]},
        {"title": "독립 목격자", "tag": "운영 중" if witness_independent else "미실행",
         "tone": "present" if witness_independent else "absent",
         "body": ("독립 운영 목격자가 트리 헤드를 교차 확인합니다."
                  if witness_independent
                  else "목격자가 T 와 같은 호스트에 있어 분기(split-view) 탐지가 성립하지 않습니다."),
         "rows": [("목격자 수", "1"),
                  ("운영 독립성", "있음" if witness_independent else "없음 — 한계 11"),
                  ("분기 탐지", "가능" if witness_independent else "not_evaluable")]},
    ]


def build(config: dict[str, Any]) -> dict[str, Any]:
    """화면이 그대로 쓰는 값 묶음."""
    roles = [r for r in "URMTW" if r in config.get("identities", {})]
    entries = [custody_from_config(config, role) for role in roles]
    rows = [c.to_dict() for c in entries]
    for row in rows:
        row["chain"] = _chain_for(row)
    return {
        "summary": summarise(entries),
        "keys": rows,
        "anchors": anchors(config),
        "local_role": config.get("role"),
        "note": ("판단 기준은 보관처가 아니라 평문 노출 여부입니다. "
                 "약한 보관처는 위반이 아니라 운영 위험이므로 판정 색을 쓰지 않습니다."),
    }


def _chain_for(row: dict[str, Any]) -> list[dict[str, Any]]:
    """설정만으로 그리는 서명 경로. 실제 어댑터가 붙으면 signer.signing_chain 이 대신한다."""
    exposed = row["exposed"]
    middle = ({"title": "키 파일 복호", "sub": "사용자 범위 복호", "at": "로컬"} if exposed
              else {"title": "Sign 요청", "sub": "서명 대상 전달 · TLS", "at": "네트워크"})
    inside = ({"title": "프로세스 내 서명", "sub": "사설키가 메모리에 평문 존재", "at": "이 프로세스"}
              if exposed
              else {"title": "외부 서명자 내부 서명", "sub": "사설키 반출 없음", "at": row["store_label"]})
    return [
        {"title": "해시 계산", "sub": "서명 대상 커밋", "at": "로컬", "inside": False},
        {**middle, "inside": False},
        {**inside, "inside": True},
        {"title": "서명값 회수", "sub": "64 B Ed25519", "at": "로컬", "inside": False},
    ]
