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
        self.assertEqual(emitted - set(_js_object(self.flow_ts, "CHECK_SLOT")), set(),
                         "flow.ts CHECK_SLOT 에 홉 지도 자리가 없는 검사가 있다")
        self.assertEqual(emitted - set(_js_object(self.flow_ts, "CHECK_CODE")), set(),
                         "flow.ts CHECK_CODE 에 L- 코드가 없는 검사가 있다 — 등식 번호로 그려져 T 등식처럼 읽힌다")

    def test_ledger_rewrite_replay_exists_in_both_consoles_and_is_not_marked_unimplemented(self):
        """원장형(1c) 재작성 재생은 두 콘솔에 같이 있어야 하고, 애니메이션 메모가 '미구현' 으로 남아 있으면 안 된다."""
        view = (DESKTOP / "features" / "simulation" / "view.ts").read_text(encoding="utf-8")
        for source in (self.report_js, view):
            self.assertIn("data-rw-play", source)
            self.assertIn("ledger_rewrite", source)
            self.assertNotIn("연쇄 애니메이션은 아직 만들지 않았다", source)
        self.assertIn(".rw-cell.changed", (UI / "console.css").read_text(encoding="utf-8"))

    def test_every_check_has_a_basis_and_the_screen_can_name_it(self):
        """검사 모드의 행은 등식이 아니다. 검사마다 근거 종류가 있어야 하고 화면은 그 이름을 가져야 한다.
        route_allowed·model_hash_reference 는 서명자의 자기보고를 기준값과 맞춘 것이지 U 의 계산이 아니다."""
        from itx.enforce.user_gate import B_ATTESTED, CHECK_BASIS
        gate = (ROOT / "itx" / "enforce" / "user_gate.py").read_text(encoding="utf-8")
        emitted = set(re.findall(r'put\("([a-z_]+)"', gate))
        self.assertEqual(emitted - set(CHECK_BASIS), set(), "CHECK_BASIS 에 근거 종류가 없는 검사가 있다")
        self.assertEqual(CHECK_BASIS["route_allowed"], B_ATTESTED)
        self.assertEqual(CHECK_BASIS["model_hash_reference"], B_ATTESTED)
        labels = _js_object(self.console_ts, "BASIS_LABEL")
        self.assertEqual(set(CHECK_BASIS.values()) - set(labels), set(), "console.ts BASIS_LABEL 에 이름이 없는 근거 종류가 있다")
        for required in ("estimate", "not_evaluable", "reconciled"):
            self.assertIn(required, labels)
        self.assertNotIn("1:1", self.flow_ts, "로컬 검사와 등식이 1:1 이라는 주장이 다시 들어왔다")
        view = (DESKTOP / "features" / "request" / "view.ts").read_text(encoding="utf-8")
        for text in (view, (ROOT / "desktop" / "index.html").read_text(encoding="utf-8"), self.report_js):
            self.assertNotIn("실제 지연 비율", text, "추정인 홉 배분을 실측처럼 적었다")


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
