"""Operations accepted by the desktop sidecar; mirrored by the Rust allowlist."""

#: Agent 가 받는 명령. **desktop/src-tauri/src/main.rs 의 OPS 와 같아야 한다.**
#: 두 목록이 어긋나면 브라우저 미리보기에서는 멀쩡하고 설치형 앱에서만
#: "Unsupported Agent operation" 이 난다 — 가장 늦게 발견되는 종류의 어긋남이다.
#: tests/test_desktop_ipc.py 가 이 상수와 Rust 목록이 같은지 검사한다.

#: 연결·상태·등록처럼 요청 흐름 밖에서 바로 답하는 명령.
DIRECT_OPERATIONS = frozenset({
    "status", "cancel", "history", "connect", "lab", "stop_t", "start_t",
    "recipient_create", "audit_verify",
    "enroll_prepare", "enroll_propose", "enroll_endorse",
    "enroll_assemble", "enroll_inspect", "enroll_activate",
})

#: 연결된 Agent 를 거쳐 처리되는 명령.
AGENT_OPERATIONS = frozenset({
    "request", "refresh", "audit", "simulation", "simulation_matrix", "export",
    "export_evidence", "export_trust", "export_checkpoint",
    "preflight", "witness", "retention_preview", "retention_apply",
    "standards", "key_inventory", "cose_export",
})

ALLOWED_OPERATIONS = DIRECT_OPERATIONS | AGENT_OPERATIONS
