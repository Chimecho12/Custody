// 홉 지도: Claude Design 'Hopmap Console v2' 원안을 그대로 옮긴 그래프 캔버스 (가상화 뷰만 제외).
//   줌·팬 캔버스(휠·드래그·핏뷰) · 미니맵 뷰포트 드래그 · 250px 커스텀 노드(등식 행 접기·펼치기, 핸들)
//   · 인터랙티브 엣지(호버 툴팁·클릭 선택·라벨 칩) · 자동 레이아웃 전환 애니메이션(Dagre LR ↔ ELK 직교, 520ms)
//   · 게이트 상태 머신 뷰. 원안의 상수·배치·로직을 그대로 쓰고, 원안이 합성했던 값만 실제 데이터로 채운다.
// 색은 판정에만 쓴다. 결손·미실행은 움직이지 않는다. 재생(패킷·꼬리·증거선)은 console.Playback 이 맡고,
// 이 모듈은 재생 프레임 이벤트를 받아 도달 링과 상태 머신만 갱신한다.
import { esc, CV, cls, st, computeLegs, reducedMotion, playControlsHtml, BASIS_LABEL, HopLabel, Leg, NodeKey, Pt, Playback } from './console';

export const EQ_TITLE: Record<string, string> = {E1: '자기 정합', E2: '요청 U→R', E3: '진술 R↔M', E4: '승인 변환 재계산', E5: 'nonce 결합', E6: '응답 M→R',
  E7: '응답 R→U', E8: '승인 경로', E9: '아티팩트', E10: '종단 응답 결합', E11: '시도 결합', E12: '유효기간'};
// U 로컬 검사를 홉 지도의 행 자리에 놓는 배치표. 등식과의 동일성이 아니다 — '어느 홉·당사자에 관한 검사인가' 만 정한다.
// 예: receipt_signature 는 R 행의 E4 자리에 놓이지만 E4(승인 변환 재계산)를 확인한 것이 아니라 영수증 서명을 확인한 것이다.
// 그래서 검사 모드에서는 등식 번호 대신 L- 코드를 보이고 근거 종류(basis)를 함께 적는다 (itx/enforce/user_gate.py 의 CHECK_BASIS).
export const CHECK_SLOT: Record<string, string> = {not_expired: 'E12', tool_policy: 'E1', nonce_match: 'E5', route_allowed: 'E8', model_hash_reference: 'E9',
  attempt_match: 'E11', request_binding: 'E2', R_authority: 'E3', receipt_signature: 'E4', M_authority: 'E6', receipt_present: 'E7', response_binding: 'E10'};
export const CHECK_CODE: Record<string, string> = {not_expired: 'L-EXP', tool_policy: 'L-TOOL', nonce_match: 'L-NONCE', route_allowed: 'L-ROUTE', model_hash_reference: 'L-HASH',
  attempt_match: 'L-ATT', request_binding: 'L-REQ', R_authority: 'L-RSIG', receipt_signature: 'L-MSIG', M_authority: 'L-MAUTH', receipt_present: 'L-RCPT', response_binding: 'L-RESP'};
// 옛 기록(basis 필드 이전)을 그릴 때의 대체값. 새 기록은 검사 자체가 basis 를 갖는다.
const CHECK_BASIS_FALLBACK: Record<string, string> = {route_allowed: 'signed_self_report', model_hash_reference: 'signed_self_report'};
const NODE_DEF: Record<NodeKey, {label: string; name: string; sub: string; rows: string[]}> = {
  U: {label: 'U', name: '사용자 · 집행 모듈', sub: '로컬 검증 · 격리', rows: ['E12', 'E2', 'E10', 'E1']},
  R: {label: 'R', name: '중개자 (클라우드 대행)', sub: '중계 진술 서명', rows: ['E3', 'E4', 'E7']},
  M: {label: 'M', name: '모델 운영자', sub: '추론 · 영수증 서명', rows: ['E6', 'E5', 'E11']},
  T: {label: 'T', name: 'T — 독립 제3자', sub: '대조 · 정책 · 추가 전용 로그', rows: ['E9', 'E8', 'E1']},
};
type Axis = 'h' | 'v';
type PosMap = Record<NodeKey, Pt>;
const LAYOUTS: Record<string, {label: string; axis: Axis; pos: PosMap}> = {
  dagre: {label: '계층 · Dagre LR', axis: 'h', pos: {U: [70, 250], R: [520, 250], M: [970, 250], T: [520, 600]}},
  elk: {label: '직교 · ELK', axis: 'v', pos: {U: [90, 70], R: [600, 330], M: [1060, 70], T: [600, 650]}},
};
const WORLD = {map: {w: 1340, h: 820}, sm: {w: 1280, h: 620}};
const NW = 250, HEAD = 58, ROWH = 24;
const APPLE = (f: number) => 1 - Math.pow(1 - f, 4);
const lerp = (a: number, b: number, f: number) => a + (b - a) * f;
const EV_NAME: Record<string, string> = {U: 'U 요청 진술', R: 'R 중계 진술', M: 'M 응답 영수증'};
const SM: Record<string, [string, string, string][]> = {
  base: [['sign', '계약 서명', 'U 서명 · 만료 고정'], ['send', '전송', 'U→R→M'], ['recv', '응답 수신', '본문 + 영수증'], ['verify', '로컬 검증', 'E2 · E10 · nonce']],
  observe: [['show', '표시만', '상태만 알린다'], ['accept', '수용', '검증 실패도 업무 반영']],
  protect: [['accept', '수용', '로컬 검증 통과'], ['hold', '격리', '업무 반영 전 차단']],
  strict: [['wait', 'T 판정 대기', '기한 내 등록 필요'], ['accept', '수용', '로컬 + T 판정'], ['deny', '거부', '기한 내 판정 없음']],
};
const eqGlyph = (r: string) => r === 'pass' ? '✓' : r === 'fail' ? '✗' : '–';
const colOf = (r: string) => CV(cls(r));

export interface EqInfo { result: string; reason?: string; compared?: string[]; trust_grade?: string; title?: string; basis?: string }
export interface FlowData {
  key: string;
  eq: Record<string, EqInfo>;            // 행 id → 결과 (검사 모드면 CHECK_SLOT 자리에 검사 결과를 놓는다)
  rowTitle?: Record<string, string>;     // 행 이름 덮어쓰기 (검사 모드: 검사 이름)
  rowId?: Record<string, string>;        // 행 id 표기 덮어쓰기 (검사 모드: L- 코드. 등식 번호를 보이지 않는다)
  regs: Record<string, number | null>;   // U/R/M 증거 등록 시각 (없으면 null = 결손)
  sent: number; received: number; latency: number;
  sm: {mode: string; gateAction: string; decidedAt: number; consumedAt: number | null; verdictAt: number | null} | null;
  info: {id: string; title: string; verdict: string; verdictTone: string; action: string; actionTone: string; note: string};
  foot: string;                           // 하단 패널: 스크러버 + 증거 행 (컨트롤은 dock 에 들어간다)
  controls?: string;                      // 재생 컨트롤 마크업 (없으면 빈 dock — 정적 컨트롤을 옮겨 붙인다)
}
// 검사 결과(검사 이름 키)를 홉 지도의 행 자리에 놓는다. 행 id 는 L- 코드, 근거는 검사가 가진 basis 다.
export function eqFromChecks(checks: Record<string, any>, names: Record<string, string>): {eq: Record<string, EqInfo>; rowTitle: Record<string, string>; rowId: Record<string, string>} {
  const eq: Record<string, EqInfo> = {}, rowTitle: Record<string, string> = {}, rowId: Record<string, string> = {};
  for (const [k, v] of Object.entries(checks || {})) {
    const id = CHECK_SLOT[k]; if (!id) continue;
    const basis = v.result === 'not_evaluable' ? 'not_evaluable' : (v.basis || CHECK_BASIS_FALLBACK[k] || 'measured_locally');
    eq[id] = {result: v.result, reason: v.reason, title: names[k], basis}; rowTitle[id] = names[k] || k; rowId[id] = CHECK_CODE[k] || k;
  }
  return {eq, rowTitle, rowId};
}
export function eqFromEquations(equations: Record<string, any>): Record<string, EqInfo> {
  const eq: Record<string, EqInfo> = {};
  for (const [k, e] of Object.entries(equations || {})) eq[k] = {result: e.result, reason: e.reason, compared: e.compared, trust_grade: e.trust_grade, title: e.title, basis: 'reconciled'};
  return eq;
}
export const labelsToEq = (labels: HopLabel[]): Record<string, EqInfo> => Object.fromEntries(labels.map(l => [CHECK_SLOT[l.id] || l.id, {result: l.result, title: l.tail}]));

// ---------- 기하 (원안 그대로) ----------
interface Geo { posA: PosMap; posB: PosMap | null; lt: number; axisA: Axis; axisB: Axis | null; open: Record<NodeKey, boolean> }
const freshGeo = (): Geo => ({posA: LAYOUTS.dagre.pos, posB: null, lt: 1, axisA: 'h', axisB: null, open: {U: true, R: true, M: true, T: true}});
function gPos(g: Geo): PosMap {
  if (!g.posB) return g.posA;
  const f = APPLE(g.lt), out = {} as PosMap;
  for (const k of Object.keys(g.posA) as NodeKey[]) out[k] = [lerp(g.posA[k][0], g.posB[k][0], f), lerp(g.posA[k][1], g.posB[k][1], f)];
  return out;
}
const gAxis = (g: Geo): Axis => g.posB ? (g.lt < .5 ? g.axisA : g.axisB!) : g.axisA;
const nodeH = (g: Geo, id: NodeKey) => g.open[id] ? HEAD + NODE_DEF[id].rows.length * ROWH + 11 : HEAD;
function anchor(g: Geo, id: NodeKey, side: 'r' | 'l' | 't' | 'b', frac: number): Pt {
  const p = gPos(g)[id], h = nodeH(g, id);
  if (side === 'r') return [p[0] + NW, p[1] + h * frac];
  if (side === 'l') return [p[0], p[1] + h * frac];
  if (side === 't') return [p[0] + NW * frac, p[1]];
  return [p[0] + NW * frac, p[1] + h];
}
function ends(g: Geo, a: NodeKey, b: NodeKey, frac: number): [Pt, Pt] {
  const ax = gAxis(g), pa = gPos(g)[a], pb = gPos(g)[b];
  if (ax === 'h') { const fwd = pb[0] >= pa[0]; return [anchor(g, a, fwd ? 'r' : 'l', frac), anchor(g, b, fwd ? 'l' : 'r', frac)]; }
  const down = pb[1] >= pa[1];
  return [anchor(g, a, down ? 'b' : 't', frac), anchor(g, b, down ? 't' : 'b', frac)];
}
function smoothstep(x1: number, y1: number, x2: number, y2: number, axis: Axis): string {
  const r = 14;
  if (axis === 'h') {
    const mx = (x1 + x2) / 2, sx = x2 > x1 ? 1 : -1, sy = y2 > y1 ? 1 : -1;
    if (Math.abs(y2 - y1) < 2) return `M ${x1} ${y1} L ${x2} ${y2}`;
    return `M ${x1} ${y1} L ${mx - r * sx} ${y1} Q ${mx} ${y1} ${mx} ${y1 + r * sy} L ${mx} ${y2 - r * sy} Q ${mx} ${y2} ${mx + r * sx} ${y2} L ${x2} ${y2}`;
  }
  const my = (y1 + y2) / 2, sy = y2 > y1 ? 1 : -1, sx = x2 > x1 ? 1 : -1;
  if (Math.abs(x2 - x1) < 2) return `M ${x1} ${y1} L ${x2} ${y2}`;
  return `M ${x1} ${y1} L ${x1} ${my - r * sy} Q ${x1} ${my} ${x1 + r * sx} ${my} L ${x2 - r * sx} ${my} Q ${x2} ${my} ${x2} ${my + r * sy} L ${x2} ${y2}`;
}
function stepPts(x1: number, y1: number, x2: number, y2: number, axis: Axis): Pt[] {
  if (axis === 'h') { const mx = (x1 + x2) / 2; return [[x1, y1], [mx, y1], [mx, y2], [x2, y2]]; }
  const my = (y1 + y2) / 2; return [[x1, y1], [x1, my], [x2, my], [x2, y2]];
}
// 원안 flowLegs 의 꼴. 시간 배분은 console.computeLegs 가 맡는다.
export function flowShape(g: Geo = freshGeo()): Pt[][] {
  const ax = gAxis(g);
  const pair = (a: NodeKey, b: NodeKey, f: number) => { const [p, q] = ends(g, a, b, f); return stepPts(p[0], p[1], q[0], q[1], ax); };
  const at = (id: NodeKey, side: 'r' | 'l' | 't' | 'b', f: number): Pt[] => [anchor(g, id, side, f)];
  const ax2 = ax === 'h' ? {in: 'l' as const} : {in: 't' as const};
  return [pair('U', 'R', .3), at('R', ax2.in, .3), pair('R', 'M', .3), at('M', ax2.in, .3), at('M', ax2.in, .72),
          pair('M', 'R', .72), at('R', ax === 'h' ? 'r' : 'b', .72), pair('R', 'U', .72)];
}
export const flowLegs = (sentAt: number, receivedAt: number, latency = 200, g?: Geo): Leg[] => computeLegs(sentAt, receivedAt, latency, flowShape(g));
export function ringFor(legs: Leg[], node: string, t: number): number {
  const lat = legs[3].t1 - legs[3].t0, win = Math.max(8, lat * 0.14);
  let best = 0;
  for (const L of legs) if (L.arrive === node && t >= L.t1) { const f = 1 - (t - L.t1) / win; if (f > best) best = f; }
  return +Math.max(0, Math.min(1, best)).toFixed(3);
}
function clipLine(g: Geo, a: NodeKey, b: NodeKey): [Pt, Pt] {
  const P = gPos(g), pa = P[a], pb = P[b], ha = nodeH(g, a), hb = nodeH(g, b);
  const c1: Pt = [pa[0] + NW / 2, pa[1] + ha / 2], c2: Pt = [pb[0] + NW / 2, pb[1] + hb / 2];
  const cut = (c: Pt, o: Pt, w: number, h: number): Pt => {
    const dx = o[0] - c[0], dy = o[1] - c[1];
    const sx = dx === 0 ? Infinity : (w / 2) / Math.abs(dx), sy = dy === 0 ? Infinity : (h / 2) / Math.abs(dy);
    const k = Math.min(sx, sy); return [c[0] + dx * k, c[1] + dy * k];
  };
  return [cut(c1, c2, NW, ha), cut(c2, c1, NW, hb)];
}
const smXY = (i: number): Pt => [i < 4 ? 70 + i * 300 : 70 + (i - 4) * 300, i < 4 ? 130 : 400];

// ---------- 캔버스 마크업 ----------
export function flowCanvasHtml(d: FlowData, view: 'map' | 'sm' = 'map', layout = 'dagre', showMinimap = true): string {
  const g = freshGeo(); if (layout !== 'dagre') { g.posA = LAYOUTS[layout].pos; g.axisA = LAYOUTS[layout].axis; }
  const W = view === 'sm' ? WORLD.sm : WORLD.map;
  const tabs = [['map', '경로 지도', 'U·R·M·T 홉 그래프'], ['sm', '게이트 상태 머신', 'AntV X6 스타일 상태 전이']]
    .map(([k, l, ti]) => `<button type="button" class="itx-btn tab${view === k ? ' on' : ''}" data-fc-view="${k}" title="${ti}">${l}</button>`).join('');
  const lays = Object.keys(LAYOUTS).map(k => `<button type="button" class="itx-btn tab lay${layout === k ? ' on' : ''}${view === 'map' ? '' : ' off'}" data-fc-layout="${k}" title="자동 레이아웃 — 전환은 애니메이션으로 이어진다">${LAYOUTS[k].label}</button>`).join('');
  const i = d.info;
  return `<div class="fcinfo"><span class="id">${esc(i.id)}</span><span class="ti">${esc(i.title)}</span><span class="sp"></span>
    <span class="kv">판정 <b class="${esc(i.verdictTone)}">${esc(i.verdict)}</b></span><span class="kv">집행 <b class="${esc(i.actionTone)}">${esc(i.action)}</b></span><span class="note">${esc(i.note)}</span></div>
  <div class="flowc" data-flow="${esc(d.key)}" tabindex="0" role="img" aria-label="홉 정합 지도 — 그래프 캔버스">
    <div class="flowc-bar">${tabs}<span class="sp"></span>${lays}
      <span style="margin-left:auto;display:flex;align-items:center;gap:6px">
        <button type="button" class="itx-btn sq" data-fc-zoom="out" title="축소 (−)">−</button><span class="zoom" data-fc-zoomtext>66%</span><button type="button" class="itx-btn sq" data-fc-zoom="in" title="확대 (+)">+</button>
        <button type="button" class="itx-btn" data-fc-zoom="fit" title="전체 보기 (F)">핏뷰</button>
        <button type="button" class="itx-btn${showMinimap ? ' on' : ''}" data-fc-mini title="미니맵 표시">미니맵</button></span>
    </div>
    <div class="flowc-canvas" data-fc-canvas>
      <div class="flowc-world" data-fc-world>${view === 'sm' ? smWorldHtml(d) : mapWorldHtml(d, g, null)}</div>
      <div class="flowc-tip" data-fc-tip hidden></div>
      <div class="flowc-legend"><span class="pass">✓ pass</span><span class="fail">✗ fail</span><span class="na">– not_evaluable</span>${d.rowId ? '<span>L- = U 로컬 검사 (T 등식 아님) · 근거 종류는 행 선택 시 표시</span>' : '<span>E- = T 가 서명 진술을 대조한 등식</span>'}<span>휠 줌 · 드래그 팬 · 엣지 클릭 선택</span></div>
      <div class="flowc-mini" data-fc-minimap${showMinimap ? '' : ' hidden'}><svg data-fc-minisvg viewBox="0 0 ${W.w} ${W.h}" preserveAspectRatio="xMidYMid meet"><g data-fc-minishapes>${miniShapesHtml(d, g, view)}</g><rect class="mmview" data-fc-miniview x="0" y="0" width="${W.w}" height="${W.h}"/></svg><span class="mmtag">MINIMAP</span></div>
      <div class="flowc-sel" data-fc-sel hidden><div class="h"><span class="id" data-fc-selid></span><span class="ti" data-fc-seltitle></span><button type="button" class="x" data-fc-clear>닫기</button></div><div class="reason" data-fc-selreason></div><div class="cmp" data-fc-selcmp></div></div>
    </div>
    <div class="flowc-foot"><div class="playdock" data-fc-dock>${d.controls ?? ''}</div>${d.foot}</div>
  </div>`;
}
function mapWorldHtml(d: FlowData, g: Geo, sel: string | null, t = Infinity, playing = false): string {
  const key = d.key, ax = gAxis(g), P = gPos(g);
  const res = (id: string) => (d.eq[id] || {}).result || 'not_evaluable';
  const title = (id: string) => d.rowTitle?.[id] || EQ_TITLE[id] || '';
  const idl = (id: string) => d.rowId?.[id] || id;  // 검사 모드에서는 등식 번호를 보이지 않는다
  const mkFlow = (id: string, a: NodeKey, b: NodeKey, frac: number) => { const [p, q] = ends(g, a, b, frac), r = res(id);
    return {id, d: smoothstep(p[0], p[1], q[0], q[1], ax), color: colOf(r), dash: 'none', marker: `url(#${key}-ar)`, res: r, mid: [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2] as Pt, ev: ''}; };
  const edges = [mkFlow('E2', 'U', 'R', .3), mkFlow('E3', 'R', 'M', .3), mkFlow('E6', 'M', 'R', .72), mkFlow('E7', 'R', 'U', .72)];
  { const [p, q] = clipLine(g, 'U', 'M'), r = res('E10'), my = Math.max(p[1], q[1]) + 190;
    edges.push({id: 'E10', d: `M ${p[0]} ${p[1]} C ${p[0]} ${my} ${q[0]} ${my} ${q[0]} ${q[1]}`, color: colOf(r), dash: '7 4', marker: 'none', res: r, mid: [(p[0] + q[0]) / 2, my * 0.78], ev: ''}); }
  const evPaths = (['U', 'R', 'M'] as const).map(k => {
    const reg = d.regs[k], registered = reg != null && t >= reg;
    const [p, q] = clipLine(g, k, 'T');
    return `<path id="${key}-ev${k}" class="evline${registered && playing ? ' flowing' : ''}" d="M ${p[0]} ${p[1]} L ${q[0]} ${q[1]}" fill="none" stroke="${reg == null ? CV('na') : registered ? CV('accent') : CV('line')}" stroke-width="1.6" stroke-dasharray="4 6" stroke-linecap="round"/>
            <path class="edge-hit" d="M ${p[0]} ${p[1]} L ${q[0]} ${q[1]}" data-fc-ev="${k}"/>`; }).join('');
  const paths = edges.map(e => `<path class="edge${sel === e.id ? ' on' : ''}" data-edge-path="${e.id}" d="${e.d}" fill="none" stroke="${e.color}" stroke-width="2.5" stroke-dasharray="${e.dash}" stroke-linecap="round" marker-end="${e.marker}"/>`).join('')
    + edges.map(e => `<path class="edge-hit" d="${e.d}" data-eq="${e.id}" data-fc-pick="${e.id}"/>`).join('');
  const labels = edges.map(e => `<div class="fclabel${sel === e.id ? ' sel' : ''}" data-eq="${e.id}" data-fc-pick="${e.id}" style="left:${e.mid[0].toFixed(1)}px;top:${e.mid[1].toFixed(1)}px;color:${e.color}">${eqGlyph(e.res)} ${esc(idl(e.id))} ${esc(title(e.id))}</div>`).join('');
  const nodes = (Object.keys(NODE_DEF) as NodeKey[]).map(id => {
    const n = NODE_DEF[id], open = g.open[id], isT = id === 'T';
    const rows = n.rows.map(eid => { const r = res(eid);
      return `<div class="fcrow${sel === eid ? ' sel' : ''}" data-eq="${eid}" data-fc-pick="${eid}"><span class="g" style="color:${colOf(r)}">${eqGlyph(r)}</span><span class="i" style="color:${colOf(r)}">${esc(idl(eid))}</span><span class="n">${esc(title(eid))}</span><span class="d" style="background:${colOf(r)}"></span></div>`; }).join('');
    const handles = (ax === 'h' ? ['left:-5px;top:30%', 'left:-5px;top:72%', 'right:-5px;top:30%', 'right:-5px;top:72%'] : ['top:-5px;left:30%', 'top:-5px;left:72%', 'bottom:-5px;left:30%', 'bottom:-5px;left:72%'])
      .map(s => `<span class="handle" style="${s}"></span>`).join('');
    return `<div class="fcnode${isT ? ' t' : ''}${open ? '' : ' closed'}" data-node="${id}" style="left:${P[id][0].toFixed(1)}px;top:${P[id][1].toFixed(1)}px">
      <div class="ring" data-ring="${id}" style="opacity:0"></div>
      <div class="fccard"><div class="fchead"><span class="fcbadge">${n.label}</span><span style="min-width:0;flex:1"><span class="fcname">${esc(n.name)}</span><span class="fcsub">${esc(n.sub)}</span></span>
        <button type="button" class="fccaret" data-fc-toggle="${id}" title="포트 접기 · 펼치기">${open ? '▾' : '▸'}</button></div>
        <div class="fcrows">${rows}</div></div>${handles}</div>`;
  }).join('');
  const start = flowShape(g)[0][0];
  return `<svg width="${WORLD.map.w}" height="${WORLD.map.h}" viewBox="0 0 ${WORLD.map.w} ${WORLD.map.h}" aria-hidden="true">
      <defs><marker id="${key}-ar" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="${CV('na')}"/></marker>
        <linearGradient id="${key}-trail-gradient" gradientUnits="userSpaceOnUse" x1="${start[0] - 20}" y1="${start[1]}" x2="${start[0]}" y2="${start[1]}" style="color:${CV('accent')}">
          <stop offset="0" stop-color="currentColor" stop-opacity="0"/><stop offset="1" stop-color="currentColor" stop-opacity=".65"/></linearGradient></defs>
      ${evPaths}${paths}
      <polyline id="${key}-trail" class="packettrail" points="" fill="none" stroke="url(#${key}-trail-gradient)" stroke-width="6" stroke-linecap="round" stroke-linejoin="round" opacity="0"/>
      <circle id="${key}-packet" class="packet" cx="${start[0]}" cy="${start[1]}" r="6" fill="${CV('accent')}"/>
    </svg><div>${labels}</div><div>${nodes}</div>`;
}
const smChain = (mode: string) => SM.base.concat(SM[mode] || SM.protect);
function smWorldHtml(d: FlowData): string {
  const chain = smChain(d.sm?.mode || 'protect');
  const cards = chain.map(([k, name, sub], i) => { const [x, y] = smXY(i);
    return `<div class="fcsm${k === 'hold' || k === 'deny' ? ' term' : ''}" data-sm="${k}" style="left:${x}px;top:${y}px"><span class="n">${esc(name)}</span><span class="s">${esc(sub)}</span></div>`; }).join('');
  let paths = '';
  for (let i = 0; i < chain.length - 1; i++) {
    const [ax1, ay1] = smXY(i), [bx1, by1] = smXY(i + 1), sameRow = (i < 4) === (i + 1 < 4);
    const p = sameRow ? [ax1 + 244, ay1 + 34] : [ax1 + 122, ay1 + 70], q = sameRow ? [bx1, by1 + 34] : [bx1 + 122, by1];
    paths += `<path class="smedge" data-sm-edge="${i}" d="${smoothstep(p[0], p[1], q[0], q[1], sameRow ? 'h' : 'v')}" marker-end="url(#${d.key}-ar)"/>`;
  }
  return `<svg width="${WORLD.sm.w}" height="${WORLD.sm.h}" viewBox="0 0 ${WORLD.sm.w} ${WORLD.sm.h}" aria-hidden="true"><defs><marker id="${d.key}-ar" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="${CV('na')}"/></marker></defs>${paths}</svg>${cards}`;
}
function miniShapesHtml(d: FlowData, g: Geo, view: 'map' | 'sm'): string {
  if (view === 'sm') return smChain(d.sm?.mode || 'protect').map((_, i) => { const [x, y] = smXY(i); return `<rect class="mmnode" x="${x}" y="${y}" width="244" height="70" rx="6"/>`; }).join('');
  const P = gPos(g);
  return (Object.keys(NODE_DEF) as NodeKey[]).map(id => `<rect class="mmnode${id === 'T' ? ' t' : ''}" x="${P[id][0].toFixed(1)}" y="${P[id][1].toFixed(1)}" width="${NW}" height="${nodeH(g, id)}" rx="6"/>`).join('');
}
// 원안 activeKey. 결정 자리에는 이 요청의 실제 게이트 결정을 쓴다.
function smActiveKey(d: FlowData, legs: Leg[], t: number): string {
  const s = d.sm!, last = legs[legs.length - 1], consumed = s.consumedAt, verdict = s.verdictAt;
  const blocked = ['quarantine', 'reject', 'reject_timeout', 'no_response'].includes(s.gateAction);
  let key = 'sign';
  if (t > 0 && t < last.t1) key = 'send';
  else if (t >= last.t1 && t < last.t1 + 8) key = 'recv';
  else if (t >= last.t1 + 8 && (consumed == null || t < consumed) && t < s.decidedAt) key = 'verify';
  else if (t >= Math.min(consumed != null ? consumed : Infinity, s.decidedAt)) {
    if (s.mode === 'observe') key = 'accept';
    else if (s.mode === 'protect') key = blocked ? 'hold' : 'accept';
    else key = verdict == null ? (t > last.t1 + 700 ? 'deny' : 'wait') : (t >= verdict ? (blocked ? 'deny' : 'accept') : 'wait');
  }
  return key;
}

// ---------- 캔버스 컨트롤러 (원안 핸들러) ----------
const mounted = new WeakMap<HTMLElement, FlowCanvas>();
export function mountFlow(root: HTMLElement, data: FlowData, playback: Playback | null): FlowCanvas | null {
  const el = root.querySelector<HTMLElement>(`.flowc[data-flow="${CSS.escape(data.key)}"]`);
  if (!el) return null;
  const c = new FlowCanvas(el, data, playback); mounted.set(el, c); return c;
}
export class FlowCanvas {
  private g = freshGeo(); private view: 'map' | 'sm' = 'map'; private layout = 'dagre'; private sel: string | null = null; private showMinimap = true;
  private vp = {x: 40, y: 20, k: .66}; private lraf = 0; private t: number; private playing = false;
  private pan: {x: number; y: number; vx: number; vy: number; id: number} | null = null; private mini: {r: DOMRect; id: number} | null = null;
  private canvas: HTMLElement; private world: HTMLElement;
  constructor(private el: HTMLElement, private d: FlowData, private pb: Playback | null) {
    this.canvas = el.querySelector('[data-fc-canvas]')!; this.world = el.querySelector('[data-fc-world]')!;
    this.t = Infinity;
    this.bind();
    if (typeof ResizeObserver !== 'undefined') new ResizeObserver(() => this.fit()).observe(this.canvas);
    this.apply(); requestAnimationFrame(() => this.fit());
  }
  legs(): Leg[] { return flowLegs(this.d.sent, this.d.received, this.d.latency, this.g); }
  private $(sel: string) { return this.el.querySelector<HTMLElement>(sel); }
  private worldSize() { return this.view === 'sm' ? WORLD.sm : WORLD.map; }
  private apply() {
    const vp = this.vp;
    this.world.style.transform = `translate(${vp.x.toFixed(1)}px,${vp.y.toFixed(1)}px) scale(${vp.k.toFixed(3)})`;
    this.canvas.style.backgroundSize = `${(22 * vp.k).toFixed(1)}px ${(22 * vp.k).toFixed(1)}px`;
    this.canvas.style.backgroundPosition = `${vp.x.toFixed(1)}px ${vp.y.toFixed(1)}px`;
    const z = this.$('[data-fc-zoomtext]'); if (z) z.textContent = Math.round(vp.k * 100) + '%';
    const r = this.canvas.getBoundingClientRect(), mv = this.$('[data-fc-miniview]');
    if (mv) { mv.setAttribute('x', (-vp.x / vp.k).toFixed(1)); mv.setAttribute('y', (-vp.y / vp.k).toFixed(1)); mv.setAttribute('width', (r.width / vp.k).toFixed(1)); mv.setAttribute('height', (r.height / vp.k).toFixed(1)); }
  }
  fit() {
    const r = this.canvas.getBoundingClientRect(), w = this.worldSize(); if (r.width <= 0) return;
    const k = Math.max(.2, Math.min(1.6, Math.min(r.width / w.w, r.height / w.h) * 0.94));
    this.vp = {k, x: (r.width - w.w * k) / 2, y: (r.height - w.h * k) / 2}; this.apply();
  }
  private zoomBy(f: number) {
    const r = this.canvas.getBoundingClientRect(), vp = this.vp, k = Math.max(.25, Math.min(2.4, vp.k * f)), cw = r.width, ch = r.height;
    this.vp = {k, x: cw / 2 - (cw / 2 - vp.x) * (k / vp.k), y: ch / 2 - (ch / 2 - vp.y) * (k / vp.k)}; this.apply();
  }
  private miniTo(cx: number, cy: number, r: DOMRect) {
    const w = this.worldSize(), c = this.canvas.getBoundingClientRect();
    const k = Math.min(r.width / w.w, r.height / w.h), offx = (r.width - w.w * k) / 2, offy = (r.height - w.h * k) / 2;
    const wx = (cx - r.left - offx) / k, wy = (cy - r.top - offy) / k;
    this.vp = {k: this.vp.k, x: c.width / 2 - wx * this.vp.k, y: c.height / 2 - wy * this.vp.k}; this.apply();
  }
  private renderWorld() {
    this.world.innerHTML = this.view === 'sm' ? smWorldHtml(this.d) : mapWorldHtml(this.d, this.g, this.sel, this.t, this.playing);
    const ms = this.$('[data-fc-minishapes]'); if (ms) ms.innerHTML = miniShapesHtml(this.d, this.g, this.view);
    const W = this.worldSize(), svg = this.$('[data-fc-minisvg]'), mv = this.$('[data-fc-miniview]');
    if (svg) svg.setAttribute('viewBox', `0 0 ${W.w} ${W.h}`); if (mv) { mv.setAttribute('width', String(W.w)); mv.setAttribute('height', String(W.h)); }
    this.apply();
    this.pb?.setLegs(this.legs()); // 재생 엔진이 새 기하로 패킷·꼬리를 다시 그린다 (시점 유지)
  }
  private tip(text: string | null) { const el = this.$('[data-fc-tip]'); if (!el) return; if (!text) { el.hidden = true; return; } el.textContent = text; el.hidden = false; }
  private select(id: string | null) {
    this.sel = id;
    this.el.querySelectorAll('.fclabel.sel, .fcrow.sel, .edge.on').forEach(n => n.classList.remove('sel', 'on'));
    const panel = this.$('[data-fc-sel]'); if (!panel) return;
    if (!id) { panel.hidden = true; return; }
    this.el.querySelectorAll(`[data-fc-pick="${CSS.escape(id)}"]`).forEach(n => n.classList.add('sel'));
    this.el.querySelectorAll(`[data-edge-path="${CSS.escape(id)}"]`).forEach(n => n.classList.add('on'));
    const e = this.d.eq[id] || {result: 'not_evaluable'}, r = e.result || 'not_evaluable';
    const sid = this.$('[data-fc-selid]')!, stt = this.$('[data-fc-seltitle]')!, rs = this.$('[data-fc-selreason]')!, cmp = this.$('[data-fc-selcmp]')!;
    sid.textContent = this.d.rowId?.[id] || id; sid.style.color = colOf(r); stt.textContent = this.d.rowTitle?.[id] || EQ_TITLE[id] || e.title || '';
    rs.textContent = e.reason || `결과 ${r} — 사유는 등식 표에서 확인한다.`;
    // 근거 종류를 항상 적는다. 로컬 검사는 T 등식과 다른 주장이고, 서명된 자기보고는 U 의 계산이 아니다.
    cmp.textContent = this.d.rowId
      ? `근거 ${BASIS_LABEL[e.basis || 'measured_locally'] || e.basis} · U 로컬 검사 (T 등식 ${id} 자리에 놓았을 뿐 그 등식을 확인한 것이 아님) · 결과 ${r}`
      : `비교 대상 · ${(e.compared || []).join(' · ') || id} · trust_grade=${e.trust_grade || '—'} · 근거 ${BASIS_LABEL.reconciled} · 판정 ${r}`;
    panel.hidden = false;
  }
  private setLayout(k: string) {
    if (k === this.layout || this.view !== 'map') return;
    const g = this.g; g.posA = gPos(g); g.axisA = gAxis(g); g.posB = LAYOUTS[k].pos; g.axisB = LAYOUTS[k].axis; g.lt = 0; this.layout = k;
    this.el.querySelectorAll<HTMLElement>('[data-fc-layout]').forEach(b => b.classList.toggle('on', b.dataset.fcLayout === k));
    const t0 = performance.now();
    const run = (ts: number) => {
      g.lt = Math.min(1, (ts - t0) / 520);
      if (g.lt >= 1) { g.posA = g.posB!; g.axisA = g.axisB!; g.posB = null; g.axisB = null; }
      this.renderWorld();
      if (g.posB) this.lraf = requestAnimationFrame(run);
    };
    cancelAnimationFrame(this.lraf); this.lraf = requestAnimationFrame(reducedMotion ? ts => { g.lt = 1; run(ts); } : run);
  }
  private setView(v: 'map' | 'sm') {
    this.view = v; this.sel = null;
    this.el.querySelectorAll<HTMLElement>('[data-fc-view]').forEach(b => b.classList.toggle('on', b.dataset.fcView === v));
    this.el.querySelectorAll<HTMLElement>('[data-fc-layout]').forEach(b => b.classList.toggle('off', v !== 'map'));
    this.select(null); this.tip(null); this.renderWorld(); requestAnimationFrame(() => this.fit());
  }
  // 재생 프레임: 도달 링(원안 ringFor 감쇠) · 상태 머신 활성 상태 · 증거선 흐름 상태를 갱신한다.
  frame(t: number, legs: Leg[], playing: boolean) {
    this.t = t; this.playing = playing;
    if (this.view === 'map') {
      const lat = legs[3].t1 - legs[3].t0;
      for (const k of ['U', 'R', 'M']) { const el = this.$(`[data-ring="${k}"]`); if (el) el.style.opacity = String(ringFor(legs, k, t)); }
      const tr = this.$('[data-ring="T"]');
      if (tr) tr.style.opacity = Math.max(0, ...['U', 'R', 'M'].map(k => { const reg = this.d.regs[k]; if (reg == null || t < reg) return 0; return Math.max(0, 1 - (t - reg) / Math.max(8, lat * 0.14)); })).toFixed(3);
    } else if (this.d.sm) {
      const chain = smChain(this.d.sm.mode), key = smActiveKey(this.d, legs, t), idx = chain.findIndex(c => c[0] === key);
      this.el.querySelectorAll<HTMLElement>('.fcsm[data-sm]').forEach(el => el.classList.toggle('on', el.dataset.sm === key));
      this.el.querySelectorAll<HTMLElement>('[data-sm-edge]').forEach(el => el.classList.toggle('done', idx > +el.dataset.smEdge!));
    }
  }
  private bind() {
    const el = this.el;
    el.addEventListener('click', e => {
      const t = e.target as HTMLElement;
      const z = t.closest<HTMLElement>('[data-fc-zoom]');
      if (z) { if (z.dataset.fcZoom === 'fit') this.fit(); else this.zoomBy(z.dataset.fcZoom === 'in' ? 1.18 : 1 / 1.18); return; }
      const mb = t.closest<HTMLElement>('[data-fc-mini]');
      if (mb) { this.showMinimap = !this.showMinimap; const m = this.$('[data-fc-minimap]'); if (m) m.hidden = !this.showMinimap; mb.classList.toggle('on', this.showMinimap); return; }
      const tg = t.closest<HTMLElement>('[data-fc-toggle]');
      if (tg) { const id = tg.dataset.fcToggle as NodeKey; this.g.open[id] = !this.g.open[id]; this.renderWorld(); return; }
      const vb = t.closest<HTMLElement>('[data-fc-view]'); if (vb) { this.setView(vb.dataset.fcView as 'map' | 'sm'); return; }
      const lb = t.closest<HTMLElement>('[data-fc-layout]'); if (lb) { this.setLayout(lb.dataset.fcLayout!); return; }
      if (t.closest('[data-fc-clear]')) { this.select(null); return; }
      const pk = t.closest<HTMLElement>('[data-fc-pick]');
      if (pk && !t.closest('[data-copy]')) this.select(this.sel === pk.dataset.fcPick ? null : pk.dataset.fcPick!);
    });
    el.addEventListener('mouseover', e => {
      const t = e.target as HTMLElement; if (!t.closest('[data-fc-canvas]')) return;
      const pk = t.closest<HTMLElement>('[data-fc-pick]');
      if (pk) { const id = pk.dataset.fcPick!, e = this.d.eq[id] || {} as EqInfo; this.tip(`${this.d.rowId?.[id] || id} ${this.d.rowTitle?.[id] || EQ_TITLE[id] || ''} — ${e.result || 'not_evaluable'}${e.basis ? ` · ${BASIS_LABEL[e.basis] || e.basis}` : ''}`); return; }
      const ev = t.closest<HTMLElement>('[data-fc-ev]');
      if (ev) { const k = ev.dataset.fcEv!, reg = this.d.regs[k]; this.tip(`${EV_NAME[k]} 제출 — ${reg == null ? '결손 (등록 없음)' : this.t >= reg ? '등록 ≤ ' + reg + ' ms' : '대기'}`); return; }
      this.tip(null);
    });
    el.addEventListener('pointerdown', e => {
      const t = e.target as HTMLElement; if (e.button !== 0) return;
      const mini = t.closest<HTMLElement>('[data-fc-minimap]');
      if (mini) { e.preventDefault(); e.stopPropagation(); const r = mini.getBoundingClientRect(); this.mini = {r, id: e.pointerId}; mini.setPointerCapture(e.pointerId); this.miniTo(e.clientX, e.clientY, r); return; }
      if (!t.closest('[data-fc-canvas]') || t.closest('button, .fcnode, .fclabel, .fcsm, [data-copy], .flowc-sel')) return;
      e.preventDefault(); this.pan = {x: e.clientX, y: e.clientY, vx: this.vp.x, vy: this.vp.y, id: e.pointerId}; this.canvas.setPointerCapture(e.pointerId); this.canvas.classList.add('panning');
    });
    el.addEventListener('pointermove', e => {
      if (this.mini && this.mini.id === e.pointerId) { this.miniTo(e.clientX, e.clientY, this.mini.r); return; }
      if (this.pan && this.pan.id === e.pointerId) { this.vp = {k: this.vp.k, x: this.pan.vx + (e.clientX - this.pan.x), y: this.pan.vy + (e.clientY - this.pan.y)}; this.apply(); }
    });
    const end = (e: PointerEvent) => { if (this.mini?.id === e.pointerId) this.mini = null; if (this.pan?.id === e.pointerId) { this.pan = null; this.canvas.classList.remove('panning'); } };
    el.addEventListener('pointerup', end); el.addEventListener('pointercancel', end);
    el.addEventListener('wheel', e => {
      if (!(e.target as HTMLElement).closest('[data-fc-canvas]')) return;
      e.preventDefault();
      const r = this.canvas.getBoundingClientRect(), vp = this.vp, k = Math.max(.25, Math.min(2.4, vp.k * (e.deltaY < 0 ? 1.09 : 1 / 1.09)));
      const px = e.clientX - r.left, py = e.clientY - r.top;
      this.vp = {k, x: px - (px - vp.x) * (k / vp.k), y: py - (py - vp.y) * (k / vp.k)}; this.apply();
    }, {passive: false});
    el.addEventListener('keydown', e => { if ((e.key === 'f' || e.key === 'F') && !e.ctrlKey && !e.metaKey) { e.preventDefault(); this.fit(); } });
    // console.Playback 이 프레임마다 보내는 이벤트 (재생 엔진은 이 모듈을 모른다).
    el.addEventListener('playbackframe', e => { const d = (e as CustomEvent<{t: number; legs: Leg[]; playing: boolean}>).detail; this.frame(d.t, d.legs, d.playing); });
  }
}
// 하단 패널 구성 도우미: 원안대로 재생 컨트롤 · 스크러버 · 증거 3행.
export function footHtml(timebox: string, evidenceRows: string): string { return `${timebox}<div class="fcev">${evidenceRows}</div>`; }
export const defaultControls = () => playControlsHtml();
export const toneOf = (verdictStatus: string | undefined) => verdictStatus ? st(verdictStatus) : 'na';
export const actionTone = (action: string | undefined) => action === 'accept' ? 'pass' : action === 'accept_unverified' ? 'warn' : action ? 'fail' : 'na';
