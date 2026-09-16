"""itx 실통신 런타임·데스크톱 사이드카 진입점 — 실제 구현은 itx/cli/runtime.py 에 있다.

PyInstaller 가 이 파일을 itx-agent.exe 로 묶는다 (scripts/build-desktop.ps1).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from itx.cli.runtime import main

if __name__ == "__main__":
    raise SystemExit(main())
