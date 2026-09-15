// 경로검증 콘솔의 공용 시각 요소. 보고서(itx/report/html.py)의 구현을 앱 안으로 옮긴 것이다.
// 홉 지도 좌표는 Claude Design 탐색안 1a 를 그대로 쓴다. 색은 항상 실제 검사·등식 결과에서 나온다.
// 모션 규칙: 인과(패킷의 이동·도달·증거 등록)를 보이는 데만 쓴다. 강조·장식에는 쓰지 않는다.
// 결손·미실행은 움직이지 않는다. prefers-reduced-motion 이면 재생 없이 최종 상태로 즉시 간다.
export type Data = Record<string, any>;

export const esc = (s: unknown): string =>
  String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c] as string));
export const cls = (r: string | undefined | null) => r === 'pass' ? 'pass' : r === 'fail' ? 'fail' : 'na';
export const st = (s: string | undefined | null) => s === 'passed' ? 'pass' : s === 'failed' ? 'fail' : 'warn';
// 해시·커밋은 앞 12자만 보이고, 누르면 전체 값을 클립보드로 복사한다 (Rekor 의 항목 해시 취급과 같은 방식).
export const short = (h: unknown) => h
  ? `<span class="hashchip" data-copy="${esc(h)}" role="button" tabindex="0" title="클릭하면 전체 값을 복사합니다">${esc(String(h).slice(0, 12))}…</span>`
  : '<span class="absent">없음</span>';
export const absent = (v: unknown) => (v === null || v === undefined) ? '<span class="absent">null</span>' : esc(v);
export const CV = (name: string) => `var(--${name})`;
export const reducedMotion = (() => { try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch { return false; } })();

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
  const halo = (id: string, x: number) => `<rect class="nodehalo" id="${key}-halo-${id}" x="${x}" y="118" width="120" height="52" rx="6" fill="none" stroke="${CV('accent')}" stroke-width="2"/>`;
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
    ${halo('U', 60)}${halo('R', 370)}${halo('M', 640)}
    <rect x="330" y="306" width="160" height="44" rx="6" fill="${CV('card')}" stroke="${CV('accent')}" stroke-dasharray="5 3"/>
    <rect class="nodehalo" id="${key}-halo-T" x="330" y="306" width="160" height="44" rx="6" fill="none" stroke="${CV('accent')}" stroke-width="2"/>
    <text x="410" y="324" text-anchor="middle" font-size="12" font-weight="700" fill="${CV('accent')}">${esc(roles.t)}</text>
    <text x="410" y="339" text-anchor="middle" font-size="10.5" fill="${CV('muted')}">${esc(roles.tSub)}</text>
    <line id="${key}-evU" class="evline" x1="120" y1="170" x2="340" y2="306" stroke="${CV('line')}" stroke-width="1.5" stroke-dasharray="4 4"/>
    <line id="${key}-evR" class="evline" x1="430" y1="170" x2="410" y2="306" stroke="${CV('line')}" stroke-width="1.5" stroke-dasharray="4 4"/>
    <line id="${key}-evM" class="evline" x1="700" y1="170" x2="480" y2="306" stroke="${CV('line')}" stroke-width="1.5" stroke-dasharray="4 4"/>
    ${[1, 2, 3].map(i => `<polyline id="${key}-trail${i}" class="packettrail" points="" fill="none" stroke="${CV('accent')}" stroke-width="${9 - i}" stroke-linecap="round" stroke-linejoin="round" opacity="0"/>`).join('')}
    <circle id="${key}-packet" class="packet" cx="120" cy="118" r="8" fill="${CV('accent')}"/>
  </svg>`;
  return `<div class="hopwrap">${svg}${labelHtml}<div class="packetlabel" data-packetlabel hidden></div></div>`;
}
export const legendRowHtml = (extra = '') =>
  `<div class="legend-row"><span class="pass">✓ pass</span><span class="fail">✗ fail</span><span class="na">– not_evaluable (사유는 표에)</span>${extra}</div>`;
export const playControlsHtml = () =>
  `<div class="playctl" tabindex="-1">
    <button type="button" class="itx-btn itx-btn-step" data-step="-1" title="이전 홉 (←)" aria-label="이전 홉">|◀</button>
    <button type="button" class="itx-btn itx-btn-accent" data-play title="재생·정지 (Space)">▶ 재생</button>
    <button type="button" class="itx-btn itx-btn-step" data-step="1" title="다음 홉 (→)" aria-label="다음 홉">▶|</button>
    <button type="button" class="itx-btn" data-reset title="처음으로 (R · Home)">처음으로</button>
    <button type="button" class="itx-btn itx-btn-speed" data-speed title="재생 속도" aria-label="재생 속도">×1</button>
    <span class="tlabel" data-tlabel>t = 0 ms</span>
  </div>`;

// ---------- 재생 구간: 시작·수신 시각 사이를 홉·처리·서명 비율로 나눈다 ----------
// 홉 20ms · 중개 처리 5ms · 서명 2ms 는 itx/sim/context.py 의 시뮬레이션 지연 상수와 같다.
export const HOP_MS = 20, PROC_MS = 5, SIGN_MS = 2;
export const MODEL_LATENCY_MS: Record<string, number> = {'model-A': 200, 'model-A-small': 80, 'model-B': 150};
export type NodeKey = 'U' | 'R' | 'M' | 'T';
export type Pt = [number, number];
// 구간은 꺾은선(pts)으로 둔다. 노드를 드나드는 수직 구간이 있어야 패킷이 선 위를 실제로 타고 도는 것처럼 보인다.
export interface Leg { t0: number; t1: number; pts: Pt[]; label: string; work: boolean; arrive?: NodeKey }

const seg = (a: Pt, b: Pt) => Math.hypot(b[0] - a[0], b[1] - a[1]);
function cumulative(pts: Pt[]): number[] { const c = [0]; for (let i = 1; i < pts.length; i++) c.push(c[i - 1] + seg(pts[i - 1], pts[i])); return c; }
function atDist(pts: Pt[], c: number[], d: number): Pt {
  const total = c[c.length - 1];
  if (total <= 0) return [pts[0][0], pts[0][1]];
  const x = Math.max(0, Math.min(total, d));
  for (let i = 1; i < pts.length; i++) {
    if (x <= c[i] || i === pts.length - 1) {
      const len = c[i] - c[i - 1], f = len > 0 ? (x - c[i - 1]) / len : 0;
      return [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * f, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * f];
    }
  }
  return [pts[pts.length - 1][0], pts[pts.length - 1][1]];
}
// 이동 구간은 정지에서 출발해 정지로 끝나므로 가감속을 준다. 노드 안 구간은 앞부분에서 자리를 잡고 머문다.
const easeInOut = (f: number) => f < .5 ? 2 * f * f : 1 - Math.pow(-2 * f + 2, 2) / 2;
const settle = (f: number) => 1 - Math.pow(1 - Math.min(1, f / 0.28), 3);

export function computeLegs(sentAt: number, receivedAt: number, latency = 200): Leg[] {
  const raw: Leg[] = []; let t = 0;
  const push = (dt: number, pts: Pt[], label: string, work: boolean, arrive?: NodeKey) => { raw.push({t0: t, t1: t + dt, pts, label, work, arrive}); t += dt; };
  push(HOP_MS, [[120, 118], [120, 100], [430, 100]], '요청 전송 U→R', false, 'R');
  push(PROC_MS, [[430, 100]], 'R 중개자 처리', true);
  push(HOP_MS, [[430, 100], [700, 100]], '요청 전달 R→M', false, 'M');
  push(latency, [[700, 100], [700, 118]], 'M 추론', true);
  push(SIGN_MS, [[700, 118]], 'M 영수증 서명', true);
  push(HOP_MS, [[700, 118], [700, 196], [430, 196]], '응답 전달 M→R', false, 'R');
  push(SIGN_MS, [[430, 196]], 'R 중계 진술 서명', true);
  push(HOP_MS, [[430, 196], [120, 196], [120, 170]], '응답 전송 R→U', false, 'U');
  const scale = (t > 0 && receivedAt > sentAt) ? (receivedAt - sentAt) / t : 1;
  return raw.map(L => ({...L, t0: sentAt + L.t0 * scale, t1: sentAt + L.t1 * scale}));
}
export function packetPos(t: number, legs: Leg[]) {
  if (t <= legs[0].t0) { const p = legs[0].pts[0]; return {x: p[0], y: p[1], leg: legs[0], index: 0, f: 0}; }
  let index = 0;
  for (let i = 0; i < legs.length; i++) if (t >= legs[i].t0) index = i;
  const L = legs[index];
  const raw = Math.max(0, Math.min(1, (t - L.t0) / Math.max(1, L.t1 - L.t0)));
  const f = L.work ? settle(raw) : easeInOut(raw);
  const c = cumulative(L.pts), p = atDist(L.pts, c, f * c[c.length - 1]);
  return {x: p[0], y: p[1], leg: L, index, f};
}
// 노드에 머무는 구간에서는 잔상이 구간 앞 30% 안에 0 으로 줄어든다 — 도착해서 멈췄다는 사실을 남긴다.
export function trailLength(t: number, legs: Leg[], base = 18): number {
  const cur = packetPos(t, legs), L = cur.leg;
  if (!L.work) return base;
  const decay = Math.max(1, (L.t1 - L.t0) * 0.3);
  return base * Math.max(0, 1 - (t - L.t0) / decay);
}
// 진행 방향 뒤쪽으로 maxLen 만큼의 잔상 좌표를 되짚는다. 꺾이는 지점과 구간 경계를 그대로 따라간다.
export function trailPoints(t: number, legs: Leg[], maxLen = 18): Pt[] {
  const cur = packetPos(t, legs);
  const out: Pt[] = [[cur.x, cur.y]];
  if (maxLen <= 0.5) return out;
  let remain = maxLen, i = cur.index, f = cur.f;
  while (remain > 0.5 && i >= 0) {
    const pts = legs[i].pts, c = cumulative(pts);
    let pos = f * c[c.length - 1];
    for (let k = pts.length - 1; k >= 0 && remain > 0.5; k--) {
      if (c[k] >= pos) continue;
      const step = pos - c[k];
      if (step >= remain) { out.push(atDist(pts, c, pos - remain)); remain = 0; break; }
      out.push([pts[k][0], pts[k][1]]); remain -= step; pos = c[k];
    }
    i--; f = 1;
  }
  return out;
}
// 시점 축: breakpoint 까지 4~64%, 그 뒤(축 생략 표시 이후) 72~96%. inv 는 스크러버가 쓰는 역함수다.
export interface Span { (ms: number): number; inv(pct: number): number }
export function makeSpan(breakpoint: number, tEnd: number): Span {
  const f = ((ms: number) => { const v = Math.min(Math.max(ms, 0), tEnd); return v <= breakpoint ? 4 + (v / breakpoint) * 60 : 72 + ((v - breakpoint) / Math.max(1, tEnd - breakpoint)) * 24; }) as Span;
  f.inv = (pct: number) => {
    const p = Math.min(Math.max(pct, 0), 100);
    const ms = p <= 4 ? 0
      : p <= 64 ? ((p - 4) / 60) * breakpoint
      : p < 72 ? breakpoint // 축 생략 구간에서는 breakpoint 에 붙인다
      : breakpoint + ((p - 72) / 24) * Math.max(1, tEnd - breakpoint);
    return Math.min(Math.max(ms, 0), tEnd); // 축 오른쪽 여백(96~100%)은 끝 시점으로 모은다
  };
  return f;
}

// ---------- 재생 엔진 ----------
export interface PlayContext {
  legs: Leg[]; tEnd: number; span: Span;
  reqFail: boolean; respFail: boolean;
  consumedAt: number | null; verdictAt: number | null; harmExposed: boolean; detectable: boolean;
}
const SPEEDS = [0.5, 1, 2];
export class Playback {
  private t = 0; private playing = false; private raf = 0; private last: number | null = null; private ctx: PlayContext | null = null;
  private speed = 1; private fired = new Set<number>(); private fill = ''; private scrub: HTMLElement | null = null;
  private prev: {x: number; y: number} | null = null;
  private evFired = new Set<string>(); private primed = false;
  constructor(private root: HTMLElement, private key: string) {
    root.addEventListener('click', e => {
      const b = (e.target as HTMLElement).closest('button');
      if (!b || !root.contains(b)) return;
      if (b.hasAttribute('data-play')) this.toggle();
      else if (b.hasAttribute('data-reset')) { this.stop(); this.seek(0); }
      else if (b.hasAttribute('data-step')) { this.stop(); this.step(+b.getAttribute('data-step')!); }
      else if (b.hasAttribute('data-speed')) { this.speed = SPEEDS[(SPEEDS.indexOf(this.speed) + 1) % SPEEDS.length]; this.button(); }
    });
    // 시점 타임라인 스크러버: 누른 자리로 바로 이동하고 드래그로 따라간다.
    root.addEventListener('pointerdown', e => {
      const box = (e.target as HTMLElement).closest<HTMLElement>('[data-scrub]');
      if (!box || !this.ctx) return;
      e.preventDefault(); this.stop(); this.scrub = box; box.setPointerCapture(e.pointerId); box.focus();
      this.seekAt(box, e.clientX);
    });
    root.addEventListener('pointermove', e => { if (this.scrub) this.seekAt(this.scrub, e.clientX); });
    const end = (e: PointerEvent) => { if (!this.scrub) return; try { this.scrub.releasePointerCapture(e.pointerId); } catch { /* 이미 해제됨 */ } this.scrub = null; };
    root.addEventListener('pointerup', end);
    root.addEventListener('pointercancel', end);
    // 키보드: 스크러버나 재생 컨트롤에 초점이 있을 때만 받는다. 입력란의 방향키를 빼앗지 않는다.
    root.addEventListener('keydown', e => {
      const target = e.target as HTMLElement;
      if (!target.closest('[data-scrub]') && !target.closest('.playctl')) return;
      if (e.key === ' ' || e.key === 'Spacebar') { if (target.closest('button')) return; e.preventDefault(); this.toggle(); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); this.stop(); this.step(-1); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); this.stop(); this.step(1); }
      else if (e.key === 'Home' || e.key === 'r' || e.key === 'R') { e.preventDefault(); this.stop(); this.seek(0); }
      else if (e.key === 'End' && this.ctx) { e.preventDefault(); this.stop(); this.seek(this.ctx.tEnd); }
    });
  }
  // 선택이 바뀌면 완결된 최종 상태에서 시작한다. 이때는 도달 펄스를 내지 않는다 — 방금 일어난 일이 아니다.
  set(ctx: PlayContext | null) {
    this.stop(); this.ctx = ctx; this.t = ctx ? ctx.tEnd : 0; this.fill = '';
    this.fired = new Set(ctx ? ctx.legs.map((_, i) => i) : []);
    this.evFired.clear(); this.primed = false; this.prev = null;
    this.button(); this.update();
  }
  stop() { this.playing = false; if (this.raf) cancelAnimationFrame(this.raf); this.raf = 0; this.last = null; this.prev = null; this.button(); }
  toggle() {
    if (!this.ctx) return;
    if (reducedMotion) { this.seek(this.ctx.tEnd); return; } // 축소 모션: 최종 상태로 즉시 점프
    if (this.playing) { this.stop(); return; }
    if (this.t >= this.ctx.tEnd) this.seek(0);
    this.playing = true; this.last = null; this.button();
    this.raf = requestAnimationFrame(ts => this.step2(ts));
  }
  seek(v: number) {
    if (!this.ctx) return;
    const next = Math.max(0, Math.min(this.ctx.tEnd, v));
    if (next < this.t) for (const i of [...this.fired]) if (this.ctx.legs[i].t1 > next) this.fired.delete(i);
    this.t = next; this.update();
  }
  // 홉 경계(구간 시작·끝)로만 이동한다. 어떤 구간에서 무엇이 바뀌는지 한 걸음씩 확인하는 용도다.
  step(dir: number) {
    if (!this.ctx) return;
    const marks = [...new Set([0, ...this.ctx.legs.map(l => l.t0), ...this.ctx.legs.map(l => l.t1), this.ctx.tEnd])]
      .filter(v => v >= 0 && v <= this.ctx!.tEnd).sort((a, b) => a - b);
    const eps = 0.5;
    const next = dir > 0 ? marks.find(v => v > this.t + eps) : [...marks].reverse().find(v => v < this.t - eps);
    this.seek(next ?? (dir > 0 ? this.ctx.tEnd : 0));
  }
  private seekAt(box: HTMLElement, clientX: number) {
    if (!this.ctx) return;
    const r = box.getBoundingClientRect();
    if (r.width <= 0) return;
    this.seek(this.ctx.span.inv(((clientX - r.left) / r.width) * 100));
  }
  private step2(ts: number) {
    if (!this.playing || !this.ctx) return;
    const dt = this.last != null ? Math.min(64, ts - this.last) : 16; this.last = ts;
    const base = Math.max(0.05, this.ctx.tEnd / 3200); // 실측 길이와 무관하게 ×1 재생은 약 3초, 구간 비율은 실제 값 그대로
    let nt = this.t + dt * base * this.speed;
    if (nt >= this.ctx.tEnd) { nt = this.ctx.tEnd; this.playing = false; }
    this.seek(nt);
    if (this.playing) this.raf = requestAnimationFrame(t => this.step2(t)); else this.button();
  }
  private button() {
    const b = this.root.querySelector<HTMLButtonElement>('button[data-play]');
    if (b) b.textContent = this.playing ? '⏸ 일시정지' : '▶ 재생';
    const s = this.root.querySelector<HTMLButtonElement>('button[data-speed]');
    if (s) s.textContent = '×' + this.speed;
  }
  private pulse(node: NodeKey) {
    const el = this.root.querySelector<SVGElement>(`#${this.key}-halo-${node}`);
    if (!el) return;
    el.classList.remove('pulse'); void el.getBoundingClientRect(); el.classList.add('pulse');
  }
  // 패킷 위치·잔상·색, 증거 도달선, 재생 헤드, 피해 막대만 갱신한다. 나머지는 정적이다.
  update() {
    const label = this.root.querySelector<HTMLElement>('[data-tlabel]');
    const c = this.ctx;
    if (!c) { if (label) label.textContent = 't = 0 ms'; return; }
    const t = this.t, lastLeg = c.legs[c.legs.length - 1];
    if (label) label.textContent = `t = ${Math.round(t)} ms`;
    const pos = packetPos(t, c.legs);
    let fill = 'accent';
    if (t >= lastLeg.t1) fill = 'muted';
    if (c.reqFail && t >= c.legs[1].t0 && t < c.legs[4].t0) fill = 'fail';
    if (c.respFail && t >= c.legs[6].t0) fill = 'fail';
    const changed = fill !== this.fill; this.fill = fill;

    const dot = this.root.querySelector(`#${this.key}-packet`);
    if (dot) { dot.setAttribute('cx', pos.x.toFixed(1)); dot.setAttribute('cy', pos.y.toFixed(1)); if (changed) dot.setAttribute('fill', CV(fill)); }
    // 홉 구간은 추론 구간보다 10배 짧아 한 프레임에 크게 건너뛴다. 재생 중에는 그 간격만큼 꼬리를 늘려
    // 이동이 끊겨 보이지 않게 한다 — 속도를 그대로 드러내는 것이고 판정과는 무관하다.
    const jump = this.prev ? Math.hypot(pos.x - this.prev.x, pos.y - this.prev.y) : 0;
    this.prev = {x: pos.x, y: pos.y};
    const base = this.playing ? Math.max(22, Math.min(44, jump * 1.6)) : 22;
    const inTransit = !reducedMotion && t > c.legs[0].t0 && t < lastLeg.t1;
    const full = inTransit ? trailLength(t, c.legs, base) : 0;
    // 꼬리는 길이·두께·농도가 다른 세 겹으로 그린다. 방향이 꺾여도 그러데이션처럼 잦아든다.
    for (const [i, share, alpha] of [[1, 1, .10], [2, .6, .16], [3, .3, .24]] as [number, number, number][]) {
      const layer = this.root.querySelector<SVGElement>(`#${this.key}-trail${i}`);
      if (!layer) continue;
      const pts = full > 0.5 ? trailPoints(t, c.legs, full * share) : [];
      layer.setAttribute('points', pts.map(p => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' '));
      if (changed) layer.setAttribute('stroke', CV(fill));
      layer.style.opacity = pts.length > 1 ? String(alpha) : '0';
    }
    const moving = t > c.legs[0].t0 && t < lastLeg.t1;
    const plabel = this.root.querySelector<HTMLElement>('[data-packetlabel]');
    if (plabel) {
      plabel.hidden = !moving;
      if (moving) {
        plabel.textContent = pos.leg.label;
        plabel.style.left = (pos.x / 820 * 100).toFixed(2) + '%';
        plabel.style.top = (pos.y / 360 * 100).toFixed(2) + '%';
        plabel.style.transform = pos.y < 150 ? 'translate(-50%,-180%)' : 'translate(-50%,80%)';
      }
    }
    if (!reducedMotion) for (let i = 0; i < c.legs.length; i++) {
      const L = c.legs[i];
      if (L.arrive && !this.fired.has(i) && t >= L.t1) { this.fired.add(i); this.pulse(L.arrive); }
    }
    for (const k of ['U', 'R', 'M']) {
      const line = this.root.querySelector<SVGElement>(`#${this.key}-ev${k}`);
      const row = this.root.querySelector<HTMLElement>(`.evrow[data-ev-key="${k}"]`);
      if (!line) continue;
      const reg = row?.dataset.evReg;
      const missing = !row || row.classList.contains('absent-row');
      const registered = !missing && reg !== undefined && t >= +reg;
      const want = missing ? CV('na') : registered ? CV('pass') : CV('line');
      if (line.getAttribute('stroke') !== want) line.setAttribute('stroke', want);
      // 증거 제출 경로임을 업무 데이터 경로와 구분해 보인다: 재생 중이고 이미 등록된 선만 흐른다.
      // 결손 선은 어떤 경우에도 움직이지 않는다.
      line.classList.toggle('flowing', registered && this.playing && !reducedMotion);
      if (registered && !this.evFired.has(k)) { this.evFired.add(k); if (this.primed && !reducedMotion) this.pulse('T'); }
      if (!registered) this.evFired.delete(k);
    }
    // 등록 여부는 클래스만 바꾸고 색 전이는 CSS 가 맡는다 (프레임마다 인라인 스타일을 쓰면 전이가 끊긴다).
    this.root.querySelectorAll<HTMLElement>('.evrow[data-ev-reg]').forEach(row => {
      const reg = +row.dataset.evReg!, arrived = t >= reg;
      if (row.classList.contains('arrived') === arrived) return;
      row.classList.toggle('arrived', arrived);
      // 이미 끝난 사건을 불러올 때(primed 이전)는 안착 애니메이션을 내지 않는다 — 방금 등록된 것이 아니다.
      row.classList.toggle('settling', arrived && this.primed && !reducedMotion);
      const state = row.querySelector<HTMLElement>('.evstate')!;
      state.textContent = arrived ? `등록 ≤ ${reg} ms` : '대기';
    });
    this.primed = true;
    const ph = this.root.querySelector<HTMLElement>('[data-playhead]'); if (ph) ph.style.left = c.span(t) + '%';
    const box = this.root.querySelector<HTMLElement>('[data-scrub]');
    if (box) { box.setAttribute('aria-valuemax', String(Math.round(c.tEnd))); box.setAttribute('aria-valuenow', String(Math.round(t))); box.setAttribute('aria-valuetext', `t = ${Math.round(t)} ms · ${pos.leg.label}`); }
    const hb = this.root.querySelector<HTMLElement>('[data-harmbar]');
    if (hb) {
      let w = 0;
      if (c.harmExposed && c.detectable && c.consumedAt != null && c.verdictAt != null) {
        const left = c.span(c.consumedAt), right = c.span(Math.min(t, c.verdictAt));
        w = Math.max(0, right - left);
        hb.style.left = left + '%'; hb.style.width = w + '%';
      } else hb.style.width = '0';
      hb.classList.toggle('empty', w <= 1); // 라벨을 띄울 자리가 없으면 막대만 남긴다
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
  return `<div class="timebox" data-scrub tabindex="0" role="slider" aria-label="재생 시점 탐색 — 드래그·방향키" aria-valuemin="0" aria-valuemax="0" aria-valuenow="0" title="클릭·드래그로 시점 이동 · ←/→ 홉 이동 · Space 재생">
    <div class="timeaxis"></div><div class="timegap" style="left:66%"></div><div class="timegaplabel" style="left:68%">축 생략</div>
    <div class="harmbar" data-harmbar style="left:0;width:0"><span class="harmlabel">피해 노출 — 사용 이후 T 판정 전</span></div>${html}
    <div class="playhead" data-playhead style="left:0"><span class="playknob"></span></div></div>`;
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
export function checkChipsHtml(checks: Data): string {
  return `<div class="chips">` + Object.entries(checks || {}).map(([k, v]: [string, any]) =>
    `<span class="chip ${v.result === 'fail' ? 'fail' : v.result === 'not_evaluable' ? 'na' : ''}" data-eq="${esc(k)}" title="${esc(v.reason)}">${esc(k)}</span>`).join('') + `</div>`;
}
export const gateColor = (action: string) => action === 'accept' ? 'pass' : action === 'accept_unverified' ? 'warn' : action === 'no_response' ? 'na' : 'fail';
export function equationTableHtml(eq: Data): string {
  const rows = Object.entries(eq || {}).map(([k, e]: [string, any]) => `<tr data-eq="${esc(k)}"><td><b>${esc(k)}</b> ${esc(e.title)}<div class="small muted">${esc(e.hop)}</div></td><td class="${cls(e.result)}">${esc(e.result)}</td><td>${esc(e.reason)}</td><td class="small">${(e.compared || []).map(esc).join('<br>')}</td><td class="small muted">${esc(e.trust_grade)}</td></tr>`).join('');
  return `<div class="tablewrap"><table><thead><tr><th>등식</th><th>결과</th><th>사유</th><th>비교 대상</th><th>신뢰 등급</th></tr></thead><tbody>${rows || '<tr><td colspan="5" class="absent">등식 결과 없음</td></tr>'}</tbody></table></div>`;
}
export function checksTableHtml(checks: Data, names: Record<string, string>): string {
  const rows = Object.entries(checks || {}).map(([key, v]: [string, any]) =>
    `<tr data-eq="${esc(key)}"><td>${esc(names[key] || v.title || key)}<div class="small mono muted">${esc(key)}</div></td><td class="${v.result === 'pass' ? 'good' : v.result === 'fail' ? 'bad' : 'muted'}">${v.result === 'pass' ? '일치' : v.result === 'fail' ? '실패' : '미확인'}</td><td class="muted">${esc(v.reason)}</td></tr>`).join('');
  return `<div class="tablewrap"><table class="checks"><thead><tr><th>검사 항목</th><th>결과</th><th>근거</th></tr></thead><tbody>${rows || '<tr><td colspan="3" class="absent">검사 결과 없음</td></tr>'}</tbody></table></div>`;
}
export function stripGridHtml(cells: {k: string; v: string; color?: string}[]): string {
  return `<div class="stripgrid">` + cells.map(c => `<div class="stripcell"><div class="k">${esc(c.k)}</div><div class="v"${c.color ? ` style="color:${CV(c.color)}"` : ''}>${c.v}</div></div>`).join('') + `</div>`;
}

// ---------- 문서 전역 상호작용: 등식 ↔ 표 연동 하이라이트, 해시 복사 ----------
let installed = false;
export function installConsoleInteractions() {
  if (installed) return; installed = true;
  let current: string | null = null;
  const mark = (id: string | null, on: boolean) => {
    if (!id) return;
    document.querySelectorAll(`[data-eq="${CSS.escape(id)}"]`).forEach(n => n.classList.toggle('eq-hi', on));
  };
  // 지도 라벨·등식 표·검사 표·집행 칩은 같은 등식 id 를 쓴다. 어느 쪽을 가리켜도 나머지가 같이 밝아진다.
  const point = (e: Event) => {
    const n = (e.target as HTMLElement | null)?.closest?.<HTMLElement>('[data-eq]') ?? null;
    const id = n ? n.dataset.eq! : null;
    if (id === current) return;
    mark(current, false); current = id; mark(current, true);
  };
  document.addEventListener('mouseover', point);
  document.addEventListener('focusin', point);

  const flash = (n: HTMLElement, message: string) => {
    n.dataset.flash = message; n.classList.add('copied');
    window.setTimeout(() => { n.classList.remove('copied'); delete n.dataset.flash; }, 1200);
  };
  document.addEventListener('click', e => {
    const n = (e.target as HTMLElement).closest<HTMLElement>('[data-copy]');
    if (!n) return;
    e.preventDefault();
    copyText(n.dataset.copy || '').then(ok => flash(n, ok ? '복사됨' : '복사 실패'));
  });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const n = (e.target as HTMLElement).closest<HTMLElement>('[data-copy][tabindex]');
    if (!n) return;
    e.preventDefault(); n.click();
  });
}
async function copyText(text: string): Promise<boolean> {
  if (!text) return false;
  try { await navigator.clipboard.writeText(text); return true; } catch { /* 권한 없는 환경은 아래로 */ }
  try {
    const ta = document.createElement('textarea');
    ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.append(ta); ta.select();
    const ok = document.execCommand('copy'); ta.remove(); return ok;
  } catch { return false; }
}
