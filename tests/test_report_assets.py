"""보고서 자산(assets/)과 공통 UI 계층(itx/ui/)이 어긋나지 않는지 검사한다.

이 저장소에는 같은 '경로검증 콘솔'이 두 벌 있다 — 데스크톱 앱(TypeScript)과 HTML
보고서(인라인 스크립트). CSS 는 ui/ 하나로 합쳤지만 동작 코드는 아직 두 벌이다.
한쪽만 고쳐 두 화면이 달라지는 일이 반복됐으므로, 최소한 두 구현이 공유해야 할
상수·표가 같은 값인지는 기계가 지키게 한다.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import ClassVar

from itx.report.html import build_report, stylesheet

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "itx" / "ui"
ASSETS = ROOT / "itx" / "report" / "assets"
DESKTOP = ROOT / "desktop" / "src"


def _js_object(source: str, name: str) -> dict:
    """`const NAME = {...}` 한 줄(또는 여러 줄) 리터럴을 파이썬 dict 로 읽는다."""
    match = re.search(rf"(?:export )?const {name}(?:: [^=]+)? = (\{{.*?\}});", source, re.S)
    if match is None:
        raise AssertionError(f"{name} 리터럴을 찾지 못했다")
    body = match.group(1)
    body = re.sub(r"//[^\n]*", "", body)
    body = re.sub(r"([{,]\s*)([A-Za-z_][\w-]*)\s*:", r'\1"\2":', body)  # 따옴표 없는 키
    return json.loads(body.replace("'", '"'))


class SharedStylesheet(unittest.TestCase):
    def test_report_inlines_the_shared_layers(self):
        """보고서가 데스크톱과 같은 토큰·컴포넌트 CSS 를 실제로 담고 있어야 한다."""
        sheet = stylesheet()
        for name in ("tokens.css", "console.css"):
            sample = [line for line in (UI / name).read_text(encoding="utf-8").splitlines()
                      if line.strip() and not line.strip().startswith("/*")]
            self.assertIn(sample[-1].strip(), sheet, f"itx/ui/{name} 이 보고서에 들어가지 않았다")

    def test_desktop_imports_the_shared_layers(self):
        css = (DESKTOP / "styles" / "app.css").read_text(encoding="utf-8")
        self.assertIn("../../../itx/ui/tokens.css", css)
        self.assertIn("../../../itx/ui/console.css", css)

    def test_no_hardcoded_font_stacks_outside_tokens(self):
        """글꼴은 --sans/--mono 토큰으로만 쓴다. 인라인 스택이 다시 늘면 드리프트가 재발한다."""
        for path in (UI / "console.css", ASSETS / "report.css", DESKTOP / "styles" / "app.css"):
            self.assertNotIn("IBM Plex", path.read_text(encoding="utf-8"), f"{path.name} 에 글꼴 스택이 직접 박혀 있다")


class ConsoleParity(unittest.TestCase):
    """두 콘솔 구현이 공유해야 하는 값."""

    def setUp(self):
        self.report_js = (ASSETS / "report.js").read_text(encoding="utf-8")
        self.console_ts = (DESKTOP / "shared" / "console.ts").read_text(encoding="utf-8")
        self.flow_ts = (DESKTOP / "shared" / "flow.ts").read_text(encoding="utf-8")

    def test_timing_constants_match(self):
        pattern = r"const HOP_MS = (\d+), PROC_MS = (\d+), SIGN_MS = (\d+)"
        report = re.search(pattern, self.report_js)
        desktop = re.search(pattern, self.console_ts)
        self.assertIsNotNone(report)
        self.assertIsNotNone(desktop)
        self.assertEqual(report.groups(), desktop.groups(), "홉·처리·서명 지연 상수가 두 콘솔에서 다르다")

    def test_model_latency_table_matches(self):
        self.assertEqual(_js_object(self.report_js, "MODEL_LATENCY_MS"),
                         _js_object(self.console_ts, "MODEL_LATENCY_MS"),
                         "모델별 추론 지연 표가 두 콘솔에서 다르다")

    def test_equation_titles_match(self):
        self.assertEqual(_js_object(self.report_js, "EQ_TITLE"), _js_object(self.flow_ts, "EQ_TITLE"),
                         "등식 이름표가 두 콘솔에서 다르다")

    def test_frontend_tables_cover_every_check_the_gate_emits(self):
        """집행 모듈이 내는 검사 키는 모두 화면에 이름과 등식 자리를 가져야 한다.

        user_gate.py 에 검사를 하나 더 넣고 화면 표를 잊으면, 그 검사는 `undefined` 로
        그려지거나 홉 지도에서 사라진다. 어느 쪽도 화면에서는 '문제 없음'처럼 보인다.
        """
        gate = (ROOT / "itx" / "enforce" / "user_gate.py").read_text(encoding="utf-8")
        emitted = set(re.findall(r'put\("([a-z_]+)"', gate))
        self.assertTrue(emitted, "user_gate.py 에서 검사 키를 읽지 못했다")
        runtime_view = (DESKTOP / "features" / "request" / "view.ts").read_text(encoding="utf-8")
        self.assertEqual(emitted - set(_js_object(runtime_view, "CHECK_NAMES")), set(),
                         "runtime-view.ts CHECK_NAMES 에 이름이 없는 검사가 있다")
        self.assertEqual(emitted - set(_js_object(self.flow_ts, "CHECK_TO_EQ")), set(),
                         "flow.ts CHECK_TO_EQ 에 등식 자리가 없는 검사가 있다")


class ReportDocument(unittest.TestCase):
    BUNDLE: ClassVar[dict] = {"generated_with": {"itx_version": "0.1.0", "checker_version": "c", "seed": 1,
                                 "crypto_backend": "pure", "claim_status": "mock_result"},
              "summary": {}, "results": [], "scenarios": [], "q1_matrix": []}

    def test_standalone_and_artifact_forms(self):
        standalone = build_report(self.BUNDLE)
        artifact = build_report(self.BUNDLE, artifact=True)
        self.assertTrue(standalone.startswith("<!DOCTYPE html>"))
        self.assertFalse(artifact.startswith("<!DOCTYPE"))
        for text in (standalone, artifact):
            self.assertNotIn("__DATA__", text, "데이터 자리표시자가 남았다")
            self.assertEqual(text.count("<style>"), 1)
            self.assertEqual(text.count("<script"), text.count("</script>"))

    def test_embedded_json_cannot_close_the_script_tag(self):
        bundle = dict(self.BUNDLE, scenarios=[{"id": "S01", "title": "</script><script>alert(1)</script>"}])
        html = build_report(bundle)
        self.assertNotIn("</script><script>alert", html)
        self.assertIn("<\\/script>", html)


if __name__ == "__main__":
    unittest.main()
