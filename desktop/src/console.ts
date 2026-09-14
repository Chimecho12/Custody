// 경로검증 콘솔의 공용 시각 요소. 보고서(itx/report/html.py)의 구현을 앱 안으로 옮긴 것이다.
// 홉 지도 좌표는 Claude Design 탐색안 1a 를 그대로 쓴다. 색은 항상 실제 검사·등식 결과에서 나온다.
export type Data = Record<string, any>;

export const esc = (s: unknown): string =>
  String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c] as string));
export const cls = (r: string | undefined | null) => r === 'pass' ? 'pass' : r === 'fail' ? 'fail' : 'na';
export const st = (s: string | undefined | null) => s === 'passed' ? 'pass' : s === 'failed' ? 'fail' : 'warn';
export const short = (h: unknown) => h ? esc(String(h).slice(0, 12)) + '…' : '<span class="absent">없음</span>';
export const absent = (v: unknown) => (v === null || v === undefined) ? '<span class="absent">null</span>' : esc(v);
export const CV = (name: string) => `var(--${name})`;
export const reducedMotion = (() => { try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch { return false; } })();

export function pills(container: HTMLElement, items: {v: string; label: string}[], isOn: (v: string) => boolean, onPick: (v: string) => void) {
  container.innerHTML = items.map(it => `<button type="button" class="pill${isOn(it.v) ? ' on' : ''}" data-v="${esc(it.v)}">${esc(it.label)}</button>`).join('');
  container.querySelectorAll<HTMLButtonElement>('button').forEach(b => b.addEventListener('click', () => onPick(b.dataset.v!)));
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
    return `<div class="hoplabel" style="left:${(l.x / 820 * 100).toFixed(2)}%;top:${(l.y / 360 * 100).toFixed(2)}%;transform:${tx};font:${l.big ? 600 : 400} ${size}px var(--mono);color:${col(l.result)}">${glyph(l.result)} ${esc(l.id)} ${esc(l.tail)}</div>`;
  }).join('');
  const svg = `<svg viewBox="0 0 820 360" role="img" aria-label="${esc(aria)}">
    <defs><marker id="${key}-ar" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="${CV('muted')}"/></marker></defs>
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
    <rect x="330" y="306" width="160" height="44" rx="6" fill="${CV('card')}" stroke="${CV('accent')}" stroke-dasharray="5 3"/>
    <text x="410" y="324" text-anchor="middle" font-size="12" font-weight="700" fill="${CV('accent')}">${esc(roles.t)}</text>
    <text x="410" y="339" text-anchor="middle" font-size="10.5" fill="${CV('muted')}">${esc(roles.tSub)}</text>
    <line id="${key}-evU" x1="120" y1="170" x2="340" y2="306" stroke="${CV('line')}" stroke-width="1.5" stroke-dasharray="4 4"/>
    <line id="${key}-evR" x1="430" y1="170" x2="410" y2="306" stroke="${CV('line')}" stroke-width="1.5" stroke-dasharray="4 4"/>
    <line id="${key}-evM" x1="700" y1="170" x2="480" y2="306" stroke="${CV('line')}" stroke-width="1.5" stroke-dasharray="4 4"/>
    <circle id="${key}-packet" cx="120" cy="196" r="8" fill="${CV('accent')}"/>
  </svg>`;
  return `<div class="hopwrap">${svg}${labelHtml}</div>`;
}
export const legendRowHtml = (extra = '') =>
  `<div class="legend-row"><span class="pass">✓ pass</span><span class="fail">✗ fail</span><span class="na">– not_evaluable (사유는 표에)</span>${extra}</div>`;
export const playControlsHtml = () =>
  `<div class="playctl"><button type="button" class="itx-btn itx-btn-accent" data-play>재생</button><button type="button" class="itx-btn" data-reset>처음으로</button><span class="tlabel" data-tlabel>t = 0 ms</span></div>`;

// ---------- 재생 구간: 시작·수신 시각 사이를 홉·처리·서명 비율로 나눈다 ----------
// 홉 20ms · 중개 처리 5ms · 서명 2ms 는 itx/sim/context.py 의 시뮬레이션 지연 상수와 같다.
export const HOP_MS = 20, PROC_MS = 5, SIGN_MS = 2;
export const MODEL_LATENCY_MS: Record<string, number> = {'model-A': 200, 'model-A-small': 80, 'model-B': 150};
export interface Leg { t0: number; t1: number; x0: number; x1: number; y: number; label: string }
export function computeLegs(sentAt: number, receivedAt: number, latency = 200): Leg[] {
  const raw: Leg[] = []; let t = 0;
  const push = (dt: number, x0: number, x1: number, y: number, label: string) => { raw.push({t0: t, t1: t + dt, x0, x1, y, label}); t += dt; };
  push(HOP_MS, 120, 430, 100, '요청 전송');
  push(PROC_MS, 430, 430, 100, '중개자 처리');
  push(HOP_MS, 430, 700, 100, '요청 전달');
  push(latency, 700, 700, 144, '추론');
  push(SIGN_MS, 700, 700, 144, '영수증 서명');
  push(HOP_MS, 700, 430, 196, '응답 전달');
  push(SIGN_MS, 430, 430, 196, '중계 진술 서명');
  push(HOP_MS, 430, 120, 196, '응답 전송');
  const scale = (t > 0 && receivedAt > sentAt) ? (receivedAt - sentAt) / t : 1;
  return raw.map(L => ({...L, t0: sentAt + L.t0 * scale, t1: sentAt + L.t1 * scale}));
}
export function packetPos(t: number, legs: Leg[]) {
  if (t <= legs[0].t0) return {x: legs[0].x0, y: legs[0].y, leg: legs[0]};
  let leg = legs[legs.length - 1];
  for (const L of legs) if (t >= L.t0) leg = L;
  const f = Math.max(0, Math.min(1, (t - leg.t0) / Math.max(1, leg.t1 - leg.t0)));
  return {x: leg.x0 + (leg.x1 - leg.x0) * f, y: leg.y, leg};
}
// 시점 축: breakpoint 까지 4~64%, 그 뒤(축 생략 표시 이후) 72~96%.
export function makeSpan(breakpoint: number, tEnd: number) {
  return (ms: number) => { const v = Math.min(Math.max(ms, 0), tEnd); return v <= breakpoint ? 4 + (v / breakpoint) * 60 : 72 + ((v - breakpoint) / Math.max(1, tEnd - breakpoint)) * 24; };
}

// ---------- 재생 엔진 ----------
export interface PlayContext {
  legs: Leg[]; tEnd: number; span: (ms: number) => number;
  reqFail: boolean; respFail: boolean;
  consumedAt: number | null; verdictAt: number | null; harmExposed: boolean; detectable: boolean;
}
export class Playback {
  private t = 0; private playing = false; private raf = 0; private last: number | null = null; private ctx: PlayContext | null = null;
  constructor(private root: HTMLElement, private key: string) {
    root.addEventListener('click', e => {
      const b = (e.target as HTMLElement).closest('button');
      if (!b || !root.contains(b)) return;
      if (b.hasAttribute('data-play')) this.toggle();
      else if (b.hasAttribute('data-reset')) { this.stop(); this.seek(0); }
    });
  }
  set(ctx: PlayContext | null) { this.stop(); this.ctx = ctx; this.t = ctx ? ctx.tEnd : 0; this.update(); }
  stop() { this.playing = false; if (this.raf) cancelAnimationFrame(this.raf); this.raf = 0; this.last = null; this.button(); }
  toggle() {
    if (!this.ctx) return;
    if (reducedMotion) { this.seek(this.ctx.tEnd); return; } // 축소 모션: 최종 상태로 즉시 점프
    if (this.playing) { this.stop(); return; }
    if (this.t >= this.ctx.tEnd) this.t = 0;
    this.playing = true; this.last = null; this.button();
    this.raf = requestAnimationFrame(ts => this.step(ts));
  }
  seek(v: number) { if (!this.ctx) return; this.t = Math.max(0, Math.min(this.ctx.tEnd, v)); this.update(); }
  private step(ts: number) {
    if (!this.playing || !this.ctx) return;
    const dt = this.last != null ? Math.min(64, ts - this.last) : 16; this.last = ts;
    const speed = Math.max(0.05, this.ctx.tEnd / 3200); // 실측 길이와 무관하게 재생은 약 3초, 구간 비율은 실제 값 그대로
    let nt = this.t + dt * speed;
    if (nt >= this.ctx.tEnd) { nt = this.ctx.tEnd; this.playing = false; }
    this.seek(nt);
    if (this.playing) this.raf = requestAnimationFrame(t => this.step(t)); else this.button();
  }
  private button() { const b = this.root.querySelector<HTMLButtonElement>('button[data-play]'); if (b) b.textContent = this.playing ? '일시정지' : '재생'; }
  // 패킷 위치·색, 증거 도달선, 재생 헤드, 피해 막대만 갱신한다. 나머지는 정적이다.
  update() {
    const label = this.root.querySelector<HTMLElement>('[data-tlabel]');
    if (!this.ctx) { if (label) label.textContent = 't = 0 ms'; return; }
    const t = this.t, c = this.ctx;
    if (label) label.textContent = `t = ${Math.round(t)} ms`;
    const pos = packetPos(t, c.legs);
    let fill = 'accent';
    if (t >= c.legs[c.legs.length - 1].t1) fill = 'muted';
    if (c.reqFail && t >= c.legs[1].t0 && t < c.legs[4].t0) fill = 'fail';
    if (c.respFail && t >= c.legs[6].t0) fill = 'fail';
    const dot = this.root.querySelector(`#${this.key}-packet`);
    if (dot) { dot.setAttribute('cx', pos.x.toFixed(1)); dot.setAttribute('cy', pos.y.toFixed(1)); dot.setAttribute('fill', CV(fill)); }
    for (const k of ['U', 'R', 'M']) {
      const line = this.root.querySelector(`#${this.key}-ev${k}`);
      const row = this.root.querySelector<HTMLElement>(`.evrow[data-ev-key="${k}"]`);
      if (!line) continue;
      const reg = row?.dataset.evReg;
      line.setAttribute('stroke', !row || row.classList.contains('absent-row') ? CV('na') : (reg !== undefined && t >= +reg ? CV('pass') : CV('line')));
    }
    this.root.querySelectorAll<HTMLElement>('.evrow[data-ev-reg]').forEach(row => {
      const reg = +row.dataset.evReg!; const arrived = t >= reg;
      row.querySelector<HTMLElement>('.evdot')!.style.background = arrived ? CV('pass') : CV('line');
      row.style.background = arrived ? CV('card') : CV('chip');
      const state = row.querySelector<HTMLElement>('.evstate')!;
      state.textContent = arrived ? `등록 ≤ ${reg} ms` : '대기'; state.style.color = arrived ? CV('pass') : CV('na');
    });
    const ph = this.root.querySelector<HTMLElement>('[data-playhead]'); if (ph) ph.style.left = c.span(t) + '%';
    const hb = this.root.querySelector<HTMLElement>('[data-harmbar]');
    if (hb) {
      if (c.harmExposed && c.detectable && c.consumedAt != null && c.verdictAt != null) {
        const left = c.span(c.consumedAt), right = c.span(Math.min(t, c.verdictAt));
        hb.style.left = left + '%'; hb.style.width = Math.max(0, right - left) + '%';
      } else hb.style.width = '0';
    }
  }
}

// ---------- 시점 타임라인 ----------
export interface Mark { label: string; at: string; pos: number; color: string }
export function timeBoxHtml(marks: Mark[]): string {
  const sorted = [...marks].sort((x, y) => x.pos - y.pos);
  let lastPos = -999, row = 0;
  const html = sorted.map(mk => {
    row = (mk.pos - lastPos < 7) ? (row === 0 ? 1 : 0) : 0; lastPos = mk.pos;
    return `<div class="timemark" style="top:${row ? 41 : 2}px;left:${mk.pos.toFixed(2)}%"><div class="markline"></div><div class="marklabel" style="color:${CV(mk.color)}">${esc(mk.label)}</div><div class="markat">${esc(mk.at)}</div></div>`;
  }).join('');
  return `<div class="timebox"><div class="timeaxis"></div><div class="timegap" style="left:66%"></div><div class="timegaplabel" style="left:68%">축 생략</div><div class="harmbar" data-harmbar style="left:0;width:0"></div>${html}<div class="playhead" data-playhead style="left:0"></div></div>`;
}

// ---------- 증거 패널 ----------
export interface EvidenceItem { key: string; name: string; detail: string; reg: number | null; present?: boolean }
export function evidenceRowsHtml(items: EvidenceItem[]): string {
  return `<div class="evlist">` + items.map(it => {
    if (it.reg === null && !it.present) return `<div class="evrow absent-row" data-ev-key="${esc(it.key)}"><span class="evdot" style="background:transparent;border:1px dashed ${CV('na')}"></span><span class="evname">${esc(it.name)}</span><span class="evdetail">${esc(it.detail)}</span><span class="evstate">결손</span></div>`;
    if (it.reg === null) return `<div class="evrow" data-ev-key="${esc(it.key)}"><span class="evdot" style="background:${CV('accent')}"></span><span class="evname">${esc(it.name)}</span><span class="evdetail">${esc(it.detail)}</span><span class="evstate">동봉 확인 · 등록 시각 미상</span></div>`;
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
export function checkChipsHtml(checks: Data): string {
  return `<div class="chips">` + Object.entries(checks || {}).map(([k, v]: [string, any]) =>
    `<span class="chip ${v.result === 'fail' ? 'fail' : v.result === 'not_evaluable' ? 'na' : ''}" title="${esc(v.reason)}">${esc(k)}</span>`).join('') + `</div>`;
}
export const gateColor = (action: string) => action === 'accept' ? 'pass' : action === 'accept_unverified' ? 'warn' : action === 'no_response' ? 'na' : 'fail';
export function equationTableHtml(eq: Data): string {
  const rows = Object.entries(eq || {}).map(([k, e]: [string, any]) => `<tr><td><b>${esc(k)}</b> ${esc(e.title)}<div class="small muted">${esc(e.hop)}</div></td><td class="${cls(e.result)}">${esc(e.result)}</td><td>${esc(e.reason)}</td><td class="small">${(e.compared || []).map(esc).join('<br>')}</td><td class="small muted">${esc(e.trust_grade)}</td></tr>`).join('');
  return `<div class="tablewrap"><table><thead><tr><th>등식</th><th>결과</th><th>사유</th><th>비교 대상</th><th>신뢰 등급</th></tr></thead><tbody>${rows || '<tr><td colspan="5" class="absent">등식 결과 없음</td></tr>'}</tbody></table></div>`;
}
export function checksTableHtml(checks: Data, names: Record<string, string>): string {
  const rows = Object.entries(checks || {}).map(([key, v]: [string, any]) =>
    `<tr><td>${esc(names[key] || v.title || key)}<div class="small mono muted">${esc(key)}</div></td><td class="${v.result === 'pass' ? 'good' : v.result === 'fail' ? 'bad' : 'muted'}">${v.result === 'pass' ? '일치' : v.result === 'fail' ? '실패' : '미확인'}</td><td class="muted">${esc(v.reason)}</td></tr>`).join('');
  return `<div class="tablewrap"><table class="checks"><thead><tr><th>검사 항목</th><th>결과</th><th>근거</th></tr></thead><tbody>${rows || '<tr><td colspan="3" class="absent">검사 결과 없음</td></tr>'}</tbody></table></div>`;
}
export function stripGridHtml(cells: {k: string; v: string; color?: string}[]): string {
  return `<div class="stripgrid">` + cells.map(c => `<div class="stripcell"><div class="k">${esc(c.k)}</div><div class="v"${c.color ? ` style="color:${CV(c.color)}"` : ''}>${c.v}</div></div>`).join('') + `</div>`;
}
