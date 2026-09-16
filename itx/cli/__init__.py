"""명령줄 진입점.

두 갈래가 있고 서로 다른 것을 실행한다 — 뿌리의 `run.py` / `runtime.py` 는 이쪽을 부르는 얇은 껍데기다.

- `itx.cli.simulation` : 모의 시계 위의 시나리오 실행·보고서·독립 감사 (`python run.py`)
- `itx.cli.runtime`    : 실제 TLS 통신을 하는 런타임과 데스크톱 사이드카 (`python runtime.py`)
"""
from __future__ import annotations

import contextlib
import sys


def use_utf8() -> None:
    """Windows 콘솔·파이프로 나가는 한글이 깨지지 않게 한다. 두 CLI 가 모두 맨 앞에서 부른다."""
    for stream in (sys.stdout, sys.stderr):
        # 이미 UTF-8 이거나 재설정할 수 없는 스트림(파이프 래퍼 등)이면 그대로 둔다.
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
