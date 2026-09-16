"""결정적 모형 모델. 실제 LLM 이 아니다 (`mock`).

원문을 그대로 처리하는 결정적 모형으로 증거·집행의 정확성을 먼저 검증한다 (05 검토서 §10.1).
소형 실제 모델 연동은 후속 단계다. 모형 결과와 실제 모델 결과는 구별해 표기한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from itx.crypto import sha256_hex

_INJECT_RE = re.compile(r"\[\[INJECT:([^\]]+)\]\]")


@dataclass(frozen=True)
class MockModel:
    model_id: str
    version: str
    style: str  # "full" | "small"
    latency_ms: int

    @property
    def manifest_hash(self) -> str:
        """아티팩트 매니페스트 해시 모사 (sha256-manifest). 실행 계산의 식별자가 아니다."""
        return sha256_hex(f"mock-model-manifest:{self.model_id}:{self.version}:{self.style}".encode())

    def infer(self, request: dict[str, Any]) -> dict[str, Any]:
        text = str(request.get("input", ""))
        clean = _INJECT_RE.sub("", text).strip()
        output = (f"[{self.model_id}] 요약: {clean[:60]}" if self.style == "full"
                  else f"[{self.model_id}] 짧은 요약: {clean[:20]}")
        if "system" in request:
            output += f" (system 적용: {str(request['system'])[:24]})"
        resp: dict[str, Any] = {
            "model": self.model_id,
            "output": output,
            "usage": {"input_chars": len(text), "output_chars": len(output)},
        }
        # 교육용 모형: 문서에 심어진 지시를 '따르는' 취약한 모델을 흉내낸다.
        # 실제 LLM 의 행동이 아니라, 무결성 검증과 내용·행동 정책이 별개임을 보이기 위한 장치다.
        m = _INJECT_RE.search(text)
        if m:
            directive = m.group(1).strip()
            if directive.upper().startswith("SEND"):
                parts = directive.split()
                resp["tool_call"] = {"name": "send", "args": parts[1:] if len(parts) > 1 else []}
        return resp


DEFAULT_MODELS: dict[str, MockModel] = {
    "model-A": MockModel("model-A", "2026.09", "full", latency_ms=200),
    "model-A-small": MockModel("model-A-small", "2026.09", "small", latency_ms=80),
    "model-B": MockModel("model-B", "2026.08", "full", latency_ms=150),
}


def reference_hashes(models: dict[str, MockModel] | None = None) -> dict[str, str]:
    models = models or DEFAULT_MODELS
    return {mid: m.manifest_hash for mid, m in models.items()}
