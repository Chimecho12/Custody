"""artifacts/results.json → 단일 HTML 보고서.

UI 원칙 (종합노트 §9.1, 05 검토서 §8):
- 종합 위험 점수 없음. 대조군·부재를 숨기지 않음. 색은 판정에만.
- '어디가 빨간가' 보다 '무엇을 알고 무엇을 막았는가'. 구간 불일치를 가해자 확정처럼 그리지 않음.
- 등록 시각은 상한으로 표기. 모든 값에 mock_result / evaluation 배지.

두 출력 형태:
- standalone (artifacts/report.html): <!DOCTYPE html> 포함, 브라우저로 바로 연다.
- artifact (artifacts/report-artifact.html): 게시 도구가 문서 골격을 덧씌우므로 <title>·<style>·본문만 낸다.

사건 상세(section 3)의 홉 지도·재생 컨트롤·시점 타임라인은 Claude Design 캔버스 탐색안
`경로검증 콘솔.dc.html` (옵션 1a, "경로 지도형 — 기본안")을 이 프로젝트의 실제 results.json 에
연결해 구현한 것이다. 목업의 하드코딩된 6개 시나리오·고정 3.4초 타임라인·시나리오별 수기 지정
"변조 셀" 배열은 쓰지 않는다 — 대신 전체 17개 시나리오와, 등식 엔진(E1~E12)·실제 타임라인
이벤트·게이트 결정 시각에서 그 값들을 그대로 도출한다.
"""
from __future__ import annotations

import json
from typing import Any

_TITLE = "itx 경로 검증"

_FONTS = (
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;600;700'
    '&family=IBM+Plex+Mono:wght@400;500&display=swap">'
)

_STYLE = r"""<style>
:root{
  --bg:#F2F4F7;--sunken:#F7F8FA;--card:#FFFFFF;--raised:#FFFFFF;
  --fg:#16191F;--muted:#5C6470;--line:#D9DEE6;--line-soft:#E6EAF0;--chip:#E9EDF3;
  --accent:#2F4C8A;--accent-soft:#E3EAF7;
  --pass:#1E7A4C;--fail:#B3261E;--warn:#9A6700;--na:#7A8290;
  --mark-consume:rgba(179,38,30,.10);--mark-decide:rgba(30,122,76,.12);
  --fail-soft:rgba(179,38,30,.07);
  --shadow-1:0 1px 2px rgba(16,24,40,.05),0 1px 1px rgba(16,24,40,.03);
  --shadow-2:0 4px 14px rgba(16,24,40,.10),0 1px 3px rgba(16,24,40,.06);
  /* 모션: 인과를 보이는 데만 쓴다. 길이는 세 단계로 고정한다. */
  --dur-1:110ms;--dur-2:200ms;--dur-3:320ms;
  --ease-out:cubic-bezier(.22,.61,.36,1);--ease-in-out:cubic-bezier(.4,0,.2,1);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#12151B;--sunken:#161A21;--card:#1A1E26;--raised:#1E232C;
    --fg:#E6E8EC;--muted:#98A0AC;--line:#2C323C;--line-soft:#242A33;--chip:#232934;
    --accent:#8DB0F5;--accent-soft:#1F2A40;
    --pass:#4CC38A;--fail:#F0716A;--warn:#E0B341;--na:#8B939F;
    --mark-consume:rgba(240,113,106,.14);--mark-decide:rgba(76,195,138,.14);
    --fail-soft:rgba(240,113,106,.12);
    --shadow-1:0 1px 2px rgba(0,0,0,.34);
    --shadow-2:0 6px 18px rgba(0,0,0,.44),0 1px 3px rgba(0,0,0,.30);
  }
}
:root[data-theme="dark"]{
  --bg:#12151B;--sunken:#161A21;--card:#1A1E26;--raised:#1E232C;
  --fg:#E6E8EC;--muted:#98A0AC;--line:#2C323C;--line-soft:#242A33;--chip:#232934;
  --accent:#8DB0F5;--accent-soft:#1F2A40;
  --pass:#4CC38A;--fail:#F0716A;--warn:#E0B341;--na:#8B939F;
  --mark-consume:rgba(240,113,106,.14);--mark-decide:rgba(76,195,138,.14);
  --fail-soft:rgba(240,113,106,.12);
  --shadow-1:0 1px 2px rgba(0,0,0,.34);
  --shadow-2:0 6px 18px rgba(0,0,0,.44),0 1px 3px rgba(0,0,0,.30);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font:14px/1.55 "IBM Plex Sans KR","Pretendard","Malgun Gothic","Apple SD Gothic Neo",system-ui,sans-serif}
header.itx{padding:22px 28px 18px;border-bottom:1px solid var(--line);background:var(--card)}
h1{margin:0 0 8px;font-size:22px;font-weight:700;letter-spacing:-.01em;text-wrap:balance}
h2{font-size:16px;font-weight:600;margin:32px 0 10px;padding-left:10px;border-left:3px solid var(--accent);text-wrap:balance}
h3{font-size:13px;font-weight:600;margin:16px 0 8px;color:var(--muted);letter-spacing:.02em}
main.itx{padding:8px 28px 64px;max-width:1400px}
.badges{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.badges span{padding:2px 9px;border-radius:999px;background:var(--chip);font-size:12px;color:var(--muted)}
.lede{margin:0;color:var(--muted);font-size:12.5px;max-width:78ch}
.tablewrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px;background:var(--card);font-variant-numeric:tabular-nums}
th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
th{background:var(--chip);font-weight:600}
tbody tr:hover td{background:var(--sunken)}
tbody tr.clickable{cursor:pointer}
tbody tr.clickable:hover td{background:var(--accent-soft)}
tbody tr.clickable:focus-visible td{outline:2px solid var(--accent);outline-offset:-2px}
tr.sel td{box-shadow:inset 3px 0 0 var(--accent);transition:box-shadow var(--dur-2) var(--ease-out)}
.pass{color:var(--pass);font-weight:600}.fail{color:var(--fail);font-weight:600}.na{color:var(--na)}.warn{color:var(--warn);font-weight:600}
.card{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:14px 16px;margin:10px 0;box-shadow:var(--shadow-1)}
/* 카드 안의 카드는 한 단계 내려앉는다 — 계층은 색이 아니라 명도와 그림자로만 낸다. */
.card .card{background:var(--sunken);border-color:var(--line-soft);box-shadow:none}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:12px}
.mono{font-family:"IBM Plex Mono",ui-monospace,Consolas,monospace;font-size:12px;word-break:break-all}
.muted{color:var(--muted)}
.absent{color:var(--na);font-style:italic}
.small{font-size:12px}
svg text{font-size:12px;fill:var(--fg);font-family:inherit}
.legend{display:flex;gap:16px;font-size:12px;margin-top:6px}
.tl td.mark{background:var(--mark-consume)}
.tl td.decide{background:var(--mark-decide)}
ul.tight{margin:4px 0;padding-left:18px}
ul.tight li{margin:2px 0}
code{background:var(--chip);padding:1px 4px;border-radius:3px;font-family:"IBM Plex Mono",ui-monospace,monospace}
.scroll{max-height:380px;overflow:auto;border-radius:4px}
.scroll thead th{position:sticky;top:0;z-index:1;box-shadow:inset 0 -1px 0 var(--line)}

/* --- 사건 상세 컨트롤 (경로검증 콘솔 1a) --- */
.controls{display:flex;flex-direction:column;gap:10px;align-items:stretch}
.tabrow{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.tabrow-label{font-size:11px;color:var(--muted);letter-spacing:.02em;flex:none}
.tabs{display:flex;flex-wrap:wrap;gap:6px}
.pill{font:600 11.5px "IBM Plex Mono",monospace;padding:4px 10px;border-radius:5px;cursor:pointer;
  border:1px solid var(--line);background:var(--card);color:var(--fg);line-height:1.3;
  transition:background var(--dur-1) var(--ease-out),border-color var(--dur-1) var(--ease-out),color var(--dur-1) var(--ease-out)}
.pill:hover{background:var(--accent-soft)}
.pill.on{border-color:var(--accent);background:var(--accent);color:#fff}
.pill:focus-visible,.itx-btn:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.itx-btn{font:600 12px "IBM Plex Sans KR",system-ui;padding:5px 14px;border-radius:5px;
  border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer;
  transition:background var(--dur-1) var(--ease-out),border-color var(--dur-1) var(--ease-out),opacity var(--dur-1) var(--ease-out),transform var(--dur-1) var(--ease-out)}
.itx-btn:hover{background:var(--accent-soft);border-color:var(--accent)}
.itx-btn:active{transform:translateY(1px)}
.itx-btn-accent{border-color:var(--accent);background:var(--accent);color:#fff;min-width:92px}
.itx-btn-accent:hover{background:var(--accent);color:#fff;opacity:.88}
.itx-btn-step{font-family:"IBM Plex Mono",monospace;padding:5px 9px;letter-spacing:-.04em}
.itx-btn-speed{font-family:"IBM Plex Mono",monospace;padding:5px 9px;min-width:42px}
.playctl{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.tabrow>.playctl{margin-left:auto}
.playctl:focus{outline:none}
.tlabel{font-family:"IBM Plex Mono",monospace;color:var(--muted);min-width:98px;text-align:right;display:inline-block;font-variant-numeric:tabular-nums}

/* --- 홉 지도 --- */
.hopwrap{position:relative;width:100%}
.hopwrap svg{width:100%;height:auto;display:block}
.hopwrap svg line,.hopwrap svg path{transition:stroke var(--dur-2) var(--ease-out)}
/* 패킷: 위치는 프레임마다 계산하고(전이 없음), 색만 부드럽게 넘긴다. 변조 시점의 색 전이가 사건 그 자체다. */
.packet{transition:fill var(--dur-2) var(--ease-out)}
.packettrail{transition:opacity var(--dur-2) var(--ease-out),stroke var(--dur-2) var(--ease-out);pointer-events:none}
/* 노드 도달 펄스: 1회성 fade. 판정 색이 아니라 흐름 색만 쓰고 잔상을 남기지 않는다. */
.nodehalo{opacity:0;pointer-events:none;transform-box:fill-box;transform-origin:center}
.nodehalo.pulse{animation:itx-node-pulse 620ms var(--ease-out)}
@keyframes itx-node-pulse{0%{opacity:.7;transform:scale(1)}100%{opacity:0;transform:scale(1.08)}}
.evline{transition:stroke var(--dur-3) var(--ease-out)}
/* 증거 제출 경로는 업무 데이터 경로와 다르다는 것을 흐르는 점선으로 보인다.
   재생 중이고 이미 등록된 선만 흐르며, 결손(na) 선은 어떤 경우에도 정지해 있다. */
.evline.flowing{animation:itx-evflow 1.8s linear infinite}
@keyframes itx-evflow{to{stroke-dashoffset:-16}}
.hoplabel{position:absolute;white-space:nowrap;font-family:"IBM Plex Mono",monospace;border-radius:3px;padding:0 3px;
  transition:background var(--dur-1) var(--ease-out),box-shadow var(--dur-1) var(--ease-out)}
.hoplabel.eq-hi{background:var(--accent-soft);box-shadow:0 0 0 1px var(--accent)}
/* 재생 중에만 나타나는 현재 구간 이름. 정지·완료 상태에서는 지운다. */
.packetlabel{position:absolute;white-space:nowrap;pointer-events:none;font:600 10.5px "IBM Plex Mono",monospace;color:var(--accent);
  background:var(--raised);border:1px solid var(--line);border-radius:4px;padding:1px 6px;box-shadow:var(--shadow-1)}
.packetlabel[hidden]{display:none}
/* 등식 라벨 <-> 표 양방향 연동 하이라이트. 판정 색을 바꾸지 않고 배경/테두리만 쓴다. */
tr.eq-hi td{background:var(--accent-soft)}
.eqchip.eq-hi{box-shadow:0 0 0 1px var(--accent)}
/* 해시는 눌러서 전체 값을 복사한다. */
.hashchip{position:relative;cursor:pointer;border-radius:3px;padding:0 2px;border-bottom:1px dotted var(--line);
  transition:background var(--dur-1) var(--ease-out),border-color var(--dur-1) var(--ease-out)}
.hashchip:hover{background:var(--chip);border-bottom-color:var(--accent)}
.hashchip:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.hashchip.copied::after{content:attr(data-flash);position:absolute;left:50%;bottom:calc(100% + 5px);transform:translateX(-50%);
  background:var(--fg);color:var(--bg);font:600 10px "IBM Plex Mono",monospace;padding:2px 7px;border-radius:4px;white-space:nowrap;z-index:40;
  box-shadow:var(--shadow-2);animation:itx-tip-in var(--dur-2) var(--ease-out)}
@keyframes itx-tip-in{from{opacity:0;transform:translate(-50%,3px)}to{opacity:1;transform:translate(-50%,0)}}
.legend-row{display:flex;gap:16px;font-size:11px;color:var(--muted);margin:2px 0 14px}

/* --- 증거 패널 --- */
.evrow{display:flex;align-items:center;gap:9px;padding:6px 9px;border-radius:5px;border:1px solid var(--line);background:var(--chip);
  transition:background var(--dur-3) var(--ease-out),border-color var(--dur-3) var(--ease-out)}
.evrow.arrived{background:var(--card)}
/* 등록은 '팝' 하고 튀지 않고 제자리로 안착한다. 이미 끝난 사건을 불러올 때는 붙지 않는 클래스다. */
.evrow.settling{animation:itx-ev-settle var(--dur-3) var(--ease-out)}
@keyframes itx-ev-settle{from{transform:translateX(3px)}to{transform:none}}
/* 결손 행은 어떤 상태 변화도 없다. 부재가 사건처럼 보이면 안 된다. */
.evrow.absent-row{background:var(--bg);border-style:dashed;border-color:var(--na);transition:none}
.evdot{width:8px;height:8px;border-radius:50%;flex:none;background:var(--line);transition:background var(--dur-3) var(--ease-out)}
.evrow.arrived .evdot{background:var(--pass)}
.evrow.absent-row .evdot{background:transparent;border:1px dashed var(--na);transition:none}
.evname{font:600 11.5px "IBM Plex Sans KR",system-ui;min-width:104px;flex:none}
.evdetail{font:400 10.5px "IBM Plex Mono",monospace;color:var(--muted);flex:1}
.evstate{font:500 10.5px "IBM Plex Mono",monospace;white-space:nowrap;color:var(--na);transition:color var(--dur-3) var(--ease-out)}
.evrow.arrived .evstate{color:var(--pass)}
.evrow.absent-row .evstate{transition:none}

/* --- 결론 코드 목록 --- */
.codebox{border-left:3px solid var(--line);padding:3px 0 3px 8px;margin:6px 0}

/* --- 시점 타임라인 --- */
.timebox{position:relative;height:94px;border:1px solid var(--line);border-radius:6px;background:var(--chip);overflow:hidden;
  cursor:ew-resize;touch-action:none;transition:border-color var(--dur-2) var(--ease-out)}
.timebox:hover{border-color:var(--accent)}
.timebox:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.timeaxis{position:absolute;left:0;right:0;top:37px;height:1px;background:var(--line)}
.timegap{position:absolute;top:28px;width:4%;height:19px;background:var(--chip);
  border-left:1px dashed var(--na);border-right:1px dashed var(--na)}
.timegaplabel{position:absolute;top:50px;transform:translateX(-50%);font:400 9.5px "IBM Plex Mono",monospace;
  color:var(--na);white-space:nowrap}
/* 피해 노출 구간: 단색 면이 아니라 해칭 + 라벨로 '무엇이 그 사이에 실행되었는가' 를 묻게 한다. */
.harmbar{position:absolute;top:35px;height:6px;border-top:1px solid var(--fail);border-bottom:1px solid var(--fail);
  background:repeating-linear-gradient(135deg,var(--fail) 0 2px,transparent 2px 5px)}
.harmlabel{position:absolute;left:0;top:-13px;font:600 9.5px "IBM Plex Mono",monospace;color:var(--fail);white-space:nowrap}
.harmbar.empty .harmlabel{display:none}
.playhead{position:absolute;top:2px;bottom:2px;width:2px;background:var(--accent);opacity:.55}
.playknob{position:absolute;top:-1px;left:50%;width:9px;height:9px;border-radius:50%;background:var(--accent);transform:translateX(-50%);box-shadow:var(--shadow-1)}
.timebox:hover .playhead,.timebox:focus-visible .playhead{opacity:.9}
.markline{width:1px;height:14px;background:var(--muted);margin:0 auto}
.marklabel{font:600 10px "IBM Plex Mono",monospace;white-space:nowrap;text-align:center}
.markat{font:400 9.5px "IBM Plex Mono",monospace;color:var(--na);text-align:center}

/* --- 정책/검사기 요약 띠 --- */
.stripgrid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--line);
  border:1px solid var(--line);border-radius:6px;overflow:hidden;font-size:11px}
.stripcell{background:var(--chip);padding:7px 9px}
.stripcell .k{font-size:10px;color:var(--na);letter-spacing:.03em}
.stripcell .v{font:500 11.5px "IBM Plex Mono",monospace;color:var(--fg)}

/* --- 1b 스윔레인 / 1c 원장 --- */
.gapbox{position:relative;height:44px;margin-top:4px}
.gapaxis{position:absolute;left:0;right:0;top:14px;height:1px;background:var(--line)}
.gapfill{position:absolute;top:12px;height:5px;background:var(--fail)}
.gaplabel-l{position:absolute;left:4%;top:22px;font:600 10px "IBM Plex Mono",monospace;color:var(--fail)}
.gaplabel-r{position:absolute;right:0;top:22px;font:600 10px "IBM Plex Mono",monospace;color:var(--pass);text-align:right}
.ledgerlink{font:600 12px "IBM Plex Sans KR",system-ui;color:var(--accent);cursor:pointer;background:none;border:none;padding:0;text-decoration:underline}

/* --- 1d 불확실성 표현 3종 --- */
.badge3{display:flex;gap:6px;flex-wrap:wrap}
.badge3 span{font:600 11.5px "IBM Plex Mono",monospace;padding:3px 9px;border-radius:4px}
.meter-sq{width:26px;height:13px;border-radius:2px;display:inline-block;flex:none}
.ladder-row{display:flex;gap:8px;font-size:11.5px;margin:4px 0;align-items:baseline}
.ladder-tag{font-weight:700;flex:none;min-width:44px}

/* --- 1e 애니메이션 메모 --- */
.animnote{border-left:3px solid var(--accent);padding:2px 0 2px 10px;margin:8px 0}
.animstatus{font:600 10px "IBM Plex Mono",monospace;padding:1px 6px;border-radius:3px;margin-left:6px;white-space:nowrap}

/* 축소 모션: 전이/재생 애니메이션을 모두 끈다. 재생 버튼은 최종 상태로 즉시 점프한다. */
@media (prefers-reduced-motion: reduce){*{transition:none!important;animation:none!important}}
</style>"""

_BODY = r"""<header class="itx">
<h1>독립 제3자 기반 AI 서비스 경로 검증·정책 집행 — 결과 보고서</h1>
<div class="badges" id="badges"></div>
<p class="lede">모든 수치는 결정적 모형 모델과 시뮬레이션 시계에서 나온 <b>mock_result</b> 다. 영수증은 security_mode=evaluation, 판정 보증은 최대 air-local 이며 TEE 출처를 주장하지 않는다. 등록 시각은 발생 시각의 상한이다.</p>
</header>
<main class="itx">

<h2>1. 모드별 요약 지표</h2>
<p class="small muted">분자/분모를 함께 표시한다. 탐지·사용 전 방어·피해 노출·오차단은 서로 다른 질문이다. '탐지 불가' 로 분류된 공격(공모·인젝션)은 탐지율 분모에서 제외하고 그 수를 따로 적는다.</p>
<div id="summary" class="tablewrap"></div>

<h2>2. 시나리오 × 모드</h2>
<p class="small muted">행을 클릭하면 아래 사건 상세가 바뀐다. 최종 판정은 세션 종료 후 T 가 서명·등록한 판정이다. 게이트는 사용자 측 집행 모듈의 결정이다.</p>
<div id="matrix" class="tablewrap"></div>

<h2>3. 사건 상세 — 경로 지도와 재생</h2>
<p class="small muted">경로(실선)는 업무 데이터, T 로 가는 점선은 증거·통제 경로다. 재생은 이 시도의 실제 타임라인 이벤트(요청 전송·홉 지연·추론·게이트 결정·T 판정 등록)로 구간을 나눈 것이며 임의의 데모 수치가 아니다. 기본 화면은 이미 완결된 결과를 보여 주고, 재생은 그 과정을 되짚어보는 보조 기능이다. 시점 타임라인은 끌어서 임의의 t 로 옮길 수 있고, |◀ ▶| 는 홉 경계 단위로 이동한다.</p>
<div class="card controls">
  <div class="tabrow"><span class="tabrow-label">사건</span><div id="scenarioTabs" class="tabs"></div></div>
  <div class="tabrow"><span class="tabrow-label">정책 모드</span><div id="modeTabs" class="tabs"></div>
    <div class="playctl" tabindex="-1">
      <button type="button" id="stepBackBtn" class="itx-btn itx-btn-step" title="이전 홉 (←)" aria-label="이전 홉">|◀</button>
      <button type="button" id="playBtn" class="itx-btn itx-btn-accent" title="재생·정지 (Space)">▶ 재생</button>
      <button type="button" id="stepFwdBtn" class="itx-btn itx-btn-step" title="다음 홉 (→)" aria-label="다음 홉">▶|</button>
      <button type="button" id="resetBtn" class="itx-btn" title="처음으로 (R · Home)">처음으로</button>
      <button type="button" id="speedBtn" class="itx-btn itx-btn-speed" title="재생 속도" aria-label="재생 속도">×1</button>
      <span id="tLabel" class="tlabel">t = 0 ms</span>
    </div>
  </div>
  <div class="tabrow" id="attemptRow" style="display:none"><span class="tabrow-label">시도</span><div id="attemptTabs" class="tabs"></div></div>
</div>
<div id="detail"></div>

<h2>4. Q1 — 협조 집합별 탐지 가능성</h2>
<p class="small muted">같은 위반을 협조 집합 {U, U+M, U+R, U+R+M} 에서 실행했다. 'insufficient_evidence' 는 위반이 없다는 뜻이 아니라 증거로 확립할 수 없다는 뜻이다. R 만 협조하고 M 이 없으면 종단 무결성(E10)을 세울 수 없다.</p>
<div id="q1" class="tablewrap"></div>

<h2>5. 판정 불확실성을 어떻게 보여줄 것인가</h2>
<p class="small muted">증거가 협조 수준만큼만 있을 때 '위반 없음'과 '위반을 확인할 수 없음'을 같은 칸에 섞으면 안 된다. 같은 사건을 세 가지 표현으로 비교한다 — 경로검증 콘솔 옵션 1d.</p>
<div class="card controls">
  <div class="tabrow"><span class="tabrow-label">사건</span><div id="uncScTabs" class="tabs"></div></div>
  <div class="tabrow"><span class="tabrow-label">협조 집합</span><div id="uncCoopTabs" class="tabs"></div></div>
</div>
<div id="uncertainty"></div>

<h2>6. 이 보고서가 주장하지 않는 것</h2>
<div class="card small">
<ul class="tight">
<li>중개자의 <b>기밀성 위반</b>(프롬프트 보관·학습 사용)은 어떤 등식으로도 탐지하지 못한다. 무결성·귀속·완전성만 다룬다.</li>
<li>모든 영수증은 evaluation 모드, 증명 문서는 mock 이다. 실제 TEE 위 실행을 보증하지 않는다.</li>
<li>R 과 M 이 공모해 일치하는 거짓 진술을 내면(S15) 현재 증거 구조는 위반을 보지 못한다. 위협 모델 TM1 밖이다.</li>
<li>아티팩트 해시 일치(E9)는 실행 계산의 일치가 아니다. 통계적 실행 검증은 미구현이다.</li>
<li>해시 트리와 앵커는 '신뢰 기준점 대비 변경'을 드러낼 뿐 조작 불가를 뜻하지 않는다. 앵커는 파일 기반 목격자 모사다.</li>
<li>시뮬레이션 지연은 고정 상수다. 실제 네트워크·모델 성능·가용성 수치가 아니다.</li>
<li>인센티브 양립('모든 정직한 노드가 손해 보지 않는 구조')은 가설이며 이 보고서는 검증하지 않았다.</li>
</ul>
</div>

<h2>7. 애니메이션·모션 설계 메모</h2>
<p class="small muted">경로검증 콘솔 옵션 1e. 모션은 인과를 보이는 데만 쓰고 강조에는 쓰지 않는다. 결손·미실행은 절대 움직이지 않는다 — 부재가 사건처럼 보이면 안 된다. <span class="mono">prefers-reduced-motion</span> 에서는 모든 재생이 최종 상태로 즉시 점프한다 (이 페이지도 그렇게 동작한다).</p>
<div class="card small" id="animNotes"></div>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const $ = (s)=>document.querySelector(s);
const esc = (s)=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const cls = (r)=>r==='pass'?'pass':r==='fail'?'fail':'na';
const st = (s)=>s==='passed'?'pass':s==='failed'?'fail':'warn';
// 해시·커밋은 앞 12자만 보이고, 누르면 전체 값을 클립보드로 복사한다.
const short = (h)=>h?`<span class="hashchip" data-copy="${esc(h)}" role="button" tabindex="0" title="클릭하면 전체 값을 복사합니다">${esc(String(h).slice(0,12))}…</span>`:'<span class="absent">없음</span>';
const absent = (v)=>(v===null||v===undefined)?'<span class="absent">null</span>':esc(v);
// 색은 CSS 토큰과 같은 값을 SVG stroke 등 속성 컨텍스트에도 그대로 써야 하므로 여기서도 고정한다
// (var(--x) 는 attribute 컨텍스트에서 계산된 값으로 안전하게 쓰인다).
const CV = (name)=>`var(--${name})`;

// ---------- 배지
(function(){
  const g = D.generated_with;
  $('#badges').innerHTML = [`itx ${g.itx_version}`,`검사기 ${g.checker_version}`,`seed ${g.seed}`,`서명 ${g.crypto_backend}`,`claim ${g.claim_status}`,`deployment evaluation`,`assurance ≤ air-local`].map(x=>`<span>${esc(x)}</span>`).join('');
})();

// ---------- 요약
(function(){
  const S = D.summary; const modes = Object.keys(S);
  const row = (label, f)=>`<tr><th>${label}</th>${modes.map(m=>`<td>${f(S[m])}</td>`).join('')}</tr>`;
  const frac = (o)=>o.den?`${o.num}/${o.den}${o.rate!=null?` <span class="muted">(${(o.rate*100).toFixed(0)}%)</span>`:''}`:'<span class="absent">분모 0</span>';
  $('#summary').innerHTML = `<table><thead><tr><th>지표</th>${modes.map(m=>`<th>${m}</th>`).join('')}</tr></thead><tbody>
  ${row('시도 수 / 공격 시도', s=>`${s.attempts} / ${s.attack_attempts}`)}
  ${row('탐지 (T 최종 판정 failed, 관측 가능한 공격 중)', s=>frac(s.detection)+` <span class="muted small">제외 ${s.detection.excluded_undetectable}</span>`)}
  ${row('사용 전 방어 (공격 응답이 업무에 소비되지 않음)', s=>frac(s.defense_before_use))}
  ${row('피해 노출 (공격 응답이 업무에 사용됨)', s=>`${s.harm_exposed.num}/${s.harm_exposed.den}`)}
  ${row('오차단 (정상인데 격리·거부)', s=>frac(s.false_block)+` <span class="muted small">무응답 제외 ${s.false_block.excluded_no_response}</span>`)}
  ${row('안전 완료 (정상 요청이 검증 후 수용)', s=>frac(s.safe_completion_legit))}
  ${row('증거 완전 (합의 증거 모두 등록)', s=>`${s.evidence_complete.num}/${s.evidence_complete.den}`)}
  ${row('결정 대기 ms (평균 / 최대)', s=>`${s.decision_wait_ms.mean ?? '-'} / ${s.decision_wait_ms.max ?? '-'}`)}
  ${row('왕복 지연 ms (평균 / 최대)', s=>`${s.rtt_ms.mean ?? '-'} / ${s.rtt_ms.max ?? '-'}`)}
  </tbody></table>`;
})();

// ---------- 매트릭스
const byKey = {}; D.results.forEach(r=>{ byKey[r.run.scenario_id+'|'+r.run.mode]=r; });
let cur = {sid:'S01', mode:'protect', attempt:0};
(function(){
  const modes = ['observe','protect','strict'];
  const rows = D.scenarios.map(sc=>{
    const rp = byKey[sc.id+'|protect']; const last = rp.attempts[rp.attempts.length-1]; const fv = last.final_verdict;
    const codes = fv.discrepancies.map(d=>d.code);
    const gates = modes.map(m=>{const r=byKey[sc.id+'|'+m]; const a=r.attempts[r.attempts.length-1]; const atk=a.metrics.attack_present; const act=a.gate.action;
      const k = act==='no_response' ? 'na' : (act==='accept'||act==='accept_unverified') ? (atk?'fail':'pass') : (atk?'pass':'fail');
      return `<td class="${k}">${esc(act)}</td>`;}).join('');
    const audit = rp.audit; const anch = audit.anchors.every(a=>a.ok);
    return `<tr class="clickable" tabindex="0" data-sid="${sc.id}"><td><b>${sc.id}</b></td><td>${esc(sc.title)}<div class="small muted">${esc(sc.category)} · 공격 ${sc.ground_truth.attack_present?'있음':'없음'}${sc.ground_truth.detectable_by_evidence?'':' · <b>증거로 탐지 불가</b>'}</div></td>
      <td class="${st(fv.verification_status)}">${fv.verification_status}</td><td>${fv.completeness}</td><td class="small">${codes.length?codes.map(esc).join('<br>'):'<span class="absent">없음</span>'}</td>${gates}
      <td class="${audit.ok?'pass':'fail'}">${audit.ok?'일치':'불일치'}${audit.verdict_mismatches.length?` <span class="small">(판정 ${audit.verdict_mismatches.length})</span>`:''}</td><td class="${anch?'pass':'fail'}">${anch?'일치':'재작성 감지'}</td></tr>`;
  }).join('');
  $('#matrix').innerHTML = `<table><thead><tr><th>ID</th><th>시나리오</th><th>최종 판정 (protect 실행)</th><th>완전성</th><th>불일치 코드</th><th>게이트 observe</th><th>게이트 protect</th><th>게이트 strict</th><th>독립 감사</th><th>앵커</th></tr></thead><tbody>${rows}</tbody></table>
  <p class="small muted">게이트 칸의 색은 '공격이 있으면 막았는가, 없으면 통과시켰는가' 기준이다. observe 모드는 설계상 모두 통과시키므로 공격 시나리오에서 빨갛다 — 그것이 관찰 모드의 비용이다. 무응답은 회색이다.</p>`;
  const pick = (sid)=>{cur.sid=sid;cur.attempt=0;onSelectionChanged();};
  document.querySelectorAll('#matrix tr.clickable').forEach(tr=>{
    tr.addEventListener('click',()=>pick(tr.dataset.sid));
    tr.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();pick(tr.dataset.sid);}});
  });
})();

// ---------- 사건 상세: 탭 컨트롤 ----------------------------------------------------
function buildTabs(container, items, isOn, onPick){
  container.innerHTML = items.map(it=>`<button type="button" class="pill${isOn(it)?' on':''}" data-v="${esc(it.v)}">${esc(it.label)}</button>`).join('');
  container.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>onPick(b.dataset.v)));
}
function onSelectionChanged(){
  document.querySelectorAll('#matrix tr').forEach(tr=>tr.classList.toggle('sel',tr.dataset.sid===cur.sid));
  buildTabs($('#scenarioTabs'), D.scenarios.map(sc=>({v:sc.id,label:sc.id})), it=>it.v===cur.sid, v=>{cur.sid=v;cur.attempt=0;onSelectionChanged();});
  buildTabs($('#modeTabs'), ['observe','protect','strict'].map(m=>({v:m,label:m})), it=>it.v===cur.mode, v=>{cur.mode=v;onSelectionChanged();});
  const r = byKey[cur.sid+'|'+cur.mode];
  const attemptRow = $('#attemptRow');
  if (r.attempts.length>1){
    attemptRow.style.display='';
    buildTabs($('#attemptTabs'), r.attempts.map((a,i)=>({v:String(i),label:a.attempt_id})), it=>+it.v===cur.attempt, v=>{cur.attempt=+v;onSelectionChanged();});
  } else { attemptRow.style.display='none'; }
  stopPlayback();
  renderDetail();
}

// ---------- 재생: 실제 타임라인에서 구간을 역산한다 --------------------------------
// 홉 20ms · 중개 처리 5ms · 서명 2ms 는 itx/sim/context.py 의 시뮬레이션 지연 상수와 같다.
const HOP_MS = 20, PROC_MS = 5, SIGN_MS = 2;
// itx/sim/model.py DEFAULT_MODELS 의 latency_ms. 프런트는 백엔드를 다시 호출하지 않으므로
// 표시용으로만 복제했다 — 실제 실행 성능이 아니라 재생 애니메이션의 구간 비율을 정하는 데만 쓴다.
const MODEL_LATENCY_MS = {'model-A':200,'model-A-small':80,'model-B':150};

// 구간은 꺾은선(pts)으로 둔다. 노드를 드나드는 수직 구간이 있어야 패킷이 선 위를 실제로 타고 도는 것처럼 보인다.
function computeLegs(a, c, rl, m){
  const modelId = (m && m.model_id) || (rl && rl.upstream_model) || c.requested_model;
  const lat = MODEL_LATENCY_MS[modelId] ?? 200;
  const raw = []; let t = 0;
  const push=(dt,pts,label,work,arrive)=>{ raw.push({t0:t,t1:t+dt,pts,label,work,arrive}); t+=dt; };
  push(HOP_MS,  [[120,118],[120,100],[430,100]], '요청 전송 U→R', false, 'R');
  push(PROC_MS, [[430,100]],                     'R 중개자 처리',  true);
  push(HOP_MS,  [[430,100],[700,100]],           '요청 전달 R→M',  false, 'M');
  push(lat,     [[700,100],[700,118]],           'M 추론',         true);
  push(SIGN_MS, [[700,118]],                     'M 영수증 서명',  true);
  push(HOP_MS,  [[700,118],[700,196],[430,196]], '응답 전달 M→R',  false, 'R');
  push(SIGN_MS, [[430,196]],                     'R 중계 진술 서명', true);
  push(HOP_MS,  [[430,196],[120,196],[120,170]], '응답 전송 R→U',  false, 'U');
  const rawEnd = t;
  const real0 = a.sent_at, real1 = a.received_at;
  const scale = (rawEnd>0 && real1>real0) ? (real1-real0)/rawEnd : 1;
  return raw.map(L=>({...L, t0:real0+L.t0*scale, t1:real0+L.t1*scale}));
}
const segLen = (a,b)=>Math.hypot(b[0]-a[0], b[1]-a[1]);
function cumulative(pts){ const c=[0]; for(let i=1;i<pts.length;i++) c.push(c[i-1]+segLen(pts[i-1],pts[i])); return c; }
function atDist(pts, c, d){
  const total = c[c.length-1];
  if (total<=0) return [pts[0][0], pts[0][1]];
  const x = Math.max(0, Math.min(total, d));
  for (let i=1;i<pts.length;i++){
    if (x<=c[i] || i===pts.length-1){
      const len=c[i]-c[i-1], f=len>0?(x-c[i-1])/len:0;
      return [pts[i-1][0]+(pts[i][0]-pts[i-1][0])*f, pts[i-1][1]+(pts[i][1]-pts[i-1][1])*f];
    }
  }
  return [pts[pts.length-1][0], pts[pts.length-1][1]];
}
// 이동 구간은 정지에서 출발해 정지로 끝나므로 가감속을 준다. 노드 안 구간은 앞부분에서 자리를 잡고 머문다.
const easeInOut = (f)=> f<.5 ? 2*f*f : 1-Math.pow(-2*f+2,2)/2;
const settle = (f)=> 1-Math.pow(1-Math.min(1,f/0.28),3);
function packetPos(t, legs){
  if (t<=legs[0].t0){ const p=legs[0].pts[0]; return {x:p[0], y:p[1], leg:legs[0], index:0, f:0}; }
  let index = 0;
  for (let i=0;i<legs.length;i++) if (t>=legs[i].t0) index=i;
  const L = legs[index];
  const raw = Math.max(0, Math.min(1, (t-L.t0)/Math.max(1,L.t1-L.t0)));
  const f = L.work ? settle(raw) : easeInOut(raw);
  const c = cumulative(L.pts), p = atDist(L.pts, c, f*c[c.length-1]);
  return {x:p[0], y:p[1], leg:L, index, f};
}
// 노드에 머무는 구간에서는 잔상이 구간 앞 30% 안에 0 으로 줄어든다 — 도착해서 멈췄다는 사실을 남긴다.
function trailLength(t, legs, base){
  const L = packetPos(t, legs).leg;
  if (!L.work) return base;
  const decay = Math.max(1, (L.t1-L.t0)*0.3);
  return base*Math.max(0, 1-(t-L.t0)/decay);
}
// 진행 방향 뒤쪽으로 maxLen 만큼의 잔상 좌표를 되짚는다. 꺾이는 지점과 구간 경계를 그대로 따라간다.
function trailPoints(t, legs, maxLen){
  const cur = packetPos(t, legs);
  const out = [[cur.x, cur.y]];
  if (maxLen<=0.5) return out;
  let remain = maxLen, i = cur.index, f = cur.f;
  while (remain>0.5 && i>=0){
    const pts = legs[i].pts, c = cumulative(pts);
    let pos = f*c[c.length-1];
    for (let k=pts.length-1; k>=0 && remain>0.5; k--){
      if (c[k]>=pos) continue;
      const step = pos-c[k];
      if (step>=remain){ out.push(atDist(pts, c, pos-remain)); remain=0; break; }
      out.push([pts[k][0], pts[k][1]]); remain-=step; pos=c[k];
    }
    i--; f=1;
  }
  return out;
}

// ---------- 재생 엔진 ------------------------------------------------------------
let PB = null; // 현재 선택의 재생 컨텍스트 (renderDetail 이 채운다)
let playing = false, rafId = null, lastTs = null;
let reducedMotion = false;
try { reducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch(e) {}

const SPEEDS = [0.5, 1, 2];
let speed = 1;
function stopPlayback(){ playing=false; if(rafId) cancelAnimationFrame(rafId); rafId=null; lastTs=null; if(PB) PB.prev=null; updatePlayBtn(); }
function updatePlayBtn(){
  const b=$('#playBtn'); if(b) b.textContent = playing?'⏸ 일시정지':'▶ 재생';
  const sp=$('#speedBtn'); if(sp) sp.textContent = '×'+speed;
}
function setT(v){
  if(!PB) return;
  const next = Math.max(0, Math.min(PB.tEnd, v));
  // 뒤로 가면 그 이후의 도달 펄스를 다시 낼 수 있게 되돌린다.
  if (next < PB.t) for (const i of [...PB.fired]) if (PB.legs[i].t1 > next) PB.fired.delete(i);
  PB.t = next; updatePacket();
}
// 홉 경계(구간 시작·끝)로만 이동한다. 어떤 구간에서 무엇이 바뀌는지 한 걸음씩 확인하는 용도다.
function stepHop(dir){
  if(!PB) return;
  const marks = [...new Set([0, ...PB.legs.map(l=>l.t0), ...PB.legs.map(l=>l.t1), PB.tEnd])]
    .filter(v=>v>=0 && v<=PB.tEnd).sort((a,b)=>a-b);
  const next = dir>0 ? marks.find(v=>v>PB.t+0.5) : [...marks].reverse().find(v=>v<PB.t-0.5);
  setT(next ?? (dir>0 ? PB.tEnd : 0));
}
function stepPlayback(ts){
  if (!playing) return;
  const dt = lastTs!=null ? Math.min(64, ts-lastTs) : 16; lastTs = ts;
  const base = Math.max(0.05, PB.tEnd/3200); // 실측 길이와 무관하게 ×1 재생은 약 3초, 구간 비율은 실제 값 그대로
  let nt = PB.t + dt*base*speed;
  if (nt >= PB.tEnd) { nt = PB.tEnd; playing = false; }
  setT(nt);
  if (playing) rafId = requestAnimationFrame(stepPlayback); else updatePlayBtn();
}
function togglePlay(){
  if (!PB) return;
  if (reducedMotion){ setT(PB.tEnd); return; } // 축소 모션: 최종 상태로 즉시 점프, 재생하지 않는다
  if (playing) { stopPlayback(); return; }
  if (PB.t >= PB.tEnd) setT(0);
  playing = true; lastTs = null; updatePlayBtn();
  rafId = requestAnimationFrame(stepPlayback);
}
$('#playBtn').addEventListener('click', togglePlay);
$('#resetBtn').addEventListener('click', ()=>{ stopPlayback(); setT(0); });
$('#stepBackBtn').addEventListener('click', ()=>{ stopPlayback(); stepHop(-1); });
$('#stepFwdBtn').addEventListener('click', ()=>{ stopPlayback(); stepHop(1); });
$('#speedBtn').addEventListener('click', ()=>{ speed = SPEEDS[(SPEEDS.indexOf(speed)+1)%SPEEDS.length]; updatePlayBtn(); });

// 시점 타임라인 스크러버: 누른 자리로 바로 이동하고 드래그로 따라간다.
let scrubbing = null;
function seekAt(box, clientX){
  if (!PB) return;
  const r = box.getBoundingClientRect();
  if (r.width<=0) return;
  setT(PB.span.inv(((clientX-r.left)/r.width)*100));
}
document.addEventListener('pointerdown', e=>{
  const box = e.target.closest && e.target.closest('[data-scrub]');
  if (!box || !PB) return;
  e.preventDefault(); stopPlayback(); scrubbing = box; box.setPointerCapture(e.pointerId); box.focus();
  seekAt(box, e.clientX);
});
document.addEventListener('pointermove', e=>{ if (scrubbing) seekAt(scrubbing, e.clientX); });
const endScrub = (e)=>{ if(!scrubbing) return; try{ scrubbing.releasePointerCapture(e.pointerId); }catch(err){} scrubbing=null; };
document.addEventListener('pointerup', endScrub);
document.addEventListener('pointercancel', endScrub);
// 키보드: 스크러버나 재생 컨트롤에 초점이 있을 때만 받는다.
document.addEventListener('keydown', e=>{
  const t = e.target;
  if (!t.closest || (!t.closest('[data-scrub]') && !t.closest('.playctl'))) return;
  if (e.key===' '||e.key==='Spacebar'){ if (t.closest('button')) return; e.preventDefault(); togglePlay(); }
  else if (e.key==='ArrowLeft'){ e.preventDefault(); stopPlayback(); stepHop(-1); }
  else if (e.key==='ArrowRight'){ e.preventDefault(); stopPlayback(); stepHop(1); }
  else if (e.key==='Home'||e.key==='r'||e.key==='R'){ e.preventDefault(); stopPlayback(); setT(0); }
  else if (e.key==='End' && PB){ e.preventDefault(); stopPlayback(); setT(PB.tEnd); }
});

// ---------- 홉 지도 (정적 부분: 등식 색·라벨. 좌표는 경로검증 콘솔.dc.html 1a 를 그대로 옮김) ------
const EQ_POS = [
  ['E12', 30, 44, 'start', '유효기간'], ['E1', 30, 60, 'start', '자기 정합'],
  ['E5', 410, 44, 'mid', 'nonce 결합'], ['E8', 410, 60, 'mid', '승인 경로'],
  ['E9', 790, 44, 'end', '아티팩트'], ['E11', 790, 60, 'end', '시도 결합'],
  ['E2', 270, 82, 'mid', '요청 U→R'], ['E3', 570, 82, 'mid', '진술 R↔M'],
  ['E4', 570, 108, 'mid', '승인 변환 재계산'], ['E6', 570, 208, 'mid', '응답 M→R'],
  ['E7', 270, 208, 'mid', '응답 R→U'],
  ['E10', 410, 284, 'mid', '종단 응답 결합 — M 이 서명한 응답 == U 가 받은 응답'],
];
function eqGlyph(r){ return r==='pass'?'✓':r==='fail'?'✗':'–'; }
function hopMapSvg(eq){
  const col = (id)=>CV(cls((eq[id]||{}).result||'not_evaluable'));
  const labels = EQ_POS.map(([id,x,y,anchor,tail])=>{
    const e = eq[id]||{result:'not_evaluable'};
    const tx = anchor==='mid'?'translate(-50%,-50%)':anchor==='end'?'translate(-100%,-50%)':'translate(0,-50%)';
    const weight = id==='E10' ? 600 : 400, size = id==='E10' ? 12 : (id==='E2'||id==='E3'||id==='E6'||id==='E7') ? 11.5 : 11;
    return `<div class="hoplabel" data-eq="${id}" style="left:${(x/820*100).toFixed(2)}%;top:${(y/360*100).toFixed(2)}%;transform:${tx};font:${weight} ${size}px 'IBM Plex Mono',monospace;color:${col(id)}">${eqGlyph(e.result)} ${id} ${esc(tail)}</div>`;
  }).join('');
  return { labels, colOf: col };
}

// ---------- 사건 상세: 전체 재구성 ------------------------------------------------
function renderDetail(){
  const r = byKey[cur.sid+'|'+cur.mode];
  const a = r.attempts[Math.min(cur.attempt, r.attempts.length-1)];
  const sc = r.scenario, fv = a.final_verdict, eq = fv.equations, g = a.gate;
  const c = a.contract.payload, o = a.observation?a.observation.payload:null,
        rl = a.inline_relay?a.inline_relay.payload:null, m = a.inline_receipt?a.inline_receipt.payload:null;
  const gt = a.ground_truth_view||{};

  const findReg = (ct)=> (a.registered||[]).find(x=>x.content_type===ct);
  const regContract = findReg('application/vnd.itx.contract+json');
  const regRelay = findReg('application/vnd.itx.relay+json');
  const regReceipt = findReg('application/vnd.itx.receipt+json');
  const regObs = findReg('application/vnd.itx.observation+json');
  const verdictEv = r.timeline.find(e=>e.kind==='verdict_issued' && e.sub===a.sub);
  const verdictAt = verdictEv ? verdictEv.t : null;
  const consumedAt = g.consumed_at;
  const detectable = a.ground_truth.detectable_by_evidence;
  const attack = a.ground_truth.attack_present;
  const harmExposed = a.metrics.harm_exposed;

  // ---- 재생 컨텍스트 계산 -------------------------------------------------------
  const legs = computeLegs(a, c, rl, m);
  const breakpoint = Math.max(60, Math.round(a.received_at*1.4/10)*10);
  const candidates = [a.sent_at, a.received_at, g.decided_at, consumedAt||0, verdictAt||0];
  const tEnd = Math.max(breakpoint+40, ...candidates) * 1.08;
  const span = (ms)=>{ const v=Math.min(Math.max(ms,0),tEnd); return v<=breakpoint ? 4+(v/breakpoint)*60 : 72+((v-breakpoint)/Math.max(1,tEnd-breakpoint))*24; };
  // 스크러버가 쓰는 역함수. 축 생략 구간(64~72%)은 breakpoint 로, 오른쪽 여백은 끝 시점으로 모은다.
  span.inv = (pct)=>{
    const q = Math.min(Math.max(pct,0),100);
    const ms = q<=4 ? 0 : q<=64 ? ((q-4)/60)*breakpoint : q<72 ? breakpoint
      : breakpoint + ((q-72)/24)*Math.max(1, tEnd-breakpoint);
    return Math.min(Math.max(ms,0), tEnd);
  };
  PB = { legs, tEnd, breakpoint, span, eq, consumedAt, verdictAt, harmExposed, detectable, attack,
         receivedAt:a.received_at, hasError: !!a.error, t: tEnd,
         fired: new Set(legs.map((_,i)=>i)), evFired: new Set(), primed: false, prev: null, fill: '' };
  $('#tLabel').textContent = `t = ${Math.round(tEnd)} ms`;

  // ---- 홉 지도 (정적) -----------------------------------------------------------
  const hop = hopMapSvg(eq);
  const evReg = (reg)=> reg ? `<span title="등록 ≤ ${reg.registered_at} ms"></span>` : '';
  const svg = `<svg viewBox="0 0 820 360" role="img" aria-label="홉 정합 지도 — ${esc(sc.id)}">
    <defs><marker id="itxar" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="${CV('muted')}"/></marker></defs>
    <line x1="150" y1="92" x2="390" y2="92" stroke="${hop.colOf('E2')}" stroke-width="2.5" marker-end="url(#itxar)"/>
    <line x1="470" y1="92" x2="670" y2="92" stroke="${hop.colOf('E3')}" stroke-width="2.5" marker-end="url(#itxar)"/>
    <line x1="670" y1="188" x2="470" y2="188" stroke="${hop.colOf('E6')}" stroke-width="2.5" marker-end="url(#itxar)"/>
    <line x1="390" y1="188" x2="150" y2="188" stroke="${hop.colOf('E7')}" stroke-width="2.5" marker-end="url(#itxar)"/>
    <path d="M700,205 C700,268 120,268 120,205" fill="none" stroke="${hop.colOf('E10')}" stroke-width="2.5" stroke-dasharray="7 4"/>
    <rect x="60" y="118" width="120" height="52" rx="6" fill="${CV('chip')}" stroke="${CV('line')}"/>
    <text x="120" y="140" text-anchor="middle" font-size="13" font-weight="700">U</text>
    <text x="120" y="157" text-anchor="middle" font-size="11" fill="${CV('muted')}">사용자 · 집행 모듈</text>
    <rect x="370" y="118" width="120" height="52" rx="6" fill="${CV('chip')}" stroke="${CV('line')}"/>
    <text x="430" y="140" text-anchor="middle" font-size="13" font-weight="700">R</text>
    <text x="430" y="157" text-anchor="middle" font-size="11" fill="${CV('muted')}">중개자 (클라우드 대행)</text>
    <rect x="640" y="118" width="120" height="52" rx="6" fill="${CV('chip')}" stroke="${CV('line')}"/>
    <text x="700" y="140" text-anchor="middle" font-size="13" font-weight="700">M</text>
    <text x="700" y="157" text-anchor="middle" font-size="11" fill="${CV('muted')}">모델 운영자</text>
    <rect class="nodehalo" id="itxHaloU" x="60" y="118" width="120" height="52" rx="6" fill="none" stroke="${CV('accent')}" stroke-width="2"/>
    <rect class="nodehalo" id="itxHaloR" x="370" y="118" width="120" height="52" rx="6" fill="none" stroke="${CV('accent')}" stroke-width="2"/>
    <rect class="nodehalo" id="itxHaloM" x="640" y="118" width="120" height="52" rx="6" fill="none" stroke="${CV('accent')}" stroke-width="2"/>
    <rect x="330" y="306" width="160" height="44" rx="6" fill="${CV('card')}" stroke="${CV('accent')}" stroke-dasharray="5 3"/>
    <text x="410" y="324" text-anchor="middle" font-size="12" font-weight="700" fill="${CV('accent')}">T — 독립 제3자</text>
    <text x="410" y="339" text-anchor="middle" font-size="10.5" fill="${CV('muted')}">대조 · 정책 · 추가 전용 로그</text>
    <rect class="nodehalo" id="itxHaloT" x="330" y="306" width="160" height="44" rx="6" fill="none" stroke="${CV('accent')}" stroke-width="2"/>
    <line id="itxEvU" class="evline" x1="120" y1="170" x2="340" y2="306" stroke="${CV('line')}" stroke-width="1.5" stroke-dasharray="4 4"/>
    <line id="itxEvR" class="evline" x1="430" y1="170" x2="410" y2="306" stroke="${CV('line')}" stroke-width="1.5" stroke-dasharray="4 4"/>
    <line id="itxEvM" class="evline" x1="700" y1="170" x2="480" y2="306" stroke="${CV('line')}" stroke-width="1.5" stroke-dasharray="4 4"/>
    ${[1,2,3].map(i=>`<polyline id="itxTrail${i}" class="packettrail" points="" fill="none" stroke="${CV('accent')}" stroke-width="${9-i}" stroke-linecap="round" stroke-linejoin="round" opacity="0"/>`).join('')}
    <circle id="itxPacket" class="packet" cx="120" cy="118" r="8" fill="${CV('accent')}"/>
  </svg>`;
  const evidenceRegs = { U: regContract, R: regRelay, M: regReceipt };

  // ---- 시점 타임라인 (정적 마크. 재생 바는 updatePacket 이 채운다) ------------------
  let marks = [
    {label:'요청 전송', at:`${a.sent_at} ms`, pos:span(a.sent_at), color:'muted'},
    {label: a.error?'응답 없음':'U 수신', at:`${a.received_at} ms`, pos:span(a.received_at), color:'muted'},
    {label:'게이트 결정', at:`${g.decided_at} ms`, pos:span(g.decided_at), color:'pass'},
  ];
  marks.push(consumedAt===null
    ? {label:'업무 사용', at:'null (격리)', pos:span(g.decided_at)+2, color:'na'}
    : {label:'업무 사용', at:`${consumedAt} ms`, pos:span(consumedAt), color: harmExposed?'fail':'muted'});
  if (!detectable && attack) marks.push({label:'T 판정', at:'탐지 불가로 분류', pos: verdictAt!=null?span(verdictAt):90, color:'na'});
  else if (verdictAt!=null) marks.push({label:'T 판정 등록', at:`${verdictAt} ms`, pos:span(verdictAt), color:'pass'});
  marks.sort((x,y)=>x.pos-y.pos);
  let lastPos=-999, row=0;
  for (const mk of marks){ row = (mk.pos-lastPos<7) ? (row===0?1:0) : 0; mk.row=row; lastPos=mk.pos; }
  const marksHtml = marks.map(mk=>`<div style="position:absolute;top:${mk.row?41:2}px;left:${mk.pos}%;transform:translateX(-50%);pointer-events:none">
    <div class="markline"></div><div class="marklabel" style="color:${CV(mk.color)}">${esc(mk.label)}</div><div class="markat">${esc(mk.at)}</div></div>`).join('');
  const harmNote = (attack && !detectable)
    ? '탐지 불가로 분류된 사건이다. 탐지율 분모에서 제외하고 그 수를 따로 적는다 — 통과 배지로 표시하지 않는다.'
    : consumedAt===null
      ? "업무 사용 없음. 이 사건에서 방어는 '경로를 차단했다' 가 아니라 '변조된 응답이 도구 실행에 쓰이기 전에 U 가 거부했다' 로 기록된다."
      : harmExposed && verdictAt!=null
        ? `소비 ${consumedAt} ms · T 판정 등록 ${verdictAt} ms. 그 사이 ${Math.max(0,verdictAt-consumedAt)} ms 동안 피해가 노출되었다. 탐지는 성공, 이 피해의 방어는 실패다.`
        : `정상 요청이 기한 내 완료되었다. 대기 비용 ${g.decided_at - g.received_at} ms.`;

  // ---- 증거 패널 -----------------------------------------------------------------
  const EV_META = {
    U: ['U 요청 계약', 'contract · 허용 모델·변환·폴백·만료 서명'],
    R: ['R 중계 진술', 'relay · in/out 커밋, 선언 변환, 상류 모델'],
    M: ['M 추론 영수증', 'receipt · 요청/응답 커밋, eat_nonce, model_id'],
    O: ['U 수신 진술', 'observation · 실제 받은 응답의 커밋'],
  };
  const evRow = (key, reg)=>{
    const [name, detail] = EV_META[key];
    if (!reg) return `<div class="evrow absent-row" data-ev-key="${key}">
      <span class="evdot"></span>
      <span class="evname">${name}</span><span class="evdetail">${detail}</span>
      <span class="evstate">결손</span></div>`;
    return `<div class="evrow" data-ev-reg="${reg.registered_at}" data-ev-key="${key}">
      <span class="evdot"></span>
      <span class="evname">${name}</span><span class="evdetail">${detail}</span>
      <span class="evstate">대기</span></div>`;
  };
  const evidence = evRow('U',regContract) + evRow('R',regRelay) + evRow('M',regReceipt) + evRow('O',regObs);

  // ---- 결론 -----------------------------------------------------------------------
  const sevColor = (sv)=> sv==='violation'?'fail':sv==='contradiction'?'warn':'na';
  const codes = fv.discrepancies.length
    ? fv.discrepancies.map(d=>`<div class="codebox" style="border-color:${CV(sevColor(d.severity))}">
        <div class="mono" style="font-weight:600;color:${CV(sevColor(d.severity))}">${esc(d.code)} <span style="font-weight:400;color:${CV('muted')}">· ${esc(d.severity)}</span></div>
        <div class="small">귀속 ${esc(d.attribution)} <span class="muted">— ${esc(d.attribution_basis)}</span></div></div>`).join('')
    : `<div class="small absent">불일치 코드 없음</div>`;

  // ---- 집행 -------------------------------------------------------------------------
  const gateColor = g.action==='accept'?'pass':g.action==='accept_unverified'?'warn':g.action==='no_response'?'na':'fail';
  const lc = Object.entries(g.local_checks||{}).map(([k,v])=>{
    const c2 = v.result==='fail'?`background:${CV('card')};border:1px solid ${CV('fail')};color:${CV('fail')}`
      : v.result==='not_evaluable'?`background:${CV('card')};border:1px dashed ${CV('na')};color:${CV('na')}`
      : `background:${CV('chip')};border:1px solid ${CV('line')};color:${CV('muted')}`;
    return `<span class="mono eqchip" data-eq="${esc(k)}" style="padding:2px 6px;border-radius:4px;${c2}" title="${esc(v.reason)}">${esc(k)}</span>`;
  }).join(' ');

  // ---- 비교: bad-cell 표시는 실제 등식 결과에서 도출한다 (수기 지정 색인 없음) ------
  const eqr = (id)=> (eq[id]||{}).result;
  const isFail = (id)=> eqr(id)==='fail';
  const bad = {
    req:  { R: isFail('E2')||isFail('E4'), M: isFail('E3')||isFail('E4') },
    model:{ R: isFail('E8'), M: isFail('E8')||isFail('E9') },
    tr:   { R: isFail('E4') },
    nonce:{ R: isFail('E5'), M: isFail('E5') },
    resp: { R: isFail('E6')||isFail('E7')||isFail('E10'), M: isFail('E6'), U: isFail('E7')||isFail('E10') },
    att:  { R: isFail('E11'), M: isFail('E11'), U: isFail('E11') },
  };
  const cell = (html, isBad, isGap)=> isGap ? `<span style="color:${CV('na')};font-style:italic">결손</span>`
    : (html==null ? '<span class="absent">없음</span>'
      : isBad ? `<span style="color:${CV('fail')};font-weight:600;background:${CV('fail-soft')};padding:1px 4px;border-radius:3px">${html}</span>` : html);
  const cmp = `<div class="tablewrap"><table><thead><tr><th></th><th>U 승인 계약</th><th>R 선언 (동봉)</th><th>M 관측 (동봉 영수증)</th><th>U 실제 수신</th></tr></thead><tbody>
    <tr><th>요청 커밋</th><td class="mono">${short(c.req_commit)}</td>
      <td class="mono">${cell(rl?`in ${short(rl.in_commit)}<br>out ${short(rl.out_commit)}`:null, bad.req.R, !rl)}</td>
      <td class="mono">${cell(m?short(m.request_commit):null, bad.req.M, !m)}</td>
      <td class="muted small">—</td></tr>
    <tr><th>모델</th><td>${esc(c.requested_model)} <span class="small muted">허용 ${esc(c.allowed_models.join(', '))} · 폴백 ${esc(c.fallback_policy)}</span></td>
      <td>${cell(rl?esc(rl.upstream_model)+' <span class="small muted">('+esc(rl.policy_decision)+')</span>':null, bad.model.R, !rl)}</td>
      <td>${cell(m?esc(m.model_id)+' <span class="small muted">'+esc(m.decision)+'</span>':null, bad.model.M, !m)}</td>
      <td class="muted small">—</td></tr>
    <tr><th>변환</th><td>${esc(c.allowed_request_transforms.join(', '))}</td>
      <td>${cell(rl?esc(rl.request_transform_id):null, bad.tr.R, !rl)}</td>
      <td class="muted small">—</td><td class="muted small">—</td></tr>
    <tr><th>nonce</th><td class="mono">${short(c.nonce)}</td>
      <td class="mono">${cell(rl?short(rl.nonce_forwarded):null, bad.nonce.R, !rl)}</td>
      <td class="mono">${cell(m?short(m.eat_nonce):null, bad.nonce.M, !m)}</td>
      <td class="muted small">—</td></tr>
    <tr><th>응답 커밋</th><td class="muted small">—</td>
      <td class="mono">${cell(rl?`in ${short(rl.resp_in_commit)}<br>out ${short(rl.resp_out_commit)}`:null, bad.resp.R, !rl)}</td>
      <td class="mono">${cell(m?short(m.response_commit):null, bad.resp.M, !m)}</td>
      <td class="mono">${cell(o?short(o.resp_commit):null, bad.resp.U, !o)}</td></tr>
    <tr><th>시도</th><td>${esc(c.attempt_id)}</td>
      <td>${cell(rl?esc(rl.attempt_id):null, bad.att.R, !rl)}</td>
      <td>${cell(m?esc(m.attempt_id):null, bad.att.M, !m)}</td>
      <td>${cell(o?esc(o.attempt_id):null, bad.att.U, !o)}</td></tr>
    </tbody></table></div>
    <div class="small muted" style="margin-top:7px">커밋은 <span class="mono">commit(x) = H(salt ‖ H(canonical(x)))</span> 의 앞 12자다. 솔트는 로그에 올리지 않으므로 공개 원장만으로는 사전 대입이 불가능하다. 빨간 셀은 실패한 등식이 가리키는 값이며 두 칸이 다르다는 사실 자체가 가해자 확정은 아니다.</div>`;

  // ---- 등식 표 / 등록 진술 표 (기존 세부 자료, 유지) --------------------------------
  const eqRows = Object.entries(eq).map(([k,e])=>`<tr data-eq="${k}"><td><b>${k}</b> ${esc(e.title)}<div class="small muted">${esc(e.hop)}</div></td><td class="${cls(e.result)}">${e.result}</td><td>${esc(e.reason)}</td><td class="small">${(e.compared||[]).map(esc).join('<br>')}</td><td class="small muted">${esc(e.trust_grade)}</td></tr>`).join('');
  const regs = (a.registered||[]).map(x=>`<tr><td>${x.index}</td><td class="small">${esc(x.content_type.replace('application/vnd.itx.','').replace('+json',''))}</td><td class="small">${esc(x.iss.replace('urn:itx:party:',''))}</td><td>≤ ${x.registered_at} ms</td><td class="mono">${short(x.statement_hash)}</td></tr>`).join('') || '<tr><td colspan="5" class="absent">등록된 진술 없음</td></tr>';

  // ---- 시뮬레이터 사실 (증거 아님) --------------------------------------------------
  const factsHtml = `<div class="tablewrap"><table class="small"><tbody>
    <tr><th>U 가 보낸 요청</th><td>${absent(gt.request_sent&&gt.request_sent.input)}</td></tr>
    <tr><th>M 이 받은 요청</th><td>${gt.request_at_model?esc(JSON.stringify(gt.request_at_model)):'<span class="absent">null (전달되지 않음)</span>'}</td></tr>
    <tr><th>M 이 낸 응답</th><td>${absent(gt.response_from_model&&gt.response_from_model.output)}</td></tr>
    <tr><th>U 가 받은 응답</th><td>${absent(gt.response_at_user&&gt.response_at_user.output)}${gt.replayed_from?` <span class="warn">(${esc(gt.replayed_from)} 의 응답 재사용)</span>`:''}${a.response_body&&a.response_body.tool_call?` <span class="fail">도구 호출 지시 포함: ${esc(JSON.stringify(a.response_body.tool_call))}</span>`:''}</td></tr>
    </tbody></table></div>`;

  const tl = r.timeline.filter(e=>!e.sub||e.sub===a.sub||e.kind.startsWith('service')||e.actor==='T'||e.actor==='auditor'||e.actor==='sim').map(e=>{
    const mark = e.kind==='response_consumed'?'mark':e.kind==='gate_decision'?'decide':'';
    return `<tr><td class="muted">${e.seq}</td><td>${e.t}</td><td><b>${esc(e.actor)}</b></td><td class="${mark}">${esc(e.kind)}</td><td class="small mono">${esc(JSON.stringify(e.detail)).slice(0,220)}</td></tr>`;}).join('');
  const au = r.audit; const ts = r.ts;
  const anchors = au.anchors.map(x=>`<tr><td>${x.tree_size}</td><td class="mono">${short(x.anchored_root)}</td><td class="mono">${short(x.recomputed_root)}</td><td class="${x.ok?'pass':'fail'}">${esc(x.reason)}</td></tr>`).join('') || '<tr><td colspan="4" class="absent">앵커 없음</td></tr>';
  const mism = au.verdict_mismatches.map(x=>`<li><span class="mono">${short(x.sub)}</span> T: <b>${esc(x.t_verdict?x.t_verdict.verification_status:'없음')}</b> [${esc((x.t_verdict?x.t_verdict.codes:[]).join(', '))}] → 재계산: <b>${esc(x.recomputed.verification_status)}</b> [${esc(x.recomputed.codes.join(', '))}]</li>`).join('');
  const unauth = (au.unauthenticated_verdicts||[]).map(x=>`<li><span class="mono">${short(x.sub)}</span> #${x.log_index} <b>${esc(x.iss)}</b>: ${esc(x.problem)}</li>`).join('');
  const drops = Object.entries(ts.queue_drops).map(([k,v])=>`${k}: ${v.length}`).join(' · ');
  const swimlane = swimlaneCard(r, a, consumedAt, verdictAt, harmExposed, detectable, attack, g);
  const ledger = ledgerCard(r, a);

  $('#detail').innerHTML = `
  <div class="card">
    <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:24px;flex-wrap:wrap">
      <div><div style="font-size:16px;font-weight:700;letter-spacing:-.01em">요청 <span class="mono" style="color:${CV('muted')};font-size:14px">${esc(a.sub)}</span> · ${esc(sc.title)}</div>
      <div class="small muted" style="margin-top:3px">${esc(sc.description)}</div></div>
      <div class="badges"><span>mock_result</span><span>evaluation</span></div>
    </div>
    <p class="small" style="margin:10px 0 0"><b>시뮬레이터 사실:</b> 공격 ${attack?`있음 (${esc(a.ground_truth.attack_kind)})`:'없음'} · 증거로 탐지 ${detectable?'가능':'<b class="warn">불가 (설계상 한계)</b>'} ${a.ground_truth.note?'· '+esc(a.ground_truth.note):''}</p>
  </div>

  <div class="card"><h3>경로 — 업무 데이터 경로(실선)와 T 의 증거·통제 경로(점선)</h3>
    <div class="hopwrap">${svg}${hop.labels}<div class="packetlabel" id="itxPacketLabel" hidden></div></div>
    <div class="legend-row"><span class="pass">✓ pass</span><span class="fail">✗ fail</span><span class="na">– not_evaluable (사유는 등식 표에)</span></div>

    <h3>시점 — 검증 전에 무엇이 소비되었는가</h3>
    <div class="timebox" id="itxTimebox" data-scrub tabindex="0" role="slider" aria-label="재생 시점 탐색 — 드래그·방향키"
         aria-valuemin="0" aria-valuemax="0" aria-valuenow="0" title="클릭·드래그로 시점 이동 · ←/→ 홉 이동 · Space 재생">
      <div class="timeaxis"></div>
      <div class="timegap" style="left:66%"></div><div class="timegaplabel" style="left:68%">축 생략</div>
      <div id="itxHarmBar" class="harmbar empty" style="left:0;width:0"><span class="harmlabel">피해 노출 — 사용 이후 T 판정 전</span></div>
      ${marksHtml}
      <div id="itxPlayhead" class="playhead" style="left:0"><span class="playknob"></span></div>
    </div>
    <p class="small muted" style="margin-top:6px">${harmNote}</p>

    <div class="stripgrid" style="margin-top:14px">
      <div class="stripcell"><div class="k">정책 해시</div><div class="v">${short(fv.policy_hash)}</div></div>
      <div class="stripcell"><div class="k">검사기</div><div class="v">${esc(fv.checker_version)}</div></div>
      <div class="stripcell"><div class="k">신뢰 키 집합</div><div class="v">${esc(fv.trust_keys_version)}</div></div>
      <div class="stripcell"><div class="k">독립 재실행</div><div class="v" style="color:${au.ok?CV('pass'):CV('fail')}">${au.ok?'일치':'불일치'}</div></div>
    </div>
    <div class="small muted" style="margin-top:7px">판정은 이 네 값에 고정된다. 감사자는 로그 내보내기와 앵커만으로 같은 판정을 재계산할 수 있어야 하며, 재계산이 T 와 다르면 그 사실이 위 칸에 남는다.</div>
  </div>

  <div class="grid">
    <div class="card"><h3>증거 — 누가 무엇을 서명해 등록했는가</h3>
      <div style="display:flex;flex-direction:column;gap:5px">${evidence}</div></div>
    <div class="card"><h3>결론 — 사실·모순·부족을 섞지 않는다</h3>
      <p style="margin:0 0 6px"><span class="mono" style="font-weight:700;font-size:14px;color:${CV(st(fv.verification_status))}">${fv.verification_status}</span>
        <span class="small muted" style="margin-left:10px">완전성 <b style="color:${fv.completeness==='complete'?CV('muted'):CV('na')}">${fv.completeness}</b></span>
        <span class="small muted" style="margin-left:10px">협조 ${esc(fv.cooperation_set)}</span>
        <span class="small muted" style="margin-left:10px">보증 <b>${esc(fv.established_assurance)}</b></span></p>
      ${codes}
      <ul class="tight small muted">${(fv.notes||[]).map(n=>`<li>${esc(n)}</li>`).join('')}</ul></div>
    <div class="card"><h3>집행 — 사용자 게이트 (${esc(g.mode)})</h3>
      <div class="mono" style="font-weight:700;font-size:13px;color:${CV(gateColor)}">${esc(g.action)}</div>
      <div class="small" style="margin-top:3px">${g.reasons.map(esc).join(' · ')}</div>
      <div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:4px">${lc}</div>
      <div class="small muted" style="margin-top:8px">수신 ${g.received_at} ms → 결정 ${g.decided_at} ms (대기 ${g.waited_ms} ms) · 업무 사용 ${g.consumed_at===null?'<span class="absent">없음</span>':g.consumed_at+' ms'} ${g.consumed_before_decision?'<b class="fail">— 결정 전에 소비됨</b>':''}</div>
      ${a.live_verdict?`<div class="small muted" style="margin-top:4px">strict 모드에서 참조한 T 판정: ${esc(a.live_verdict.verification_status)} (${esc(a.live_verdict.completeness)})</div>`:''}
      ${a.error?`<div class="fail small" style="margin-top:4px">오류: ${esc(a.error)}</div>`:''}</div>
  </div>

  <div class="card"><h3>비교 — U 승인 계약 · R 선언 · M 관측 · U 실제 수신</h3>${cmp}</div>

  <div class="card"><h3>시뮬레이터가 아는 사실 (증거가 아님)</h3>${factsHtml}</div>

  <div class="grid">
    <div class="card"><h3>등식 (pass / fail / not_evaluable)</h3><div class="tablewrap"><table><thead><tr><th>등식</th><th>결과</th><th>사유</th><th>비교 대상</th><th>신뢰 등급</th></tr></thead><tbody>${eqRows}</tbody></table></div></div>
    <div class="card"><h3>등록된 진술 원장</h3><div class="tablewrap"><table><thead><tr><th>#</th><th>유형</th><th>발행</th><th>등록 시각 (상한)</th><th>진술 해시</th></tr></thead><tbody>${regs}</tbody></table></div>
      <p class="small muted">판정이 참조한 진술 ${fv.evidence_refs.length}건 · 서명 무효 ${fv.invalid_signature_refs.length}건 · 발행 권한 없음 ${(fv.unauthorized_issuer_refs||[]).length}건</p></div>
  </div>

  <div class="card"><h3>T 자기 검증과 독립 감사</h3>
    <p class="small">트리 크기 ${ts.tree_size} · 루트 <span class="mono">${short(ts.root_hash)}</span> · 등록 ${ts.submissions} / 거부 ${ts.refusals} · 큐 드롭 ${drops} · T 정지 ${ts.down_during_run?'있음':'없음'} · 추가 지연 ${ts.extra_delay_ms} ms ${ts.tampered_index!==null?`· <b class="fail">운영자가 항목 #${ts.tampered_index} 를 교체 (모사)</b>`:''}</p>
    <p>독립 재실행: <b class="${au.ok?'pass':'fail'}">${au.ok?'T 판정·트리·앵커 모두 일치':'불일치 발견'}</b> · 트리 재계산 ${au.tree_recomputed_matches_head?'<span class="pass">일치</span>':'<span class="fail">불일치</span>'} · 헤드 서명 ${au.head_signature_valid?'<span class="pass">유효</span>':'<span class="fail">무효</span>'} · 검사한 요청 ${au.subs_checked}</p>
    ${mism?`<ul class="tight small">${mism}</ul>`:''}
    ${unauth?`<p class="small fail">인증되지 않는 판정 진술 (서명·발행자 확인 실패)</p><ul class="tight small">${unauth}</ul>`:''}
    <div class="tablewrap"><table><thead><tr><th>앵커 크기</th><th>앵커 루트</th><th>현재 재계산 루트</th><th>판정</th></tr></thead><tbody>${anchors}</tbody></table></div>
    <p class="small muted">${esc(au.note)}</p></div>

  ${swimlane}
  ${ledger}

  <div class="card"><h3>시간선 (시뮬레이션 ms). 붉은 행 = 업무 사용, 녹색 행 = 게이트 결정</h3><div class="scroll"><table class="tl"><thead><tr><th>#</th><th>t</th><th>주체</th><th>사건</th><th>세부</th></tr></thead><tbody>${tl}</tbody></table></div></div>`;

  updatePacket();
}

// ---------- 재생 프레임: 패킷 위치·잔상·색, 도달 펄스, 증거 도달선, 재생 헤드/피해 막대만 갱신 -----------
function pulseNode(node){
  const el = $('#itxHalo'+node);
  if (!el) return;
  el.classList.remove('pulse'); void el.getBoundingClientRect(); el.classList.add('pulse');
}
function updatePacket(){
  if (!PB) return;
  const t = PB.t, lastLeg = PB.legs[PB.legs.length-1];
  $('#tLabel').textContent = `t = ${Math.round(t)} ms`;
  const pos = packetPos(t, PB.legs);
  const respTampered = (PB.eq.E10||{}).result==='fail';
  const reqTampered = (PB.eq.E4||{}).result==='fail';
  let fill = 'accent';
  if (t >= lastLeg.t1) fill = 'muted';
  if (reqTampered && t>=PB.legs[1].t0 && t<PB.legs[4].t0) fill = 'fail';
  if (respTampered && t>=PB.legs[6].t0) fill = 'fail';
  const changed = fill !== PB.fill; PB.fill = fill;
  const dot = $('#itxPacket');
  if (dot){ dot.setAttribute('cx', pos.x.toFixed(1)); dot.setAttribute('cy', pos.y.toFixed(1)); if (changed) dot.setAttribute('fill', CV(fill)); }

  const moving = t > PB.legs[0].t0 && t < lastLeg.t1;
  // 홉 구간은 추론 구간보다 10배 짧아 한 프레임에 크게 건너뛴다. 재생 중에는 그 간격만큼 꼬리를 늘려
  // 이동이 끊겨 보이지 않게 한다 — 속도를 그대로 드러내는 것이고 판정과는 무관하다.
  const jump = PB.prev ? Math.hypot(pos.x-PB.prev.x, pos.y-PB.prev.y) : 0;
  PB.prev = {x:pos.x, y:pos.y};
  const base = playing ? Math.max(22, Math.min(44, jump*1.6)) : 22;
  const full = (moving && !reducedMotion) ? trailLength(t, PB.legs, base) : 0;
  // 꼬리는 길이·두께·농도가 다른 세 겹으로 그린다. 방향이 꺾여도 그러데이션처럼 잦아든다.
  for (const [i, share, alpha] of [[1,1,.10],[2,.6,.16],[3,.3,.24]]){
    const layer = $('#itxTrail'+i);
    if (!layer) continue;
    const pts = full>0.5 ? trailPoints(t, PB.legs, full*share) : [];
    layer.setAttribute('points', pts.map(q=>`${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(' '));
    if (changed) layer.setAttribute('stroke', CV(fill));
    layer.style.opacity = pts.length>1 ? String(alpha) : '0';
  }
  const plabel = $('#itxPacketLabel');
  if (plabel){
    plabel.hidden = !moving;
    if (moving){
      plabel.textContent = pos.leg.label;
      plabel.style.left = (pos.x/820*100).toFixed(2)+'%';
      plabel.style.top = (pos.y/360*100).toFixed(2)+'%';
      plabel.style.transform = pos.y<150 ? 'translate(-50%,-180%)' : 'translate(-50%,80%)';
    }
  }
  if (!reducedMotion) for (let i=0;i<PB.legs.length;i++){
    const L = PB.legs[i];
    if (L.arrive && !PB.fired.has(i) && t>=L.t1){ PB.fired.add(i); pulseNode(L.arrive); }
  }

  // 결손 증거의 점선은 회색으로 고정한다 — 등록을 기다리는 상태(line)와 구분한다.
  for (const k of ['U','R','M']){
    const el = $('#itxEv'+k); if (!el) continue;
    const row = document.querySelector(`.evrow[data-ev-key="${k}"]`);
    const reg = row ? row.dataset.evReg : undefined;
    const missing = !row || row.classList.contains('absent-row');
    const registered = !missing && reg !== undefined && t >= +reg;
    const want = missing ? CV('na') : registered ? CV('pass') : CV('line');
    if (el.getAttribute('stroke') !== want) el.setAttribute('stroke', want);
    // 증거 제출 경로임을 업무 데이터 경로와 구분해 보인다: 재생 중이고 이미 등록된 선만 흐른다.
    el.classList.toggle('flowing', registered && playing && !reducedMotion);
    if (registered && !PB.evFired.has(k)){ PB.evFired.add(k); if (PB.primed && !reducedMotion) pulseNode('T'); }
    if (!registered) PB.evFired.delete(k);
  }
  // 등록 여부는 클래스만 바꾸고 색 전이는 CSS 가 맡는다 (프레임마다 인라인 색을 쓰면 전이가 끊긴다).
  document.querySelectorAll('.evrow[data-ev-reg]').forEach(row=>{
    const reg = +row.dataset.evReg, arrived = t>=reg;
    if (row.classList.contains('arrived') === arrived) return;
    row.classList.toggle('arrived', arrived);
    // 이미 끝난 사건을 불러올 때(primed 이전)는 안착 애니메이션을 내지 않는다 — 방금 등록된 것이 아니다.
    row.classList.toggle('settling', arrived && PB.primed && !reducedMotion);
    row.querySelector('.evstate').textContent = arrived ? `등록 ≤ ${reg} ms` : '대기';
  });
  PB.primed = true;
  const box = $('#itxTimebox');
  if (box){
    box.setAttribute('aria-valuemax', String(Math.round(PB.tEnd)));
    box.setAttribute('aria-valuenow', String(Math.round(t)));
    box.setAttribute('aria-valuetext', `t = ${Math.round(t)} ms · ${pos.leg.label}`);
  }

  const ph = $('#itxPlayhead'); if (ph) ph.style.left = PB.span(t) + '%';
  const hb = $('#itxHarmBar');
  if (hb){
    let w = 0;
    if (PB.harmExposed && PB.detectable && PB.consumedAt!=null && PB.verdictAt!=null){
      const left = PB.span(PB.consumedAt), right = PB.span(Math.min(t, PB.verdictAt));
      w = Math.max(0, right-left);
      hb.style.left = left+'%'; hb.style.width = w+'%';
    } else { hb.style.width = '0'; }
    hb.classList.toggle('empty', w <= 1); // 라벨을 띄울 자리가 없으면 막대만 남긴다
  }
}

// ---------- 1b 스윔레인: 실제 타임라인을 U/R/M/T 레인으로 피벗한다 --------------------
const KIND_LABEL = {
  contract_signed:'계약 서명', request_sent:'요청 전송', received:'요청 수신', pre_exec_check:'실행 전 검사',
  refused:'거부', inferred:'추론 완료', receipt_issued:'영수증 발행', relay_statement_issued:'중계 진술 발행',
  modified_request:'요청 변조', transformed_request:'요청 변환', rerouted:'재라우팅', stripped_binding:'결합 정보 제거',
  modified_response:'응답 변조', collusion_forged_receipt:'공모 영수증 위조', dropped_request:'요청 드롭',
  replayed_previous_response:'이전 응답 재사용', statement_omitted:'진술 미발행', stripped_inline_receipt:'영수증 제거',
  response_received:'응답 수신', error_received:'오류 수신', gate_local_checks:'로컬 검사',
  response_consumed:'업무 사용', manifest_issued:'매니페스트 발행', verdict_requested:'T 판정 조회',
  verdict_unavailable:'T 응답 없음', verdict_deadline:'기한 도달', service_down:'T 정지', service_up:'T 복구',
  checkpoint_anchored:'앵커 고정', log_tampered:'기록 재작성', gate_decision:'게이트 결정', verdict_issued:'T 판정',
};
// 증거 등록·비공개 증거 전달 같은 배관용 이벤트는 뺀다 — 이미 '증거' 패널·원장·아래 시간선에 있다.
// 스윔레인의 목적은 서사(무엇이 언제 어느 당사자에서 일어났는가)이지 전체 로그 재현이 아니다.
function swimlaneCard(r, a, consumedAt, verdictAt, harmExposed, detectable, attack, g){
  const rows = r.timeline.filter(e=>(e.actor==='U'||e.actor==='R'||e.actor==='M'||e.actor==='T')
    && (e.sub===a.sub || (e.sub===null && e.actor==='T')) && KIND_LABEL[e.kind]!==undefined);
  const lanes = rows.map(e=>{
    let label = KIND_LABEL[e.kind] || e.kind;
    let cls = '';
    if (e.kind==='gate_decision'){ label = `게이트 ${e.detail.action}`; cls = (e.detail.action==='accept'||e.detail.action==='accept_unverified') ? '' : ''; }
    if (e.kind==='verdict_issued'){ label = attack && !detectable ? '판정 (탐지 불가)' : `T 판정 ${e.detail.status}`; }
    if (e.kind==='modified_response') cls='fail';
    if (e.kind==='modified_request') cls='fail';
    if (e.kind==='response_consumed' && harmExposed) cls='fail';
    if (e.kind==='gate_decision' && (g.action==='accept'||g.action==='accept_unverified') && attack) cls='fail';
    if (e.kind==='gate_decision' && (g.action==='quarantine'||g.action==='reject'||g.action==='reject_timeout')) cls='pass';
    return {seq:e.seq, t:e.t, actor:e.actor, label, cls};
  });
  const cell = (row, actor)=> row.actor===actor ? `<span class="${row.cls}">${esc(row.label)}</span>` : '<span class="muted">·</span>';
  const body = lanes.map(row=>`<tr><td class="muted">${row.seq}</td><td class="mono">${row.t}</td>
    <td>${cell(row,'U')}</td><td>${cell(row,'R')}</td><td>${cell(row,'M')}</td><td>${cell(row,'T')}</td></tr>`).join('');
  const gapVisible = consumedAt!==null && attack && harmExposed && verdictAt!=null;
  const tEndLocal = Math.max(consumedAt||0, verdictAt||0, 1) * 1.1;
  const gapPct = gapVisible ? Math.min(88, ((verdictAt-consumedAt)/tEndLocal)*100+6) : 0;
  const gapNote = !detectable && attack
    ? `이 사건은 증거 구조로 탐지할 수 없다 (${esc(a.ground_truth.attack_kind)}). 간격 자체가 정의되지 않는다.`
    : consumedAt===null
      ? '결정 전 소비 없음 — 간격이 0 이다. 이것이 protect·strict 가 사는 이유다.'
      : gapVisible ? `observe 모드라면 응답은 ${consumedAt} ms 에 소비되고 T 판정은 ${verdictAt} ms 에 등록된다. 이 화면의 목적은 그 간격을 숨기지 않는 것이다.`
        : '정상 사건. 소비와 판정 사이의 위험 간격 없음.';
  return `<div class="card"><h3>스윔레인 — 수집기 시퀀스 정렬</h3>
    <p class="small muted" style="margin:0 0 8px">정렬 기준은 각 당사자의 시계가 아니라 수집기가 등록한 순서(seq)다. t 는 시뮬레이션 시계이며 등록 시각은 상한으로 별도 표시된다.</p>
    <div class="tablewrap"><table style="font-size:12px"><thead><tr><th>seq</th><th>t ms</th><th>U</th><th>R</th><th>M</th><th style="color:${CV('accent')}">T</th></tr></thead><tbody>${body}</tbody></table></div>
    <h3>탐지 ≠ 방어</h3>
    <div class="gapbox"><div class="gapaxis"></div>
      ${gapVisible?`<div class="gapfill" style="left:4%;width:${gapPct}%"></div>`:''}
      <div class="gaplabel-l">${consumedAt===null?'소비 없음':'소비 '+consumedAt+' ms'}</div>
      <div class="gaplabel-r">${(!detectable&&attack)?'탐지 불가':verdictAt!=null?'탐지 '+verdictAt+' ms':'—'}</div>
    </div>
    <p class="small" style="margin-top:4px">${gapNote}</p></div>`;
}

// ---------- 1c 원장형: 이 사건에 등록된 진술 + 외부 앵커 ------------------------------
function ledgerCard(r, a){
  const rows = (a.registered||[]).map(x=>`<tr><td class="muted">${x.index}</td>
    <td>${esc(x.content_type.replace('application/vnd.itx.','').replace('+json',''))}</td>
    <td class="mono">${esc(x.iss.replace('urn:itx:party:',''))}</td>
    <td class="mono">≤ ${x.registered_at}</td>
    <td class="mono">${short(x.statement_hash)}</td></tr>`).join('') || '<tr><td colspan="5" class="absent">등록된 진술 없음</td></tr>';
  const ts = r.ts;
  const anch = ts.anchor_record;
  const av = ts.anchors && ts.anchors[0];
  const anchorRow = av
    ? `<tr><td class="mono">${av.tree_size}</td><td class="mono">${short(av.anchored_root)}</td><td class="mono">${short(av.recomputed_root)}</td>
        <td class="${av.ok?'pass':'fail'}">${esc(av.reason)}</td></tr>`
    : '<tr><td colspan="4" class="absent">앵커 없음</td></tr>';
  const showTamperDemo = r.run.scenario_id !== 'S14';
  return `<div class="card"><h3>원장형 — 추가 전용 로그와 외부 앵커</h3>
    <p class="small muted" style="margin:0 0 8px">블록체인의 자리는 여기 하나다 — T 가 나중에 다른 과거를 제시하지 못하게 하는 외부 체크포인트. 이 표는 실제 등록 원장이며 임의로 값을 바꾸는 시연 버튼은 두지 않는다.</p>
    <div class="tablewrap"><table style="font-size:12px"><thead><tr><th>#</th><th>진술 유형</th><th>발행</th><th>≤ 등록</th><th>해시</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="tablewrap" style="margin-top:10px"><table><thead><tr><th>앵커 크기</th><th>앵커에 고정된 루트</th><th>현재 재계산 루트</th><th>판정</th></tr></thead><tbody>${anchorRow}</tbody></table></div>
    ${showTamperDemo
      ? `<p class="small" style="margin-top:8px">운영자가 과거 항목을 실제로 교체하면 어떻게 되는지는 <button type="button" class="ledgerlink" data-jump="S14">S14 — T 의 기록 재작성</button> 시나리오에서 그대로 볼 수 있다. 트리는 다시 계산돼 스스로는 깨지지 않지만, 앵커된 루트와 달라지고 일관성 증명이 실패한다.</p>`
      : `<p class="small fail" style="margin-top:8px">이 시나리오는 앵커 이후 항목 #${ts.tampered_index} 을 교체한 사건이다. 위 판정 칸이 '재작성 감지' 로 바뀐 것을 확인한다 — 트리 자체는 재계산돼 깨지지 않았지만 외부에 고정한 루트와 달라졌다.</p>`}
  </div>`;
}
document.addEventListener('click', e=>{
  const btn = e.target.closest('button[data-jump]');
  if (btn){ cur.sid = btn.dataset.jump; cur.attempt = 0; onSelectionChanged(); window.scrollTo({top:0,behavior:reducedMotion?'auto':'smooth'}); $('#scenarioTabs').scrollIntoView({block:'center'}); }
});

// ---------- 1d 판정 불확실성 표현 3종 --------------------------------------------------
let curU = { sid:'S03', coop:'U' };
function renderUncertainty(){
  const rows = D.q1_matrix;
  const sids = [...new Set(rows.map(r=>r.scenario_id))];
  buildTabs($('#uncScTabs'), sids.map(s=>({v:s,label:s})), it=>it.v===curU.sid, v=>{curU.sid=v;renderUncertainty();});
  buildTabs($('#uncCoopTabs'), ['U','U+M','U+R','U+R+M'].map(c=>({v:c,label:c})), it=>it.v===curU.coop, v=>{curU.coop=v;renderUncertainty();});
  const full = rows.find(r=>r.scenario_id===curU.sid && r.cooperation==='U+R+M');
  const row = rows.find(r=>r.scenario_id===curU.sid && r.cooperation===curU.coop);
  const title = row.title;
  const establishedCodes = row.codes;
  const missingCodes = full.codes.filter(c=>!row.codes.includes(c));
  const coopSet = new Set(curU.coop.split('+'));
  const statusStyle = row.verification_status==='insufficient_evidence'
    ? `background:${CV('card')};border:1px dashed ${CV('na')};color:${CV('na')}`
    : `background:${CV('card')};border:1px solid ${CV(st(row.verification_status))};color:${CV(st(row.verification_status))}`;
  const gateStyle = (row.gate_action==='accept'||row.gate_action==='accept_unverified')
    ? `background:${CV('chip')};color:${CV('muted')}` : `background:${CV('card')};border:1px solid ${CV('fail')};color:${CV('fail')}`;

  const meter = ['U','R','M'].map(p=>`<span class="meter-sq" style="background:${coopSet.has(p)?CV('accent'):CV('card')};${coopSet.has(p)?'':'border:1px dashed '+CV('na')}"></span>`).join('');
  const missingParties = ['U','R','M'].filter(p=>!coopSet.has(p));

  const ladder = [];
  ladder.push(`<div class="ladder-row"><span class="ladder-tag pass">확립</span><span>U 가 서명한 요청 계약과 수신 진술의 자기 결합 (${esc(curU.coop)} 협조 수준에서 항상 확인 가능).</span></div>`);
  if (establishedCodes.length) ladder.push(`<div class="ladder-row"><span class="ladder-tag pass">확립</span><span>이 협조 수준에서 이미 드러난 위반: ${establishedCodes.map(esc).join(', ')}.</span></div>`);
  if (missingCodes.length) ladder.push(`<div class="ladder-row"><span class="ladder-tag na">미확립</span><span>이 협조 수준에서는 감춰짐: ${missingCodes.map(esc).join(', ')}. 필요한 증거: ${missingParties.map(p=>p==='R'?'R 중계 진술':'M 추론 영수증').join(', ')||'없음'}.</span></div>`);
  ladder.push(`<div class="ladder-row"><span class="ladder-tag ${(row.gate_action==='accept'||row.gate_action==='accept_unverified')?'na':'fail'}">조치</span><span>protect 정책상 게이트 결정: <span class="mono">${esc(row.gate_action)}</span>.</span></div>`);

  $('#uncertainty').innerHTML = `<div class="card"><p class="small muted" style="margin:0 0 10px">${esc(title)} — 협조 <b>${esc(curU.coop)}</b> (전체 U+R+M 결과와 비교)</p>
  <div class="grid">
    <div class="card"><div class="mono" style="font-size:10.5px;color:${CV('na')};margin:0 0 7px">(i) 세 상태 배지 — 가장 보수적</div>
      <div class="badge3">
        <span style="${statusStyle}">${esc(row.verification_status)}</span>
        <span style="background:${CV('chip')};color:${CV('muted')}">completeness: ${esc(row.completeness)}</span>
        <span style="${gateStyle}">gate: ${esc(row.gate_action)}</span>
      </div>
      <p class="small" style="margin-top:7px">판정과 집행이 서로 다른 축임이 드러난다. 대신 "왜 부족한가" 가 안 보인다.</p></div>
    <div class="card"><div class="mono" style="font-size:10.5px;color:${CV('na')};margin:0 0 7px">(ii) 증거 커버리지 눈금 계량기 — 실측과의 거리</div>
      <div style="display:flex;align-items:center;gap:10px">${meter}<span class="mono small">${curU.coop} 협조${missingParties.length?' · '+missingParties.map(p=>p+' 결손').join(', '):''}</span></div>
      <p class="small" style="margin-top:7px">종단 등식(E10)을 세우려면 M 영수증이 필요하다는 사실이 칸 수로 보인다. 다만 "칸이 많을수록 좋다" 로 오독될 위험이 있어 사용자 시험이 필요하다.</p></div>
    <div class="card"><div class="mono" style="font-size:10.5px;color:${CV('na')};margin:0 0 7px">(iii) 확립/미확립 서술 사다리</div>
      ${ladder.join('')}
      <p class="small" style="margin-top:7px">논문·발표에 가장 잘 읽힌다. 운영 콘솔에는 길다.</p></div>
  </div></div>`;
}

// ---------- 1e 애니메이션 메모 (정적 — 섹션 3 재생 기능의 실제 구현 여부를 함께 표기) --------
(function(){
  const IMPL = 'background:var(--chip);color:var(--pass)', PLANNED = 'background:var(--chip);color:var(--na)';
  const items = [
    {title:'요청의 이동과 진술 발행', spec:'섹션 3 재생 · 실제 홉 지연 비례', impl:true,
     body:'U→R→M→R→U 를 점 하나가 지난다. 구간 경계는 임의 데모 수치가 아니라 이 시도의 실제 sent_at/received_at 과 시뮬레이션 지연 상수(홉 20ms·중개 처리 5ms·서명 2ms)에서 역산한 것이다. 이동 구간은 정지에서 출발해 정지로 끝나므로 가감속을 주고, 노드를 드나드는 수직 구간을 넣어 꺾은선 위를 실제로 타고 돈다.'},
    {title:'진행 방향 잔상', spec:'섹션 3 재생 · 18px 꼬리', impl:true,
     body:'점 뒤로 지나온 경로를 22px 만큼 되짚은 반투명 꼬리를 길이·두께·농도가 다른 세 겹으로 그린다. 꼬리는 경로의 꺾임과 구간 경계를 그대로 따라가며, 노드에 도착해 머무는 동안에는 길이가 0 으로 줄어든다. 홉 구간은 추론 구간보다 10배 짧아 한 프레임에 크게 건너뛰므로 재생 중에는 그 간격만큼 꼬리를 늘린다 — 속도를 읽게 할 뿐 어떤 판정도 나타내지 않는다.'},
    {title:'노드 도달 펄스', spec:'섹션 3 재생 · 1회성 fade', impl:true,
     body:'패킷이 U/R/M 상자에 닿는 순간 그 상자에만 1회성 테두리 fade 를 낸다 (620ms, 흐름 색). 반복·점멸하지 않고 잔상도 남기지 않는다. 뒤로 이동하면 다시 낼 수 있게 초기화되고, 선택을 바꿔 최종 상태로 들어올 때는 내지 않는다 — 방금 일어난 일이 아니기 때문이다.'},
    {title:'변조의 순간', spec:'섹션 3 재생 · 색 전이만', impl:true,
     body:'요청 변조(E4 실패)는 R→M 구간에서, 응답 변조(E10 실패)는 M→R 구간부터 점과 꼬리의 색이 파랑에서 빨강으로 바뀐다. 폭발·흔들림 없이 색과 라벨만 바꾼다. 실제로 실패한 등식에서 색을 가져오므로 시나리오마다 자동으로 맞다.'},
    {title:'증거 제출 경로의 흐름', spec:'섹션 3 T 점선 · 대시 오프셋', impl:true,
     body:'T 로 가는 점선은 업무 데이터 경로(실선)와 다른 성격이므로, 재생 중이면서 이미 등록된 선만 대시 오프셋이 천천히 흐른다. 등록 전이거나 결손인 선은 정지해 있고, 정지·완료 상태에서는 전부 멈춘다. 증거가 T 에 닿는 순간 T 상자에 1회성 펄스를 낸다.'},
    {title:'증거 등록의 도달', spec:'섹션 3 증거 패널 · 320ms 페이드 + 안착', impl:true,
     body:'재생 시점이 각 진술의 등록 시각(상한)을 지나면 그 행과 T 로 가는 점선이 대기색에서 pass 색으로 넘어가고 3px 만큼 제자리로 안착한다. 프레임마다 인라인 색을 쓰지 않고 상태 클래스만 바꿔 전이가 끊기지 않게 했다. 결손 행은 전이 대상에서 제외한다 — 부재는 어떤 경우에도 움직이지 않는다.'},
    {title:'임의 시점 탐색', spec:'섹션 3 시점 타임라인 · 스크러버', impl:true,
     body:'타임라인을 누르거나 끌면 그 시점으로 바로 간다. |◀ ▶| 는 홉 경계 단위로 한 걸음씩 옮기고, 속도는 ×0.5/×1/×2 로 바꾼다. 초점이 타임라인이나 재생 컨트롤에 있을 때 Space 는 재생·정지, ←/→ 는 홉 이동, Home/End 는 처음·끝이다.'},
    {title:'탐지와 소비의 간격', spec:'섹션 3 시점 타임라인 + 스윔레인(1b) 하단', impl:true,
     body:'소비 지점에서 T 판정 등록 지점까지 붉은 막대가 실제 시간 비율대로 자란다. 막대가 길수록 나쁜 것이 아니라 "무엇이 그 사이에 실행되었는가" 를 묻게 만드는 장치다.'},
    {title:'증거가 늘며 바뀌는 판정', spec:'섹션 5 (1d) · 탭 전환', impl:true,
     body:'협조 집합 탭을 U → U+M/U+R → U+R+M 으로 늘리면 같은 사건의 배지·사다리가 실제 Q1 매트릭스 값으로 바뀐다. 탭을 누를 때만 바뀌고 나머지는 정지한다 — 별도 애니메이션은 넣지 않았다.'},
    {title:'해시 체인과 외부 앵커', spec:'섹션 3 원장형(1c) · S14 로 이동', impl:false,
     body:'항목을 교체하면 그 이후 행의 해시가 순서대로 빨갛게 물들고 앵커 비교 행이 불일치로 바뀌는 연쇄 애니메이션은 아직 만들지 않았다. 대신 실제로 재작성이 일어난 S14 시나리오로 바로 이동하는 링크를 두었다 — 가짜 수치로 연출하지 않기 위해서다.'},
    {title:'모드 전환', spec:'섹션 3 · 탭 전환', impl:true,
     body:'observe/protect/strict 를 바꾸면 경로와 증거는 그대로 있고 시간선의 결정·소비 표시와 게이트 패널만 바뀐다. 크로스페이드는 넣지 않았고 즉시 갱신된다 — 같은 사건에서 정책만 달라졌음을 보이는 데는 애니메이션이 굳이 필요하지 않았다.'},
  ];
  $('#animNotes').innerHTML = items.map(a=>`<div class="animnote"><div style="font:600 12.5px 'IBM Plex Sans KR',system-ui">${esc(a.title)}
    <span class="mono muted" style="font-size:11px">${esc(a.spec)}</span>
    <span class="animstatus" style="${a.impl?IMPL:PLANNED}">${a.impl?'구현됨':'미구현'}</span></div>
    <div class="small" style="color:var(--fg);line-height:1.5">${esc(a.body)}</div></div>`).join('')
    + `<p class="small muted" style="margin-top:10px;padding-top:10px;border-top:1px solid var(--line)">공통 규칙: 모션은 인과를 보이는 데만 쓰고 강조에는 쓰지 않는다. 결손·미실행은 절대 움직이지 않는다. <span class="mono">prefers-reduced-motion</span> 에서는 이 페이지의 모든 재생이 최종 상태로 즉시 점프한다.</p>`;
})();

// ---------- Q1
(function(){
  const rows = D.q1_matrix; const coops = ['U','U+M','U+R','U+R+M']; const sids = [...new Set(rows.map(r=>r.scenario_id))];
  const cell = (r)=>r?`<div class="${st(r.verification_status)}">${r.verification_status}</div><div class="small">${r.codes.length?r.codes.map(esc).join('<br>'):'<span class="absent">코드 없음</span>'}</div><div class="small muted">완전성 ${r.completeness} · 게이트 ${esc(r.gate_action)}</div>`:'-';
  $('#q1').innerHTML = `<table><thead><tr><th>위반 시나리오</th>${coops.map(c=>`<th>${c}</th>`).join('')}</tr></thead><tbody>${sids.map(s=>{const t=rows.find(r=>r.scenario_id===s).title;return `<tr><td><b>${s}</b><div class="small">${esc(t)}</div></td>${coops.map(c=>`<td>${cell(rows.find(r=>r.scenario_id===s&&r.cooperation===c))}</td>`).join('')}</tr>`;}).join('')}</tbody></table>`;
})();

// ---------- 등식 라벨 <-> 등식표·집행 칩 양방향 연동, 해시 복사 ----------
(function(){
  let current = null;
  const mark = (id, on)=>{ if(!id) return; document.querySelectorAll(`[data-eq="${CSS.escape(id)}"]`).forEach(n=>n.classList.toggle('eq-hi', on)); };
  const point = (e)=>{
    const n = e.target && e.target.closest ? e.target.closest('[data-eq]') : null;
    const id = n ? n.dataset.eq : null;
    if (id === current) return;
    mark(current, false); current = id; mark(current, true);
  };
  document.addEventListener('mouseover', point);
  document.addEventListener('focusin', point);

  async function copyText(text){
    if (!text) return false;
    try { await navigator.clipboard.writeText(text); return true; } catch(e) {}
    try {
      const ta = document.createElement('textarea');
      ta.value = text; ta.setAttribute('readonly',''); ta.style.position='fixed'; ta.style.opacity='0';
      document.body.appendChild(ta); ta.select();
      const ok = document.execCommand('copy'); ta.remove(); return ok;
    } catch(e) { return false; }
  }
  const flash = (n, message)=>{
    n.dataset.flash = message; n.classList.add('copied');
    setTimeout(()=>{ n.classList.remove('copied'); delete n.dataset.flash; }, 1200);
  };
  document.addEventListener('click', e=>{
    const n = e.target && e.target.closest ? e.target.closest('[data-copy]') : null;
    if (!n) return;
    e.preventDefault();
    copyText(n.dataset.copy||'').then(ok=>flash(n, ok?'복사됨':'복사 실패'));
  });
  document.addEventListener('keydown', e=>{
    if (e.key!=='Enter' && e.key!==' ') return;
    const n = e.target && e.target.closest ? e.target.closest('[data-copy][tabindex]') : null;
    if (!n) return;
    e.preventDefault(); n.click();
  });
})();

onSelectionChanged();
renderUncertainty();
</script>
"""


def build_report(bundle: dict[str, Any], artifact: bool = False) -> str:
    """artifact=False: 완전한 HTML 문서. artifact=True: <title>·<style>·본문만 (게시 도구가 골격을 덧씌움)."""
    data = json.dumps(bundle, ensure_ascii=False).replace("</", "<\\/")
    body = _BODY.replace("__DATA__", data)
    head = f"<title>{_TITLE}</title>\n{_FONTS}\n{_STYLE}\n"
    if artifact:
        return head + body
    return (
        '<!DOCTYPE html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"{head}</head>\n<body>\n{body}</body>\n</html>\n"
    )
