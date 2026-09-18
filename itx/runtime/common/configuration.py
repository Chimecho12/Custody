"""Load pinned role configuration without owning storage or service lifecycles."""
from __future__ import annotations

from pathlib import Path

from .primitives import ISS, json_loads, require_crypto


def load_config(path):
    require_crypto()
    path = Path(path).resolve()
    config = json_loads(path.read_bytes())
    if config.get("version") != 1 or config.get("role") not in (*ISS, "W"):
        raise ValueError("지원하지 않는 연결 설정입니다.")
    config["config_path"] = str(path)
    config["directory"] = str(path.parent)
    for field in ("ca_file", "tls_cert", "tls_key", "tls_password_file", "deployment_file"):
        if field in config:
            config[field] = str((path.parent / config[field]).resolve())
    config["ca_files"] = {r: str((path.parent / p).resolve()) for r, p in config.get("ca_files", {}).items()}
    for role in "URMT":
        info = config["identities"][role]
        if info["iss"] != ISS[role] or len(bytes.fromhex(info["public_key"])) != 32:
            raise ValueError("잘못된 신뢰 키 설정입니다.")
    if len({config["identities"][r]["kid"] for r in ISS}) != 4 or len({config["identities"][r]["public_key"] for r in ISS}) != 4:
        raise ValueError("역할별 키는 서로 달라야 합니다.")
    if type(config.get("strict_timeout_ms")) is not int or not 100 <= config["strict_timeout_ms"] <= 10000:
        raise ValueError("strict 대기 시간은 100~10,000 ms 정수여야 합니다.")
    if type(config.get("policy_expires_at")) is not int or type(config.get("created_at")) is not int:
        raise ValueError("정책 시각은 정수여야 합니다.")
    if config["policy_expires_at"] <= config["created_at"] or type(config.get("lab")) is not bool:
        raise ValueError("정책 기간 또는 실험 구분이 잘못되었습니다.")
    if config.get("deployment_file"):
        from ..enrollment import configuration, verify_deployment
        from ..packages import read_document
        bundle = read_document(config["deployment_file"])
        verify_deployment(bundle)
        if any(config.get(k) != v for k, v in configuration(bundle).items()):
            raise ValueError("local configuration differs from the endorsed deployment")
    return config
