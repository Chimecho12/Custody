// 경로검증 콘솔의 공용 시각 요소. 보고서(itx/report/html.py)의 구현을 앱 안으로 옮긴 것이다.
// 홉 지도 좌표는 Claude Design 탐색안 1a 를 그대로 쓴다. 색은 항상 실제 검사·등식 결과에서 나온다.
// 모션 규칙: 인과(패킷의 이동·도달·증거 등록)를 보이는 데만 쓴다. 강조·장식에는 쓰지 않는다.
// 결손·미실행은 움직이지 않는다. prefers-reduced-motion 이면 재생 없이 최종 상태로 즉시 간다.
import type { Data } from './types';

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
const motionPreference = typeof window === 'undefined' ? null : window.matchMedia('(prefers-reduced-motion: reduce)');
export let reducedMotion = motionPreference?.matches ?? false;
motionPreference?.addEventListener('change', e => { reducedMotion = e.matches; });

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
    <circle id="${key}-ripple" class="packet-ripple" cx="120" cy="118" r="8"/>
    <circle id="${key}-aura" class="packet-aura" cx="120" cy="118" r="13" fill="${CV('accent')}"/>
    <circle id="${key}-packet" class="packet" cx="120" cy="118" r="5" fill="${CV('accent')}"/>
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

// ---------- 재생 구간: 시작·수신 시각 사이를 홉·처리·서명 비율로 나눈다 ----------
// 홉 20ms · 중개 처리 5ms · 서명 2ms 는 itx/sim/context.py 의 시뮬레이션 지연 상수와 같다.
export const HOP_MS = 20, PROC_MS = 5, SIGN_MS = 2;
export const MODEL_LATENCY_MS: Record<string, number> = {'model-A': 200, 'model-A-small': 80, 'model-B': 150};
export type NodeKey = 'U' | 'R' | 'M' | 'T';
export type Pt = [number, number];
// 구간은 꺾은선(pts)으로 둔다. 노드를 드나드는 수직 구간이 있어야 패킷이 선 위를 실제로 타고 도는 것처럼 보인다.
// arrive 는 이동 구간이 닿는 노드, at 은 머무는 구간이 속한 노드다 (노드 활성 상태 표시에 쓴다).
export interface Leg { t0: number; t1: number; pts: Pt[]; label: string; work: boolean; arrive?: NodeKey; at?: NodeKey }
// 기본 꼴은 옛 SVG 좌표계(820×360)다. flow.ts 는 그래프 배치에서 뽑은 꼴을 넘겨 같은 시간 배분을 쓴다.
export const DEFAULT_SHAPE: Pt[][] = [
  [[120, 118], [120, 100], [430, 100]], [[430, 100]], [[430, 100], [700, 100]], [[700, 100], [700, 118]],
  [[700, 118]], [[700, 118], [700, 196], [430, 196]], [[430, 196]], [[430, 196], [120, 196], [120, 170]],
];

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
// 꺾은선의 꼭짓점을 반지름 r 의 2차 베지에로 둥글린다. flow.ts 의 smoothstep(r=14) 과 같은 곡률이라
// 패킷이 그려진 선 위를 그대로 탄다 — 직각에서 관성 없이 꺾이지 않는다. 짧은 변에서는 반지름을 그 절반으로 줄인다.
export const FILLET_R = 14;
export function filletPolyline(pts: Pt[], r = FILLET_R, samples = 6): Pt[] {
  if (pts.length < 3) return pts;
  const out: Pt[] = [pts[0]];
  for (let i = 1; i < pts.length - 1; i++) {
    const a = pts[i - 1], v = pts[i], b = pts[i + 1], la = seg(a, v), lb = seg(v, b);
    const d = Math.min(r, la / 2, lb / 2);
    if (d < 0.5) { out.push(v); continue; }
    const p1: Pt = [v[0] + (a[0] - v[0]) / la * d, v[1] + (a[1] - v[1]) / la * d];
    const p2: Pt = [v[0] + (b[0] - v[0]) / lb * d, v[1] + (b[1] - v[1]) / lb * d];
    for (let k = 0; k <= samples; k++) {
      const u = k / samples, w = 1 - u;
      out.push([w * w * p1[0] + 2 * w * u * v[0] + u * u * p2[0], w * w * p1[1] + 2 * w * u * v[1] + u * u * p2[1]]);
    }
  }
  out.push(pts[pts.length - 1]);
  return out;
}
// 이동 구간은 정지에서 출발해 정지로 끝나므로 가감속을 준다. 노드 안 구간은 앞부분에서 자리를 잡고 머문다.
const easeInOut = (f: number) => f < .5 ? 2 * f * f : 1 - Math.pow(-2 * f + 2, 2) / 2;
const settle = (f: number) => 1 - Math.pow(1 - Math.min(1, f / 0.28), 3);

export function computeLegs(sentAt: number, receivedAt: number, latency = 200, shape: Pt[][] = DEFAULT_SHAPE): Leg[] {
  const raw: Leg[] = []; let t = 0;
  shape = shape.map(p => filletPolyline(p));
  const push = (dt: number, pts: Pt[], label: string, work: boolean, arrive?: NodeKey, at?: NodeKey) => { raw.push({t0: t, t1: t + dt, pts, label, work, arrive, at}); t += dt; };
  push(HOP_MS, shape[0], '요청 전송 U→R', false, 'R');
  push(PROC_MS, shape[1], 'R 중개자 처리', true, undefined, 'R');
  push(HOP_MS, shape[2], '요청 전달 R→M', false, 'M');
  push(latency, shape[3], 'M 추론', true, undefined, 'M');
  push(SIGN_MS, shape[4], 'M 영수증 서명', true, undefined, 'M');
  push(HOP_MS, shape[5], '응답 전달 M→R', false, 'R');
  push(SIGN_MS, shape[6], 'R 중계 진술 서명', true, undefined, 'R');
  push(HOP_MS, shape[7], '응답 전송 R→U', false, 'U');
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
function packetLabel(t: number, legs: Leg[]): string {
  return t < legs[0].t0 ? '전송 전' : t >= legs[legs.length - 1].t1 ? '응답 수신 후' : packetPos(t, legs).leg.label;
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

// ---------- 인지 시간(재생 벽시계) ↔ 실측 시간(t) ----------
// 화면의 t · 눈금 · 홉 경계 · aria 값은 전부 실측이다. 재생이 그 시간축을 지나가는 '속도' 만 구간마다 다르게 둔다:
// 20 ms 홉은 눈이 궤적을 쫓을 수 있도록 최소 480 ms 를, 200 ms 추론은 멈춘 것처럼 보이지 않도록 최대 750 ms 를 쓴다.
// 수치를 왜곡하는 것이 아니라 관찰 속도를 조절하는 것이다 — 표시되는 t 는 언제나 실측 그대로다.
export const PACE = {pre: 160, move: 480, sign: 220, workMin: 350, workMax: 750, postMin: 400, postMax: 1200};
export interface Pace { p0: number; p1: number; t0: number; t1: number }
export function paceSchedule(legs: Leg[], tEnd: number): Pace[] {
  const out: Pace[] = []; let p = 0;
  const add = (t0: number, t1: number, wall: number) => { if (t1 <= t0 || wall <= 0) return; out.push({p0: p, p1: p + wall, t0, t1}); p += wall; };
  add(0, legs[0].t0, PACE.pre);
  for (const L of legs) {
    const real = L.t1 - L.t0;
    add(L.t0, L.t1, !L.work ? PACE.move : real < 30 ? PACE.sign : Math.max(PACE.workMin, Math.min(PACE.workMax, real)));
  }
  const last = legs[legs.length - 1].t1;
  add(last, tEnd, Math.max(PACE.postMin, Math.min(PACE.postMax, tEnd - last)));
  return out;
}
export const paceLength = (s: Pace[]) => s.length ? s[s.length - 1].p1 : 0;
export function tFromPace(s: Pace[], p: number): number {
  if (!s.length) return 0;
  if (p <= 0) return s[0].t0;
  for (const seg of s) if (p <= seg.p1) return seg.t0 + (seg.t1 - seg.t0) * ((p - seg.p0) / (seg.p1 - seg.p0));
  return s[s.length - 1].t1;
}
export function paceFromT(s: Pace[], t: number): number {
  if (!s.length) return 0;
  if (t <= s[0].t0) return 0;
  for (const seg of s) if (t <= seg.t1) return seg.p0 + (seg.p1 - seg.p0) * ((t - seg.t0) / (seg.t1 - seg.t0));
  return paceLength(s);
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
  private speed = 1; private fired = new Set<number>(); private fill = '';
  private pace: Pace[] = []; private wall = 0;  // 재생 벽시계 위치 — t 와 paceSchedule 로 서로 변환한다
  private scrub: {box: HTMLElement; pointerId: number} | null = null;
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
      if (!box || !this.ctx || e.button !== 0 || !e.isPrimary || this.scrub) return;
      e.preventDefault(); this.stop(); this.scrub = {box, pointerId: e.pointerId};
      box.setPointerCapture(e.pointerId); box.focus();
      this.seekAt(box, e.clientX); this.tip(box, e.clientX);
    });
    // 커서가 타임라인 위에 있으면 그 자리의 시점·홉 상태를 툴팁으로 보인다. 드래그 중에는 재생 헤드가 그 자리다.
    root.addEventListener('pointermove', e => {
      if (this.scrub) {
        if (e.pointerId === this.scrub.pointerId) { this.seekAt(this.scrub.box, e.clientX); this.tip(this.scrub.box, e.clientX); }
        return;
      }
      if (!e.isPrimary) return;
      const box = (e.target as HTMLElement).closest<HTMLElement>('[data-scrub]');
      if (box) this.tip(box, e.clientX); else this.tip(null);
    });
    root.addEventListener('pointerleave', () => { if (!this.scrub) this.tip(null); });
    const end = (e: PointerEvent) => { if (this.scrub?.pointerId === e.pointerId) this.endScrub(); };
    root.addEventListener('pointerup', e => {
      if (this.scrub?.pointerId === e.pointerId) { this.seekAt(this.scrub.box, e.clientX); this.endScrub(); }
    });
    root.addEventListener('pointercancel', end);
    root.addEventListener('lostpointercapture', end);
    // 키보드: 스크러버나 재생 컨트롤에 초점이 있을 때만 받는다. 입력란의 방향키를 빼앗지 않는다.
    root.addEventListener('keydown', e => {
      const target = e.target as HTMLElement;
      if (e.defaultPrevented || e.isComposing || e.altKey || e.ctrlKey || e.metaKey) return;
      if (!target.closest('[data-scrub]') && !target.closest('.playctl')) return;
      if (e.key === ' ' || e.key === 'Spacebar') { if (target.closest('button')) return; e.preventDefault(); if (!e.repeat) this.toggle(); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); this.stop(); this.step(-1); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); this.stop(); this.step(1); }
      else if (e.key === 'Home' || e.key === 'r' || e.key === 'R') { e.preventDefault(); this.stop(); this.seek(0); }
      else if (e.key === 'End' && this.ctx) { e.preventDefault(); this.stop(); this.seek(this.ctx.tEnd); }
    });
  }
  // 선택이 바뀌면 완결된 최종 상태에서 시작한다. 이때는 도달 펄스를 내지 않는다 — 방금 일어난 일이 아니다.
  set(ctx: PlayContext | null) {
    this.endScrub(); this.stop(); this.ctx = ctx; this.t = ctx ? ctx.tEnd : 0; this.fill = '';
    this.pace = ctx ? paceSchedule(ctx.legs, ctx.tEnd) : []; this.wall = paceLength(this.pace);
    this.fired = new Set(ctx ? ctx.legs.map((_, i) => i) : []);
    this.evFired.clear(); this.primed = false; this.prev = null;
    this.button(); this.update();
  }
  // 캔버스가 노드를 접거나 배치를 바꾸면 같은 시점에서 새 기하로 다시 그린다.
  setLegs(legs: Leg[]) { if (!this.ctx) return; this.ctx.legs = legs; this.pace = paceSchedule(legs, this.ctx.tEnd); this.fill = ''; this.prev = null; this.update(); }
  stop() {
    this.playing = false; if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0; this.last = null; this.prev = null;
    this.root.querySelectorAll('.flowing, .pulse, .settling, .working, .arrive').forEach(el => el.classList.remove('flowing', 'pulse', 'settling', 'working', 'arrive'));
    this.tip(null); this.button();
  }
  toggle() {
    if (!this.ctx) return;
    if (reducedMotion) { this.stop(); this.seek(this.ctx.tEnd); return; } // 축소 모션: 최종 상태로 즉시 점프
    if (this.playing) { this.stop(); return; }
    if (this.t >= this.ctx.tEnd) this.seek(0);
    this.wall = paceFromT(this.pace, this.t);  // 스크러버로 옮긴 자리에서 이어 간다
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
  private endScrub() {
    const active = this.scrub; this.scrub = null;
    if (active?.box.hasPointerCapture(active.pointerId)) active.box.releasePointerCapture(active.pointerId);
    this.tip(null);
  }
  // 툴팁은 커서 아래 시점을 말한다: 어느 구간인지, 전송 전인지, 수신 후인지. 판정은 말하지 않는다.
  private tip(box: HTMLElement | null, clientX = 0) {
    if (!box || !this.ctx) { this.root.querySelectorAll<HTMLElement>('[data-scrubtip]').forEach(el => { el.hidden = true; }); return; }
    const el = box.querySelector<HTMLElement>('[data-scrubtip]');
    if (!el) return;
    const r = box.getBoundingClientRect();
    if (r.width <= 0) { el.hidden = true; return; }
    const pct = Math.max(0, Math.min(100, ((clientX - r.left) / r.width) * 100));
    const t = this.scrub ? this.t : this.ctx.span.inv(pct);
    el.textContent = `t = ${Math.round(t)} ms · ${packetLabel(t, this.ctx.legs)}`;
    el.hidden = false;
    const half = el.offsetWidth / 2 + 4;
    const x = (this.scrub ? this.ctx.span(t) : pct) / 100 * r.width;
    el.style.left = Math.max(half, Math.min(r.width - half, x)).toFixed(1) + 'px';
  }
  private step2(ts: number) {
    if (!this.playing || !this.ctx) return;
    if (this.root.hidden || !this.root.isConnected) { this.stop(); return; }
    if (reducedMotion) { this.stop(); this.seek(this.ctx.tEnd); return; }
    const dt = this.last != null ? Math.min(64, ts - this.last) : 16; this.last = ts;
    // 벽시계로 진행하고 실측 t 로 바꿔 그린다. ×1 재생은 구간 수에 따라 약 3.5~4초.
    const total = paceLength(this.pace);
    let nw = this.wall + dt * this.speed, nt = total ? tFromPace(this.pace, nw) : this.ctx.tEnd;
    if (nw >= total || nt >= this.ctx.tEnd) { nt = this.ctx.tEnd; nw = total; this.playing = false; }
    this.wall = nw; this.seek(nt);
    if (this.playing) this.raf = requestAnimationFrame(t => this.step2(t)); else this.button();
  }
  private button() {
    const b = this.root.querySelector<HTMLButtonElement>('button[data-play]');
    if (b) { b.textContent = this.playing ? '❚❚ 일시정지' : '▶ 재생'; b.setAttribute('aria-pressed', String(this.playing)); }
    const s = this.root.querySelector<HTMLButtonElement>('button[data-speed]');
    if (s) s.textContent = this.speed + '×';
  }
  private pulse(node: NodeKey) {
    // flow.ts 의 HTML 노드가 있으면 그 노드에, 없으면(옛 SVG 지도) halo 사각형에 1회성 펄스를 낸다.
    const el = this.root.querySelector<HTMLElement>(`.flow-node[data-node="${node}"]`) || this.root.querySelector<SVGElement>(`#${this.key}-halo-${node}`);
    if (el) { el.classList.remove('pulse'); void el.getBoundingClientRect(); el.classList.add('pulse'); }
    // 그래프 캔버스 상자(.fcnode)는 흡수로 반응한다: 1.5% 부풀었다 돌아오고, 애니메이션이 끝나면 클래스를 걷는다.
    const card = this.root.querySelector<HTMLElement>(`.fcnode[data-node="${node}"]`);
    if (card) {
      card.classList.remove('arrive'); void card.getBoundingClientRect(); card.classList.add('arrive');
      card.addEventListener('animationend', () => card.classList.remove('arrive'), {once: true});
    }
  }
  // 패킷 위치·잔상·색, 증거 도달선, 재생 헤드, 피해 막대만 갱신한다. 나머지는 정적이다.
  update() {
    const label = this.root.querySelector<HTMLElement>('[data-tlabel]');
    const c = this.ctx;
    if (!c) { if (label) label.textContent = 't = 0 ms'; return; }
    const t = this.t, lastLeg = c.legs[c.legs.length - 1];
    if (label) label.textContent = `t = ${Math.round(t)} ms · ${packetLabel(t, c.legs)}`; // 원안: t 라벨에 현재 구간
    const pos = packetPos(t, c.legs);
    let fill = 'accent';
    if (t >= lastLeg.t1) fill = 'muted';
    if (c.reqFail && t >= c.legs[1].t0 && t < c.legs[4].t0) fill = 'fail';
    if (c.respFail && t >= c.legs[5].t0) fill = 'fail'; // 원안: 응답 변조는 M→R 구간부터 붉다
    const changed = fill !== this.fill; this.fill = fill;

    const moving = t > c.legs[0].t0 && t < lastLeg.t1;
    const dot = this.root.querySelector<SVGElement>(`#${this.key}-packet`);
    if (dot) {
      dot.setAttribute('cx', pos.x.toFixed(1)); dot.setAttribute('cy', pos.y.toFixed(1));
      if (changed) {
        dot.setAttribute('fill', CV(fill));
        // 글로우는 패킷 색을 따른다. 도착해 멈춘 뒤(muted)에는 빛나지 않는다.
        dot.style.filter = fill === 'muted' ? 'none' : `drop-shadow(0 0 6px ${CV(fill + '-glow')})`;
      }
      // 노드 안에서 일하는 동안은 코어를 살짝 가라앉힌다 — 연산 중임은 노드의 호흡(flow.ts .working)이 말한다.
      dot.classList.toggle('docked', moving && pos.leg.work);
    }
    // 두 겹 패킷: 코어 뒤의 넓은 발광. 색은 코어와 같고, 도착해 멈추면 꺼진다.
    const aura = this.root.querySelector<SVGElement>(`#${this.key}-aura`);
    if (aura) {
      aura.setAttribute('cx', pos.x.toFixed(1)); aura.setAttribute('cy', pos.y.toFixed(1));
      if (changed) { aura.setAttribute('fill', CV(fill)); aura.classList.toggle('off', fill === 'muted'); }
    }
    // 변조의 순간: 색이 바뀌는 그 프레임에 붉은 파문 하나와 짧은 흔들림을 딱 한 번 낸다. 재생 중에만 — 스크러버로 지나갈 때는 색만 바뀐다.
    if (changed && fill === 'fail' && this.playing && !reducedMotion) {
      const ripple = this.root.querySelector<SVGElement>(`#${this.key}-ripple`);
      if (ripple) { ripple.setAttribute('cx', pos.x.toFixed(1)); ripple.setAttribute('cy', pos.y.toFixed(1)); ripple.classList.remove('go'); void ripple.getBoundingClientRect(); ripple.classList.add('go'); }
      if (dot) { dot.classList.remove('hit'); void dot.getBoundingClientRect(); dot.classList.add('hit'); }
    }
    // 홉 구간은 추론 구간보다 10배 짧아 한 프레임에 크게 건너뛴다. 재생 중에는 그 간격만큼 꼬리를 늘려
    // 이동이 끊겨 보이지 않게 한다 — 속도를 그대로 드러내는 것이고 판정과는 무관하다. 기본 길이는 20px.
    const jump = this.prev ? Math.hypot(pos.x - this.prev.x, pos.y - this.prev.y) : 0;
    this.prev = {x: pos.x, y: pos.y};
    const base = this.playing ? Math.max(30, Math.min(46, jump * 1.6)) : 22; // 재생 중 최소 30px — 홉이 느려진 만큼 꼬리로 방향을 남긴다
    const inTransit = !reducedMotion && t > c.legs[0].t0 && t < lastLeg.t1;
    const full = inTransit ? trailLength(t, c.legs, base) : 0;
    // 실제 SVG 그라데이션을 꼬리→패킷 방향으로 정렬한다. 꺾은선의 좌표는 그대로 유지한다.
    const layer = this.root.querySelector<SVGElement>(`#${this.key}-trail`);
    const gradient = this.root.querySelector<SVGElement>(`#${this.key}-trail-gradient`);
    if (layer && gradient) {
      const pts = full > 0.5 ? trailPoints(t, c.legs, full) : [];
      layer.setAttribute('points', pts.map(p => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' '));
      if (changed) gradient.style.color = CV(fill);
      if (pts.length > 1) {
        const tail = pts[pts.length - 1];
        gradient.setAttribute('x1', String(tail[0])); gradient.setAttribute('y1', String(tail[1]));
        gradient.setAttribute('x2', String(pos.x)); gradient.setAttribute('y2', String(pos.y));
      }
      layer.style.opacity = pts.length > 1 ? '1' : '0';
    }
    const plabel = this.root.querySelector<HTMLElement>('[data-packetlabel]');
    if (plabel) {
      plabel.hidden = !moving;
      if (moving) {
        plabel.textContent = pos.leg.label;
        // 위·아래 자리는 프레임이 아니라 구간 단위로 정한다 — 한 구간을 지나는 동안 라벨이 뒤집히지(jitter) 않는다.
        const legTop = Math.min(...pos.leg.pts.map(p => p[1]));
        if (plabel.hasAttribute('data-px')) { // flow 뷰포트 안에서는 그래프 좌표(px)를 그대로 쓴다
          plabel.style.left = pos.x.toFixed(1) + 'px'; plabel.style.top = pos.y.toFixed(1) + 'px';
          plabel.style.transform = legTop < 100 ? 'translate(-50%,calc(-100% - 14px))' : 'translate(-50%,16px)';
        } else {
          plabel.style.left = (pos.x / 820 * 100).toFixed(2) + '%';
          plabel.style.top = (pos.y / 360 * 100).toFixed(2) + '%';
          plabel.style.transform = legTop < 150 ? 'translate(-50%,calc(-100% - 12px))' : 'translate(-50%,14px)';
        }
      }
    }
    // 노드 상태: 패킷이 머무는 노드만 active (X6 식 상태 표시). 미니맵의 점도 같이 옮긴다.
    // 캔버스(flow.ts)에 프레임을 알린다 — 도달 링 감쇠·상태 머신은 그쪽이 그린다. 재생 엔진은 캔버스를 모른다.
    const flow = this.root.querySelector<HTMLElement>(`.flowc[data-flow="${this.key}"]`);
    if (flow && typeof CustomEvent === 'function' && typeof flow.dispatchEvent === 'function') flow.dispatchEvent(new CustomEvent('playbackframe', {bubbles: true, detail: {t, legs: c.legs, playing: this.playing}}));
    if (!reducedMotion) for (let i = 0; i < c.legs.length; i++) {
      const L = c.legs[i];
      if (L.arrive && !this.fired.has(i) && t >= L.t1) { this.fired.add(i); if (this.playing) this.pulse(L.arrive); }
    }
    for (const k of ['U', 'R', 'M']) {
      const line = this.root.querySelector<SVGElement>(`#${this.key}-ev${k}`);
      const row = this.root.querySelector<HTMLElement>(`.evrow[data-ev-key="${k}"]`);
      if (!line) continue;
      const reg = row?.dataset.evReg;
      const missing = !row || row.classList.contains('absent-row');
      const registered = !missing && reg !== undefined && t >= +reg;
      const want = missing ? CV('na') : registered ? CV('accent') : CV('line');
      if (line.getAttribute('stroke') !== want) line.setAttribute('stroke', want);
      // 증거 제출 경로임을 업무 데이터 경로와 구분해 보인다: 재생 중이고 이미 등록된 선만 흐른다.
      // 결손 선은 어떤 경우에도 움직이지 않는다.
      line.classList.toggle('flowing', registered && this.playing && !reducedMotion);
      if (registered && !this.evFired.has(k)) { this.evFired.add(k); if (this.playing && this.primed && !reducedMotion) this.pulse('T'); }
      if (!registered) this.evFired.delete(k);
    }
    // 등록 여부는 클래스만 바꾸고 색 전이는 CSS 가 맡는다 (프레임마다 인라인 스타일을 쓰면 전이가 끊긴다).
    this.root.querySelectorAll<HTMLElement>('.evrow[data-ev-reg]').forEach(row => {
      const reg = +row.dataset.evReg!, arrived = t >= reg;
      if (row.classList.contains('arrived') === arrived) return;
      row.classList.toggle('arrived', arrived);
      // 이미 끝난 사건을 불러올 때(primed 이전)는 안착 애니메이션을 내지 않는다 — 방금 등록된 것이 아니다.
      row.classList.toggle('settling', arrived && this.playing && this.primed && !reducedMotion);
      const state = row.querySelector<HTMLElement>('.evstate')!;
      state.textContent = arrived ? `등록 ≤ ${reg} ms` : '대기';
    });
    this.primed = true;
    const ph = this.root.querySelector<HTMLElement>('[data-playhead]'); if (ph) ph.style.left = c.span(t) + '%';
    const box = this.root.querySelector<HTMLElement>('[data-scrub]');
    if (box) { box.setAttribute('aria-valuemax', String(Math.round(c.tEnd))); box.setAttribute('aria-valuenow', String(Math.round(t))); box.setAttribute('aria-valuetext', `t = ${Math.round(t)} ms · ${packetLabel(t, c.legs)}`); }
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
export async function copyText(text: string): Promise<boolean> {
  if (!text) return false;
  try { await navigator.clipboard.writeText(text); return true; } catch { /* 권한 없는 환경은 아래로 */ }
  try {
    const ta = document.createElement('textarea');
    ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.append(ta); ta.select();
    const ok = document.execCommand('copy'); ta.remove(); return ok;
  } catch { return false; }
}
