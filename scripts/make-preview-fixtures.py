"""브라우저 UI 미리보기용 런타임 표본을 만든다 → desktop/preview/fixtures.json (커밋하지 않는다).

로컬 TLS 실험실을 실제로 띄워 요청 몇 건과 감사를 실행하고, 앱이 화면에 쓰는 공개 기록만 저장한다.
원문 격리 본문·salt·개인키는 Agent.public() 이 제외한다.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from itx.runtime.agent import Agent  # noqa: E402
from itx.runtime.lab import Lab  # noqa: E402

REQUESTS = [
    ("AI 서비스의 경로 무결성을 한 문장으로 설명해 주세요.", "protect", "normal"),
    ("응답 무결성 검사", "protect", "response_tamper"),
    ("승인 요청 결합 검사", "strict", "request_tamper"),
    ("관찰 대조군", "observe", "response_tamper"),
    ("영수증 누락", "protect", "missing_receipt"),
    ("정상 strict 요청", "strict", "normal"),
]


def main() -> int:
    out = ROOT / "desktop" / "preview" / "fixtures.json"
    with tempfile.TemporaryDirectory(prefix="itx-preview-") as temp:
        lab = Lab(Path(temp) / "deployment")
        agent = Agent(lab.start())
        try:
            for prompt, mode, scenario in REQUESTS:
                record = agent.request(prompt, mode, scenario)
                for _ in range(10):
                    try:
                        agent.refresh(record["sub"])
                        break
                    except Exception:
                        time.sleep(0.3)
            fixtures = {
                "status": {**agent.status(), "services": lab.status()},
                "history": agent.history(),
                "audit": agent.audit(),
                "preflight": agent.preflight(),
            }
        finally:
            agent.close()
            lab.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fixtures, ensure_ascii=False, indent=1), encoding="utf-8")
    print(out, f"{len(fixtures['history'])} requests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
