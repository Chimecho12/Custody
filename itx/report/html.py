"""artifacts/results.json → 단일 HTML 보고서.

UI 원칙 (종합노트 §9.1, 05 검토서 §8):
- 종합 위험 점수 없음. 대조군·부재를 숨기지 않음. 색은 판정에만.
- '어디가 빨간가' 보다 '무엇을 알고 무엇을 막았는가'. 구간 불일치를 가해자 확정처럼 그리지 않음.
- 등록 시각은 상한으로 표기. 모든 값에 mock_result / evaluation 배지.

두 출력 형태:
- standalone (artifacts/report.html): <!DOCTYPE html> 포함, 브라우저로 바로 연다.
- artifact (artifacts/report-artifact.html): 게시 도구가 문서 골격을 덧씌우므로 <title>·<style>·본문만 낸다.

이 모듈은 조립만 한다. 실제 화면은 `assets/` 의 일반 웹 파일이다.

    assets/report.css    보고서 전용 규칙 (공통 토큰·컴포넌트는 ui/ 에서 가져온다)
    assets/report.html   본문 골격 (빈 컨테이너와 __DATA__ 자리)
    assets/report.js     results.json 을 읽어 화면을 그리는 스크립트

`ui/` 의 두 파일은 데스크톱 앱(desktop/src/style.css)과 **같은 원본**이다. 한쪽만
고쳐 두 콘솔이 어긋나던 문제를 없애려고 분리했다. 보고서에만 필요한 규칙은
assets/report.css 에 둔다.

사건 상세(section 3)의 홉 지도·재생 컨트롤·시점 타임라인은 Claude Design 캔버스 탐색안
`경로검증 콘솔.dc.html` (옵션 1a, "경로 지도형 — 기본안")을 이 프로젝트의 실제 results.json 에
연결해 구현한 것이다. 목업의 하드코딩된 6개 시나리오·고정 3.4초 타임라인·시나리오별 수기 지정
"변조 셀" 배열은 쓰지 않는다 — 대신 전체 17개 시나리오와, 등식 엔진(E1~E12)·실제 타임라인
이벤트·게이트 결정 시각에서 그 값들을 그대로 도출한다.
"""
from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

_ASSETS = Path(__file__).resolve().parent / "assets"
_UI = Path(__file__).resolve().parents[2] / "ui"

_TITLE = "itx 경로 검증"

_FONTS = (
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;600;700'
    '&family=IBM+Plex+Mono:wght@400;500&display=swap">'
)

#: 스타일시트 조립 순서. 토큰이 먼저, 공통 컴포넌트, 보고서 전용 규칙 순이다.
_STYLESHEETS = (_UI / "tokens.css", _UI / "console.css", _ASSETS / "report.css")


@cache
def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def stylesheet() -> str:
    """보고서에 인라인되는 CSS 전문. 자산 파일 순서대로 이어 붙인다."""
    return "\n".join(_read(p).strip("\n") for p in _STYLESHEETS)


def build_report(bundle: dict[str, Any], artifact: bool = False) -> str:
    """artifact=False: 완전한 HTML 문서. artifact=True: <title>·<style>·본문만 (게시 도구가 골격을 덧씌움)."""
    data = json.dumps(bundle, ensure_ascii=False).replace("</", "<\\/")
    body = (
        _read(_ASSETS / "report.html").strip("\n").replace("__DATA__", data)
        + "\n<script>\n"
        + _read(_ASSETS / "report.js").strip("\n")
        + "\n</script>\n"
    )
    head = f"<title>{_TITLE}</title>\n{_FONTS}\n<style>\n{stylesheet()}\n</style>\n"
    if artifact:
        return head + body
    return (
        '<!DOCTYPE html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"{head}</head>\n<body>\n{body}</body>\n</html>\n"
    )
