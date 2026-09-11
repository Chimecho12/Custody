"""진술 7종의 페이로드 스키마와 생성기.

설계 문서 v2 §4 의 진술 5종에 05 검토서가 요구한 두 가지를 더했다.
- 요청 진술 → **요청 계약**: 허용 모델·폴백·변환·만료를 사용자가 전송 전에 서명 (§4.4, §6).
- **응답 수신 진술**(observation): 사용자가 실제로 받은 응답의 커밋 (§4.12).

모든 해시 값은 솔트 커밋이다 (§4.6). 모델 영수증의 security_mode 는 "evaluation" 만
허용하며 "production" 을 만드는 코드 경로는 없다.
"""
from __future__ import annotations

from typing import Any

from itx import PROFILE_VERSION
from .envelope import (
    CT_CONTRACT, CT_RELAY, CT_RECEIPT, CT_OBSERVATION, CT_MANIFEST, CT_VERDICT, CT_POLICY,
    ALL_CONTENT_TYPES,
)

HEX32 = 64  # 32바이트 = 16진 64자

REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    CT_CONTRACT: (
        "profile", "attempt_id", "session_id", "session_seq", "nonce", "req_commit",
        "requested_model", "allowed_models", "fallback_policy",
        "allowed_request_transforms", "allowed_response_transforms",
        "relay_id", "expires_at", "client_time", "enforcement_mode",
    ),
    CT_RELAY: (
        "profile", "attempt_id", "in_commit", "out_commit", "request_transform_id",
        "upstream_id", "upstream_model", "resp_in_commit", "resp_out_commit",
        "response_transform_id", "policy_version", "policy_decision",
        "nonce_forwarded", "salt_forwarded", "relay_seq",
    ),
    CT_RECEIPT: (
        "profile", "cti", "attempt_id", "request_commit", "response_commit",
        "model_id", "model_version", "model_hash", "model_hash_scheme", "eat_nonce",
        "security_mode", "attestation", "execution_time_ms", "pre_exec_check", "decision",
    ),
    CT_OBSERVATION: (
        "profile", "attempt_id", "resp_commit", "received_at",
        "inline_receipt_hash", "inline_relay_hash",
    ),
    CT_MANIFEST: ("profile", "session_id", "attempts", "closed_at", "prev_manifest_hash"),
    CT_VERDICT: (
        "profile", "attempt_id", "verification_status", "established_assurance",
        "deployment_mode", "cooperation_set", "completeness", "equations",
        "discrepancies", "evidence_refs", "policy_hash", "checker_version",
        "trust_keys_version", "threat_model",
    ),
    CT_POLICY: (
        "profile", "version", "ts_id", "ts_iss", "allowed_content_types", "sub_pattern",
        "trusted_keys", "issuer_content_types",
    ),
}

POLICY_DECISIONS = ("forwarded", "refused", "fallback", "error")
VERIFICATION_STATUSES = ("passed", "failed", "insufficient_evidence")
ASSURANCE_LEVELS = ("none", "air-local")  # TEE 값은 타입 수준에서 존재하지 않는다.
COMPLETENESS = ("complete", "gap", "not_observable")
ENFORCEMENT_MODES = ("observe", "protect", "strict")
FALLBACK_POLICIES = ("none", "declared_only")


def _is_hex(v: Any, n: int) -> bool:
    if not isinstance(v, str) or len(v) != n:
        return False
    try:
        bytes.fromhex(v)
        return True
    except ValueError:
        return False


def validate_payload(content_type: str, payload: dict[str, Any]) -> list[str]:
    """스키마 위반 목록을 돌려준다. 빈 목록이면 통과."""
    errors: list[str] = []
    required = REQUIRED_FIELDS.get(content_type)
    if required is None:
        return [f"unknown content_type {content_type}"]
    for k in required:
        if k not in payload:
            errors.append(f"missing field {k}")
    if errors:
        return errors
    if not str(payload["profile"]).startswith(PROFILE_VERSION):
        errors.append(f"profile must start with {PROFILE_VERSION}")

    if content_type == CT_CONTRACT:
        if not _is_hex(payload["nonce"], HEX32):
            errors.append("nonce must be 32-byte hex")
        if not _is_hex(payload["req_commit"], HEX32):
            errors.append("req_commit must be 32-byte hex")
        if payload["fallback_policy"] not in FALLBACK_POLICIES:
            errors.append("bad fallback_policy")
        if payload["enforcement_mode"] not in ENFORCEMENT_MODES:
            errors.append("bad enforcement_mode")
        if payload["requested_model"] not in payload["allowed_models"]:
            errors.append("requested_model must be in allowed_models")
    elif content_type == CT_RELAY:
        for k in ("in_commit", "out_commit"):
            if not _is_hex(payload[k], HEX32):
                errors.append(f"{k} must be 32-byte hex")
        for k in ("resp_in_commit", "resp_out_commit", "nonce_forwarded"):
            if payload[k] is not None and not _is_hex(payload[k], HEX32):
                errors.append(f"{k} must be 32-byte hex or null")
        if payload["policy_decision"] not in POLICY_DECISIONS:
            errors.append("bad policy_decision")
    elif content_type == CT_RECEIPT:
        if payload["security_mode"] != "evaluation":
            errors.append("security_mode must be 'evaluation' in this project")
        for k in ("request_commit", "response_commit", "model_hash"):
            if payload[k] is not None and not _is_hex(payload[k], HEX32):
                errors.append(f"{k} must be 32-byte hex")
        if payload["eat_nonce"] is not None and not _is_hex(payload["eat_nonce"], HEX32):
            errors.append("eat_nonce must be 32-byte hex or null")
        att = payload["attestation"]
        if not isinstance(att, dict) or att.get("kind") != "mock":
            errors.append("attestation.kind must be 'mock' (no real TEE in this version)")
        if payload["decision"] not in ("served", "refused"):
            errors.append("bad decision")
    elif content_type == CT_OBSERVATION:
        if not _is_hex(payload["resp_commit"], HEX32):
            errors.append("resp_commit must be 32-byte hex")
    elif content_type == CT_VERDICT:
        if payload["verification_status"] not in VERIFICATION_STATUSES:
            errors.append("bad verification_status")
        if payload["established_assurance"] not in ASSURANCE_LEVELS:
            errors.append("bad established_assurance")
        if payload["deployment_mode"] != "evaluation":
            errors.append("deployment_mode must be 'evaluation'")
        if payload["completeness"] not in COMPLETENESS:
            errors.append("bad completeness")
    elif content_type == CT_POLICY:
        if not isinstance(payload["trusted_keys"], dict):
            errors.append("trusted_keys must be a map kid -> {iss, public_key}")
        ict = payload["issuer_content_types"]
        if not isinstance(ict, dict):
            errors.append("issuer_content_types must be a map iss -> [content_type]")
        else:
            for iss, cts in ict.items():
                if not isinstance(cts, list) or any(c not in ALL_CONTENT_TYPES for c in cts):
                    errors.append(f"issuer_content_types[{iss}] must list known content types")
    return errors


# ---------------------------------------------------------------------------
# 페이로드 생성기. 시뮬레이터와 당사자 구현이 공통으로 쓴다.
# ---------------------------------------------------------------------------
def contract_payload(
    *, attempt_id: str, session_id: str, session_seq: int, nonce: str, req_commit: str,
    requested_model: str, allowed_models: list[str], fallback_policy: str,
    allowed_request_transforms: list[str], allowed_response_transforms: list[str],
    relay_id: str, expires_at: int, client_time: int, enforcement_mode: str,
) -> dict[str, Any]:
    return {
        "profile": f"{PROFILE_VERSION}/contract",
        "attempt_id": attempt_id,
        "session_id": session_id,
        "session_seq": session_seq,
        "nonce": nonce,
        "req_commit": req_commit,
        "requested_model": requested_model,
        "allowed_models": list(allowed_models),
        "fallback_policy": fallback_policy,
        "allowed_request_transforms": list(allowed_request_transforms),
        "allowed_response_transforms": list(allowed_response_transforms),
        "relay_id": relay_id,
        "expires_at": expires_at,
        "client_time": client_time,
        "enforcement_mode": enforcement_mode,
    }


def relay_payload(
    *, attempt_id: str, in_commit: str, out_commit: str, request_transform_id: str,
    upstream_id: str, upstream_model: str, resp_in_commit: str | None, resp_out_commit: str | None,
    response_transform_id: str, policy_version: str, policy_decision: str,
    nonce_forwarded: str | None, salt_forwarded: bool, relay_seq: int,
) -> dict[str, Any]:
    return {
        "profile": f"{PROFILE_VERSION}/relay",
        "attempt_id": attempt_id,
        "in_commit": in_commit,
        "out_commit": out_commit,
        "request_transform_id": request_transform_id,
        "upstream_id": upstream_id,
        "upstream_model": upstream_model,
        "resp_in_commit": resp_in_commit,
        "resp_out_commit": resp_out_commit,
        "response_transform_id": response_transform_id,
        "policy_version": policy_version,
        "policy_decision": policy_decision,
        "nonce_forwarded": nonce_forwarded,
        "salt_forwarded": bool(salt_forwarded),
        "relay_seq": relay_seq,
    }


def receipt_payload(
    *, cti: str, attempt_id: str, request_commit: str | None, response_commit: str | None,
    model_id: str, model_version: str, model_hash: str, eat_nonce: str | None,
    execution_time_ms: int, pre_exec_check: str, decision: str, attestation_doc_hash: str,
) -> dict[str, Any]:
    return {
        "profile": f"{PROFILE_VERSION}/receipt (AIR-02-like, evaluation only)",
        "cti": cti,
        "attempt_id": attempt_id,
        "request_commit": request_commit,
        "response_commit": response_commit,
        "model_id": model_id,
        "model_version": model_version,
        "model_hash": model_hash,
        "model_hash_scheme": "sha256-manifest",
        "eat_nonce": eat_nonce,
        "security_mode": "evaluation",
        "attestation": {"kind": "mock", "doc_hash": attestation_doc_hash, "claim_status": "mock_result"},
        "execution_time_ms": execution_time_ms,
        "pre_exec_check": pre_exec_check,
        "decision": decision,
    }


def observation_payload(
    *, attempt_id: str, resp_commit: str, received_at: int,
    inline_receipt_hash: str | None, inline_relay_hash: str | None,
    presented_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """사용자 수신 진술. `presented_receipt` 는 중개자가 사용자에게 보여 준 모델 영수증의 사본이다.
    등록된 영수증이 없을 때(재전송 등) 대조 엔진이 '사용자가 무엇을 근거로 받았는가' 를 검사하는 데 쓴다."""
    return {
        "profile": f"{PROFILE_VERSION}/observation",
        "attempt_id": attempt_id,
        "resp_commit": resp_commit,
        "received_at": received_at,
        "inline_receipt_hash": inline_receipt_hash,
        "inline_relay_hash": inline_relay_hash,
        "presented_receipt": presented_receipt,
    }


def manifest_payload(
    *, session_id: str, attempts: list[dict[str, str]], closed_at: int, prev_manifest_hash: str | None,
) -> dict[str, Any]:
    return {
        "profile": f"{PROFILE_VERSION}/manifest",
        "session_id": session_id,
        "attempts": [dict(a) for a in attempts],
        "closed_at": closed_at,
        "prev_manifest_hash": prev_manifest_hash,
    }


def policy_payload(
    *, version: int, ts_id: str, ts_iss: str, allowed_content_types: list[str],
    sub_pattern: str, trusted_keys: dict[str, dict[str, str]],
    issuer_content_types: dict[str, list[str]],
) -> dict[str, Any]:
    """`issuer_content_types` 는 발행자별로 **어떤 유형의 진술을 낼 수 있는가** 를 고정한다.

    키 소유 확인만으로는 부족하다. 신뢰 목록에 오른 중개자가 자기 키로 모델 영수증을
    서명하면 키 검증은 통과하고, 대조 엔진은 그것을 M 의 증거로 읽는다 (R 이 M 없이
    'M 이 처리했다' 를 만들어 낼 수 있다). 역할과 진술 유형의 결합을 정책에 적어
    등록과 대조 양쪽에서 강제한다."""
    return {
        "profile": f"{PROFILE_VERSION}/policy",
        "version": version,
        "ts_id": ts_id,
        "ts_iss": ts_iss,
        "allowed_content_types": list(allowed_content_types),
        "sub_pattern": sub_pattern,
        "trusted_keys": {k: dict(v) for k, v in trusted_keys.items()},
        "issuer_content_types": {k: list(v) for k, v in issuer_content_types.items()},
    }
