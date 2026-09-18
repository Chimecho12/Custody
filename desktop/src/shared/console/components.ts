import type { Data } from '../types';
import { esc, cls, short, CV } from './format';

export function pills(container: HTMLElement, items: {v: string; label: string; title?: string}[], isOn: (v: string) => boolean, onPick: (v: string) => void) {
  container.innerHTML = items.map(it => `<button type="button" class="pill${isOn(it.v) ? ' on' : ''}" data-v="${esc(it.v)}"${it.title ? ` title="${esc(it.title)}"` : ''}>${esc(it.label)}</button>`).join('');
  const buttons = [...container.querySelectorAll<HTMLButtonElement>('button')];
  buttons.forEach((b, i) => {
    b.addEventListener('click', () => onPick(b.dataset.v!));
    // 탭 묶음 안에서는 방향키로 이동한다. 선택은 바뀌지 않고 초점만 옮긴다.
    b.addEventListener('keydown', e => {
      const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      if (!d) return;
      e.preventDefault(); buttons[(i + d + buttons.length) % buttons.length].focus();
    });
  });
}

// ---------- 홉 지도 ----------
export interface HopLabel { id: string; x: number; y: number; anchor: 'start' | 'mid' | 'end'; tail: string; result: string; edge?: boolean; big?: boolean }
export interface HopEdges { ur: string; rm: string; mr: string; ru: string; e2e: string }
type Pos = [string, number, number, 'start' | 'mid' | 'end', string];

export const EQ_POS: Pos[] = [
  ['E12', 30, 44, 'start', '유효기간'], ['E1', 30, 60, 'start', '자기 정합'],
  ['E5', 410, 44, 'mid', 'nonce 결합'], ['E8', 410, 60, 'mid', '승인 경로'],
  ['E9', 790, 44, 'end', '아티팩트'], ['E11', 790, 60, 'end', '시도 결합'],
  ['E2', 270, 82, 'mid', '요청 U→R'], ['E3', 570, 82, 'mid', '진술 R↔M'],
  ['E4', 570, 108, 'mid', '승인 변환 재계산'], ['E6', 570, 208, 'mid', '응답 M→R'],
  ['E7', 270, 208, 'mid', '응답 R→U'],
  ['E10', 410, 284, 'mid', '종단 응답 결합 — M 이 서명한 응답 == U 가 받은 응답'],
];
// 런타임 U Agent 의 로컬 검사를 같은 지도에 놓는다. 검사 이름은 itx/enforce/user_gate.py 의 키다.
export const CHECK_POS: Pos[] = [
  ['not_expired', 30, 44, 'start', '계약 유효기간'], ['tool_policy', 30, 60, 'start', '도구 실행 정책'],
  ['nonce_match', 410, 44, 'mid', 'nonce 결합'], ['route_allowed', 410, 60, 'mid', '허용 모델 경로'],
  ['model_hash_reference', 790, 44, 'end', '등록 기준 해시'], ['attempt_match', 790, 60, 'end', '시도 ID 결합'],
  ['request_binding', 270, 82, 'mid', '승인된 요청 결합'], ['R_authority', 570, 82, 'mid', 'R 발행자·역할 인증'],
  ['receipt_signature', 570, 108, 'mid', '영수증 서명'], ['M_authority', 570, 208, 'mid', 'M 발행자·역할 인증'],
  ['receipt_present', 270, 208, 'mid', '모델 영수증 동봉'],
  ['response_binding', 410, 284, 'mid', '종단 응답 결합 — M 이 서명한 응답 == U 가 받은 응답'],
];
const EDGE_IDS = new Set(['E2', 'E3', 'E6', 'E7', 'request_binding', 'R_authority', 'M_authority', 'receipt_present']);
function labelsFrom(pos: Pos[], results: Data, bigId: string): HopLabel[] {
  return pos.map(([id, x, y, anchor, tail]) => ({id, x, y, anchor, tail, result: (results[id] || {}).result || 'not_evaluable', edge: EDGE_IDS.has(id), big: id === bigId}));
}
export const eqLabels = (eq: Data) => labelsFrom(EQ_POS, eq, 'E10');
export const checkLabels = (checks: Data) => labelsFrom(CHECK_POS, checks, 'response_binding');
const resultOf = (m: Data, id: string) => (m[id] || {}).result || 'not_evaluable';
export const eqEdges = (eq: Data): HopEdges => ({ur: resultOf(eq, 'E2'), rm: resultOf(eq, 'E3'), mr: resultOf(eq, 'E6'), ru: resultOf(eq, 'E7'), e2e: resultOf(eq, 'E10')});
export const checkEdges = (c: Data): HopEdges => ({ur: resultOf(c, 'request_binding'), rm: resultOf(c, 'R_authority'), mr: resultOf(c, 'M_authority'), ru: resultOf(c, 'receipt_present'), e2e: resultOf(c, 'response_binding')});
export const idleEdges: HopEdges = {ur: 'not_evaluable', rm: 'not_evaluable', mr: 'not_evaluable', ru: 'not_evaluable', e2e: 'not_evaluable'};

export function hopMapHtml(key: string, labels: HopLabel[], edges: HopEdges, aria: string,
                           roles: {u: string; r: string; m: string; t: string; tSub: string} = {u: '사용자 · 집행 모듈', r: '중개자 (클라우드 대행)', m: '모델 운영자', t: 'T — 독립 제3자', tSub: '대조 · 정책 · 추가 전용 로그'}): string {
  const col = (r: string) => CV(cls(r));
  const glyph = (r: string) => r === 'pass' ? '✓' : r === 'fail' ? '✗' : '–';
  const labelHtml = labels.map(l => {
    const tx = l.anchor === 'mid' ? 'translate(-50%,-50%)' : l.anchor === 'end' ? 'translate(-100%,-50%)' : 'translate(0,-50%)';
    const size = l.big ? 12 : l.edge ? 11.5 : 11;
    return `<div class="hoplabel" data-eq="${esc(l.id)}" style="left:${(l.x / 820 * 100).toFixed(2)}%;top:${(l.y / 360 * 100).toFixed(2)}%;transform:${tx};font:${l.big ? 600 : 400} ${size}px var(--mono);color:${col(l.result)}">${glyph(l.result)} ${esc(l.id)} ${esc(l.tail)}</div>`;
  }).join('');
  // 노드 상자의 도달 펄스는 별도 halo 사각형으로 낸다. 판정 색을 쓰지 않고 흐름 색(accent)만 쓴다.
  const halo = (id: string, x: number) => `<rect class="nodehalo" id="${key}-halo-${id}" x="${x}" y="118" width="120" height="52" rx="6" fill="none" stroke="${CV('accent-glow')}" stroke-width="8"/>`;
  const svg = `<svg viewBox="0 0 820 360" role="img" aria-label="${esc(aria)}">
    <defs><marker id="${key}-ar" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="${CV('muted')}"/></marker>
      <linearGradient id="${key}-trail-gradient" gradientUnits="userSpaceOnUse" x1="100" y1="118" x2="120" y2="118" style="color:${CV('accent')}">
        <stop offset="0" stop-color="currentColor" stop-opacity="0"/><stop offset="1" stop-color="currentColor" stop-opacity=".65"/>
      </linearGradient></defs>
    <line x1="150" y1="92" x2="390" y2="92" stroke="${col(edges.ur)}" stroke-width="2.5" marker-end="url(#${key}-ar)"/>
    <line x1="470" y1="92" x2="670" y2="92" stroke="${col(edges.rm)}" stroke-width="2.5" marker-end="url(#${key}-ar)"/>
    <line x1="670" y1="188" x2="470" y2="188" stroke="${col(edges.mr)}" stroke-width="2.5" marker-end="url(#${key}-ar)"/>
    <line x1="390" y1="188" x2="150" y2="188" stroke="${col(edges.ru)}" stroke-width="2.5" marker-end="url(#${key}-ar)"/>
    <path d="M700,205 C700,268 120,268 120,205" fill="none" stroke="${col(edges.e2e)}" stroke-width="2.5" stroke-dasharray="7 4"/>
    <rect x="60" y="118" width="120" height="52" rx="6" fill="${CV('chip')}" stroke="${CV('line')}"/>
    <text x="120" y="140" text-anchor="middle" font-size="13" font-weight="700">U</text>
    <text x="120" y="157" text-anchor="middle" font-size="11" fill="${CV('muted')}">${esc(roles.u)}</text>
    <rect x="370" y="118" width="120" height="52" rx="6" fill="${CV('chip')}" stroke="${CV('line')}"/>
    <text x="430" y="140" text-anchor="middle" font-size="13" font-weight="700">R</text>
    <text x="430" y="157" text-anchor="middle" font-size="11" fill="${CV('muted')}">${esc(roles.r)}</text>
    <rect x="640" y="118" width="120" height="52" rx="6" fill="${CV('chip')}" stroke="${CV('line')}"/>
    <text x="700" y="140" text-anchor="middle" font-size="13" font-weight="700">M</text>
    <text x="700" y="157" text-anchor="middle" font-size="11" fill="${CV('muted')}">${esc(roles.m)}</text>
    ${halo('U', 60)}${halo('R', 370)}${halo('M', 640)}
    <rect x="330" y="306" width="160" height="44" rx="6" fill="${CV('card')}" stroke="${CV('accent')}" stroke-dasharray="5 3"/>
    <rect class="nodehalo" id="${key}-halo-T" x="330" y="306" width="160" height="44" rx="6" fill="none" stroke="${CV('accent-glow')}" stroke-width="8"/>
    <text x="410" y="324" text-anchor="middle" font-size="12" font-weight="700" fill="${CV('accent')}">${esc(roles.t)}</text>
    <text x="410" y="339" text-anchor="middle" font-size="10.5" fill="${CV('muted')}">${esc(roles.tSub)}</text>
    <line id="${key}-evU" class="evline" x1="120" y1="170" x2="340" y2="306" stroke="${CV('line')}" stroke-width="1.5" stroke-dasharray="4 6"/>
    <line id="${key}-evR" class="evline" x1="430" y1="170" x2="410" y2="306" stroke="${CV('line')}" stroke-width="1.5" stroke-dasharray="4 6"/>
    <line id="${key}-evM" class="evline" x1="700" y1="170" x2="480" y2="306" stroke="${CV('line')}" stroke-width="1.5" stroke-dasharray="4 6"/>
    <polyline id="${key}-trail" class="packettrail" points="" fill="none" stroke="url(#${key}-trail-gradient)" stroke-width="6" stroke-linecap="round" stroke-linejoin="round" opacity="0"/>
    <circle id="${key}-packet" class="packet" cx="120" cy="118" r="6" fill="${CV('accent')}"/>
  </svg>`;
  return `<div class="hopwrap">${svg}${labelHtml}<div class="packetlabel" data-packetlabel hidden></div></div>`;
}
export const legendRowHtml = (extra = '') =>
  `<div class="legend-row"><span class="pass">✓ pass</span><span class="fail">✗ fail</span><span class="na">– not_evaluable (사유는 표에)</span>${extra}</div>`;
// 순서는 가이드 3.2 그대로: [|◀ 처음] [◀ 이전 홉] [▶ 재생 / ❚❚ 일시정지] [다음 홉 ▶] [배속]
export const playControlsHtml = () =>
  `<div class="playctl" tabindex="-1">
    <button type="button" class="itx-btn itx-btn-step" data-reset title="처음으로 (R · Home)">|◀ 처음</button>
    <button type="button" class="itx-btn itx-btn-step" data-step="-1" title="이전 홉 (←)">◀ 이전 홉</button>
    <button type="button" class="itx-btn itx-btn-accent" data-play title="재생·정지 (Space)">▶ 재생</button>
    <button type="button" class="itx-btn itx-btn-step" data-step="1" title="다음 홉 (→)">다음 홉 ▶</button>
    <button type="button" class="itx-btn itx-btn-speed" data-speed title="재생 속도 (0.5× · 1× · 2×)" aria-label="재생 속도">1×</button>
    <span class="tlabel" data-tlabel>t = 0 ms</span>
  </div>`;

// ---------- 시점 타임라인 ----------
export interface Mark { label: string; at: string; pos: number; color: string }
export function timeBoxHtml(marks: Mark[]): string {
  const sorted = [...marks].sort((x, y) => x.pos - y.pos);
  let lastPos = -999, row = 0;
  const html = sorted.map(mk => {
    row = (mk.pos - lastPos < 7) ? (row === 0 ? 1 : 0) : 0; lastPos = mk.pos;
    return `<div class="timemark" style="top:${row ? 41 : 2}px;left:${mk.pos.toFixed(2)}%"><div class="markline"></div><div class="marklabel" style="color:${CV(mk.color)}">${esc(mk.label)}</div><div class="markat">${esc(mk.at)}</div></div>`;
  }).join('');
  return `<div class="timebox" data-scrub tabindex="0" role="slider" aria-label="재생 시점 탐색 — 드래그·방향키" aria-valuemin="0" aria-valuemax="0" aria-valuenow="0" title="클릭·드래그로 시점 이동 · ←/→ 홉 이동 · Space 재생">
    <div class="timeaxis"></div><div class="timegap" style="left:66%"></div><div class="timegaplabel" style="left:68%">축 생략</div>
    <div class="harmbar" data-harmbar style="left:0;width:0"><span class="harmlabel">피해 노출 — 사용 이후 T 판정 전</span></div>${html}
    <div class="playhead" data-playhead style="left:0"><span class="playknob"></span></div>
    <div class="scrubtip" data-scrubtip hidden></div></div>`;
}

// ---------- 증거 패널 ----------
export interface EvidenceItem { key: string; name: string; detail: string; reg: number | null; present?: boolean }
export function evidenceRowsHtml(items: EvidenceItem[]): string {
  return `<div class="evlist">` + items.map(it => {
    if (it.reg === null && !it.present) return `<div class="evrow absent-row" data-ev-key="${esc(it.key)}"><span class="evdot"></span><span class="evname">${esc(it.name)}</span><span class="evdetail">${esc(it.detail)}</span><span class="evstate">결손</span></div>`;
    if (it.reg === null) return `<div class="evrow inline-row" data-ev-key="${esc(it.key)}"><span class="evdot"></span><span class="evname">${esc(it.name)}</span><span class="evdetail">${esc(it.detail)}</span><span class="evstate">동봉 확인 · 등록 시각 미상</span></div>`;
    return `<div class="evrow" data-ev-key="${esc(it.key)}" data-ev-reg="${it.reg}"><span class="evdot"></span><span class="evname">${esc(it.name)}</span><span class="evdetail">${esc(it.detail)}</span><span class="evstate">대기</span></div>`;
  }).join('') + `</div>`;
}

// ---------- 결론·집행·등식 표 ----------
export const sevColor = (sv: string) => sv === 'violation' ? 'fail' : sv === 'contradiction' ? 'warn' : 'na';
export function codesHtml(discrepancies: Data[]): string {
  if (!discrepancies?.length) return `<div class="small absent">불일치 코드 없음</div>`;
  return discrepancies.map(d => `<div class="codebox" style="border-color:${CV(sevColor(d.severity))}">
    <div class="mono" style="font-weight:600;color:${CV(sevColor(d.severity))}">${esc(d.code)} <span style="font-weight:400;color:${CV('muted')}">· ${esc(d.severity)}</span></div>
    <div class="small">귀속 ${esc(d.attribution)} <span class="muted">— ${esc(d.attribution_basis)}</span></div></div>`).join('');
}
// 근거 종류. 같은 '통과' 라도 무엇으로 통과했는지가 다르다 — 화면은 이 다섯을 섞지 않는다.
//   measured_locally   U 가 직접 계산·비교 (해시·서명·nonce·시각·본문)
//   signed_self_report 서명은 검증했지만 내용은 서명자의 주장 (모델 id·해시·폴백 선언)
//   estimate           실측 사이를 시뮬레이션 상수 비율로 나눈 값 (홉 지도 재생 구간)
//   not_evaluable      증거가 없어 평가하지 않음 — 위반이 아니다
//   reconciled         T 가 여러 당사자의 서명 진술을 대조한 등식 (E1~E12)
// 값은 itx/enforce/user_gate.py 의 CHECK_BASIS 와 같다.
export const BASIS_LABEL: Record<string, string> = {measured_locally: 'U 실측·계산', signed_self_report: '서명된 자기보고', estimate: '추정', not_evaluable: '평가 불가', reconciled: 'T 대조 등식'};
export const basisOf = (v: any): string => !v ? 'not_evaluable' : v.result === 'not_evaluable' ? 'not_evaluable' : (v.basis || 'measured_locally');
export const basisLabel = (v: any): string => BASIS_LABEL[basisOf(v)] || String(basisOf(v));
export function checkChipsHtml(checks: Data): string {
  return `<div class="chips">` + Object.entries(checks || {}).map(([k, v]: [string, any]) =>
    `<span class="chip ${v.result === 'fail' ? 'fail' : v.result === 'not_evaluable' ? 'na' : ''}" data-eq="${esc(k)}" data-basis="${esc(basisOf(v))}" title="${esc(basisLabel(v))} — ${esc(v.reason)}">${esc(k)}</span>`).join('') + `</div>`;
}
export const gateColor = (action: string) => action === 'accept' ? 'pass' : action === 'accept_unverified' ? 'warn' : action === 'no_response' ? 'na' : 'fail';
export function equationTableHtml(eq: Data): string {
  const rows = Object.entries(eq || {}).map(([k, e]: [string, any]) => `<tr data-eq="${esc(k)}"><td><b>${esc(k)}</b> ${esc(e.title)}<div class="small muted">${esc(e.hop)}</div></td><td class="${cls(e.result)}">${esc(e.result)}</td><td>${esc(e.reason)}</td><td class="small">${(e.compared || []).map(esc).join('<br>')}</td><td class="small muted">${esc(e.trust_grade)}</td></tr>`).join('');
  return `<div class="tablewrap"><table><thead><tr><th>등식</th><th>결과</th><th>사유</th><th>비교 대상</th><th>신뢰 등급</th></tr></thead><tbody>${rows || '<tr><td colspan="5" class="absent">등식 결과 없음</td></tr>'}</tbody></table></div>`;
}
// 로컬 검사 표. 결과 옆에 근거 종류를 따로 적는다 — '일치' 가 U 의 계산인지 서명자의 자기보고인지 읽는 사람이 구별해야 한다.
export function checksTableHtml(checks: Data, names: Record<string, string>): string {
  const rows = Object.entries(checks || {}).map(([key, v]: [string, any]) =>
    `<tr data-eq="${esc(key)}"><td>${esc(names[key] || v.title || key)}<div class="small mono muted">${esc(key)}</div></td><td class="${v.result === 'pass' ? 'good' : v.result === 'fail' ? 'bad' : 'muted'}">${v.result === 'pass' ? '일치' : v.result === 'fail' ? '실패' : '미확인'}</td><td class="small ${basisOf(v) === 'signed_self_report' ? 'warn' : 'muted'}">${esc(basisLabel(v))}</td><td class="muted">${esc(v.reason)}</td></tr>`).join('');
  return `<div class="tablewrap"><table class="checks"><thead><tr><th>검사 항목</th><th>결과</th><th>근거 종류</th><th>사유</th></tr></thead><tbody>${rows || '<tr><td colspan="4" class="absent">검사 결과 없음</td></tr>'}</tbody></table></div>`;
}
export function stripGridHtml(cells: {k: string; v: string; color?: string}[]): string {
  return `<div class="stripgrid">` + cells.map(c => `<div class="stripcell"><div class="k">${esc(c.k)}</div><div class="v"${c.color ? ` style="color:${CV(c.color)}"` : ''}>${c.v}</div></div>`).join('') + `</div>`;
}
