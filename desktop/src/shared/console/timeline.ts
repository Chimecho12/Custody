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
// 이동 구간은 정지에서 출발해 정지로 끝나므로 가감속을 준다. 노드 안 구간은 앞부분에서 자리를 잡고 머문다.
const easeInOut = (f: number) => f < .5 ? 2 * f * f : 1 - Math.pow(-2 * f + 2, 2) / 2;
const settle = (f: number) => 1 - Math.pow(1 - Math.min(1, f / 0.28), 3);

export function computeLegs(sentAt: number, receivedAt: number, latency = 200, shape: Pt[][] = DEFAULT_SHAPE): Leg[] {
  const raw: Leg[] = []; let t = 0;
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
export function packetLabel(t: number, legs: Leg[]): string {
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
