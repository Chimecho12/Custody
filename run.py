"""itx 시뮬레이션 CLI 진입점 — 실제 구현은 itx/cli/simulation.py 에 있다.

  python run.py doctor / test / run / report / audit / all
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from itx.cli.simulation import main

if __name__ == "__main__":
    raise SystemExit(main())
