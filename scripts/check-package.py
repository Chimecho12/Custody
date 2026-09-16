"""Check a built wheel without installing it or importing the source checkout.

Usage: python scripts/check-package.py dist/itx-0.1.0-py3-none-any.whl
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PROBE = r'''
import importlib
import json
import sys
from importlib.resources import files

sys.path.insert(0, sys.argv[1])
for name in ("itx.cose", "itx.keys", "itx.cli.runtime", "itx.runtime.desktop", "itx.sim.parties"):
    module = importlib.import_module(name)
    assert sys.argv[1] in module.__file__, module.__file__
from itx.report import build_report
from itx.report.html import stylesheet
from itx.sim.parties import Relay, ThirdParty, User

html = build_report({"results": [], "summary": {}, "scenarios": [], "q1_matrix": []})
for name in ("tokens.css", "console.css"):
    assert files("itx.ui").joinpath(name).read_text(encoding="utf-8").strip() in stylesheet()
assert html.startswith("<!DOCTYPE html>") and "__DATA__" not in html
assert "<style>" in html and "<script>" in html
print(json.dumps({"wheel_imports": "ok", "report_resources": "ok", "html_bytes": len(html.encode("utf-8"))}))
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    wheel = parser.parse_args().wheel.resolve(strict=True)
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        for required in ("itx/cose/__init__.py", "itx/keys/__init__.py", "itx/sim/parties/user.py",
                         "itx/runtime/desktop/ipc.py", "itx/ui/tokens.css", "itx/ui/console.css",
                         "itx/report/assets/report.html", "itx/report/assets/report.js", "itx/report/assets/report.css"):
            if required not in names:
                raise ValueError(f"wheel is missing {required}")
    with tempfile.TemporaryDirectory(prefix="itx-wheel-check-") as directory:
        subprocess.run([sys.executable, "-I", "-B", "-c", PROBE, str(wheel)], cwd=directory, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
