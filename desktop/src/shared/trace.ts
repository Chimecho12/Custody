import type { Data } from './types';
// 실행 추적 3단 (Claude Design 'Workflow Canvas' 참고): 판정 배너 · 1단 라이프사이클 파이프라인 · 3단 스플릿 인스펙터.
// 2단(홉 지도·패킷)은 flow.ts 의 그래프 캔버스가 맡고, 세 단은 재생 엔진의 한 시계(t)를 공유한다 —
// 타임라인을 끌면 배너 톤·단계 진행 바·인스펙터가 같은 시점으로 되돌아간다.
// 값은 전부 실제 실행 기록(record.checks · gate · t_verdict · timeline)에서 온다. 색은 판정에만 쓴다.
import { esc, short, cls, st, Leg, Playback } from './console';

export interface TraceData {
  record: Data; status: Data | null; legs: Leg[];
  sent: number; received: number; decided: number; released: number | null; verdictAt: number | null; tEnd: number;
}
type Res = 'pass' | 'fail' | 'warn' | 'na' | 'not_evaluable';
const glyphOf = (r: string) => r === 'pass' ? '✓' : r === 'fail' ? '✗' : r === 'warn' ? '!' : '–';
const colOf = (r: string) => r === 'warn' ? 'var(--warn)' : `var(--${cls(r)})`;
const ms = (v: number | null | undefined) => v == null ? '—' : `${Math.round(v)} ms`;
const actionRes = (a: string | undefined): Res => a === 'accept' ? 'pass' : a === 'accept_unverified' ? 'warn' : a ? 'fail' : 'not_evaluable';

interface Phase { key: string; role: string; title: string; sub: string; t0: number; t1: number }
function phases(d: TraceData): Phase[] {
  const L = d.legs, ev = (d.record.timeline || []).find((e: Data) => String(e.kind).includes('계약 서명'));
  return [
    {key: 'sign', role: 'U', title: '요청 계약 서명', sub: '허용 모델 · 변환 · 만료 고정', t0: ev ? ev.t_ms : 0, t1: d.sent},
    {key: 'relay', role: 'R', title: '중개자 전달', sub: '중계 진술 서명 · 전달 해시', t0: L[0].t0, t1: L[2].t1},
    {key: 'infer', role: 'M', title: '모델 추론 · 영수증', sub: '응답 커밋 · 시도 ID 서명', t0: L[3].t0, t1: L[4].t1},
    {key: 'gate', role: 'U', title: 'U Gate 집행', sub: '로컬 검증 후 공개 또는 격리', t0: L[5].t0, t1: d.decided},
    {key: 'ledger', role: 'T', title: '제3자 원장 등록', sub: 'Merkle 포함 증명 · 사후 판정', t0: d.decided, t1: d.verdictAt ?? d.tEnd},
  ];
}
function stateOf(d: TraceData, p: Phase, t: number): {res: Res; label: string} {
  const checks: Data = d.record.checks || {}, g = d.record.gate, v = d.record.t_verdict?.payload;
  const r = (k: string) => (checks[k] || {}).result;
  if (t < p.t0) return {res: 'not_evaluable', label: '대기'};
  if (t < p.t1) return {res: 'na', label: '진행 중'};
  if (p.key === 'gate') return g ? {res: actionRes(g.action), label: g.action} : {res: 'not_evaluable', label: d.record.state || '결정 없음'};
  if (p.key === 'ledger') return v ? {res: st(v.verification_status) as Res, label: `등록 · ${v.verification_status}`} : {res: 'not_evaluable', label: d.record.t_error ? '판정 미확인' : '등록 대기 · 큐 보관'};
  if (p.key === 'relay') return r('R_authority') === 'pass' ? {res: 'pass', label: '자기 정합'} : r('R_authority') === 'fail' ? {res: 'fail', label: '진술 실패'} : {res: 'not_evaluable', label: '미확인'};
  if (p.key === 'infer') return r('M_authority') === 'pass' && r('receipt_signature') !== 'fail' ? {res: 'pass', label: '서명 확인'} : r('M_authority') === 'fail' || r('receipt_signature') === 'fail' ? {res: 'fail', label: '영수증 실패'} : {res: 'not_evaluable', label: '미확인'};
  return {res: 'pass', label: '서명 확인'};
}

// ---------- 판정 배너 ----------
function bannerHtml(d: TraceData, t: number): string {
  const g = d.record.gate, checks: Data = d.record.checks || {}, on = t >= d.decided && !!g;
  const action: string = g?.action || '';
  const tone: Res = !on ? 'na' : actionRes(action);
  const chk = (k: string, label: string): [string, string] => [label, (checks[k] || {}).result || 'not_evaluable'];
  const texts: Record<string, [string, string]> = {
    pass: ['암호학적으로 검증된 원본 응답', 'M 이 서명한 응답 해시와 U 가 받은 응답 해시가 같습니다. 승인된 경로·모델·시도 결합까지 로컬에서 확인했습니다.'],
    warn: ['검증과 무관하게 observe 모드로 그대로 공개됨', '이 모드는 상태만 알리고 차단하지 않습니다. 검증에 실패한 응답이라면 업무에 노출되며, 노출 구간은 타임라인의 해칭 구간입니다.'],
    fail: action === 'reject_timeout'
      ? ['기한 내 T 판정 없음 — 수용 거부', 'strict 모드는 T 의 등록 판정까지 기다립니다. 기한 안에 인증된 판정이 오지 않아 응답을 업무에 쓰지 않습니다. 증거는 큐에 남아 재제출됩니다.']
      : action === 'no_response' ? ['응답 없음 — 판정 대상 없음', '중개 경로에서 응답이 돌아오지 않았습니다. 공개할 본문이 없으므로 게이트는 아무것도 수용하지 않습니다.']
      : ['화면 공개 전 격리 (Quarantined Before Use)', '로컬 검사에 실패한 응답입니다. 본문은 애플리케이션으로 넘기지 않고 격리했습니다. 실패한 검사와 사유는 아래 인스펙터에 있습니다.'],
    na: ['검증 진행 중', '응답과 영수증이 아직 U Gate 에 도착하지 않았습니다. 이 단계에서는 어떤 판정도 확정하지 않습니다.'],
    not_evaluable: ['결정 없음', '이 요청은 게이트 결정 전에 끝났습니다.'],
  };
  const [title, body] = texts[tone] || texts.na;
  const failed = Object.entries(checks).filter(([, v]: [string, any]) => v.result === 'fail').map(([k]) => k);
  const rules: [string, string][] = tone === 'na' || tone === 'not_evaluable' ? []
    : tone === 'pass' ? [chk('response_binding', 'E10 종단 응답 결합'), chk('request_binding', 'E2 승인 요청 결합'), chk('nonce_match', 'nonce 결합'), chk('attempt_match', '시도 결합')]
    : tone === 'warn' ? [chk('response_binding', 'E10 종단 응답 결합'), ['집행 정책 observe — 차단 없음', 'warn']]
    : action === 'reject_timeout' ? [['T 등록 판정', 'not_evaluable'], ['집행 정책 strict — 기한 초과 거부', 'fail']]
    : [...(failed.length ? failed.map(k => [k, 'fail'] as [string, string]) : [chk('response_binding', 'E10 종단 응답 결합')]),
       chk('R_authority', 'R 중계 진술 자기 정합'),
       ...((checks.response_binding || {}).result === 'fail' && (checks.R_authority || {}).result === 'pass' ? [['귀속 R — 중개 구간 변조', 'fail'] as [string, string]] : [])];
  return `<div class="wf-banner tone-${tone}" data-tone="${tone}">
    <span class="ic">${tone === 'pass' ? '✓' : tone === 'fail' ? '⛨' : tone === 'warn' ? '!' : '…'}</span>
    <div style="min-width:0;flex:1"><div class="ti">${esc(title)}</div><div class="bd">${esc(body)}</div>
      <div class="rules">${rules.map(([text, res]) => `<span class="wf-chip" style="color:${colOf(res)};border-color:${colOf(res)}">${glyphOf(res)} ${esc(text)}</span>`).join('')}</div></div>
    <span class="at">${on ? `t = ${Math.round(d.decided)} ms` : `t = ${Math.round(t)} ms`}</span></div>`;
}

// ---------- 1단 라이프사이클 파이프라인 ----------
function stepsHtml(d: TraceData, t: number, sel: string): string {
  const ph = phases(d);
  return ph.map((p, i) => {
    const s = stateOf(d, p, t), on = sel === p.key, col = colOf(s.res), next = ph[i + 1];
    const prog = Math.max(0, Math.min(1, (t - p.t0) / Math.max(1, p.t1 - p.t0)));
    const fill = next ? Math.max(0, Math.min(1, (t - p.t1) / Math.max(1, (next.t0 - p.t1) || 1))) : 0;
    return `<div class="wf-stepwrap"><button type="button" class="wf-step${on ? ' on' : ''}" data-trace-step="${p.key}">
      <span class="hd"><span class="badge${p.role === 'T' ? ' t' : ''}">${p.role}</span><span class="idx">0${i + 1}</span><span class="gl" style="color:${col}" data-gl>${glyphOf(s.res)}</span></span>
      <span class="ti">${esc(p.title)}</span><span class="sb">${esc(p.sub)}</span>
      <span class="ft"><span class="stt" style="color:${col}" data-state>${esc(s.label)}</span><span class="at" data-at>${t >= p.t0 ? `t = ${Math.round(Math.min(t, p.t1))} ms` : `t = ${Math.round(p.t0)} ms`}</span></span>
      <span class="bar"><span data-bar style="background:${col};width:${(prog * 100).toFixed(1)}%"></span></span></button>
      ${next ? `<span class="wf-conn"><span data-conn style="background:${t >= p.t1 ? 'var(--accent)' : 'var(--line-strong)'};width:${(fill * 100).toFixed(1)}%"></span></span>` : ''}</div>`;
  }).join('');
}

// ---------- 3단 인스펙터 ----------
type Row = {k: string; v: string; mono?: boolean; color?: string};
const kv = (k: string, v: string, mono = true, color?: string): Row => ({k, v, mono, color});
function inspector(d: TraceData, sel: string): {role: string; title: string; sub: string; state: string; color: string; rows: Row[]; chips: [string, string][]} {
  const r = d.record, checks: Data = r.checks || {}, g = r.gate, v = r.t_verdict?.payload, s = d.status;
  const c = (k: string) => checks[k] || {result: 'not_evaluable', reason: '기록 없음'};
  const res = (k: string) => c(k).result as string;
  const line = (k: string) => `${res(k)} — ${c(k).reason || ''}`;
  const chip = (k: string, label: string): [string, string] => [label, res(k)];
  switch (sel) {
    case 'sign': return {role: 'U', title: 'U 요청 계약', sub: 'contract · 전송 전 큐 등록', state: '서명 확인', color: colOf('pass'),
      rows: [kv('요청 ID', esc(r.sub)), kv('시도 ID', esc(r.attempt_id || '—')), kv('허용 모델', esc(s?.model_id || r.model_kind || '—')),
        kv('만료', `sent + 60,000 ms · 정책 ${s ? new Date(s.policy_expires_at).toLocaleString('ko-KR') : '—'}`), kv('정책 해시', s ? short(s.policy_hash) : '—'), kv('집행 모드', esc(r.mode))],
      chips: [['U 서명 계약 · 전송 전 큐 등록', 'pass'], chip('not_expired', '계약 유효기간')]};
    case 'relay': return {role: 'R', title: 'R 중계 진술', sub: '전달 해시 · 변환 선언', state: res('R_authority') === 'pass' ? '자기 정합' : res('R_authority'), color: colOf(res('R_authority')),
      rows: [kv('발행자·역할', line('R_authority'), false, colOf(res('R_authority'))), kv('승인 요청 결합', line('request_binding'), false, colOf(res('request_binding'))),
        kv('허용 경로', line('route_allowed'), false, colOf(res('route_allowed'))), kv('처리 지연', '추정 — 홉 20 ms · 중개 처리 5 ms 비율 (U 는 R 내부를 실측하지 않는다)')],
      chips: [chip('R_authority', 'R 발행자·역할 인증'), chip('request_binding', '승인 요청 결합')]};
    case 'infer': return {role: 'M', title: 'M 추론 영수증', sub: '응답 커밋 · 시도 결합', state: res('M_authority') === 'pass' ? '서명 확인' : res('M_authority'), color: colOf(res('M_authority')),
      rows: [kv('발행자·역할', line('M_authority'), false, colOf(res('M_authority'))), kv('영수증 서명', line('receipt_signature'), false, colOf(res('receipt_signature'))),
        kv('등록 기준 해시', line('model_hash_reference'), false, colOf(res('model_hash_reference'))), kv('시도 ID 결합', line('attempt_match'), false, colOf(res('attempt_match'))),
        kv('모델', esc(r.model_kind || '—')), kv('추론 지연', '추정 — 200 ms 비율 (실측 아님)')],
      chips: [chip('nonce_match', 'nonce 결합'), chip('attempt_match', '시도 결합'), chip('route_allowed', '승인 모델 경로')]};
    case 'ledger': return {role: 'T', title: 'T 원장 등록 · 사후 판정', sub: 'RFC 9162 Merkle · 등록 영수증', state: v ? '등록 완료' : (r.t_error ? '판정 미확인' : '등록 대기'), color: v ? colOf(st(v.verification_status)) : colOf('na'),
      rows: v ? [kv('판정', esc(v.verification_status), true, colOf(st(v.verification_status))), kv('완전성', esc(v.completeness)), kv('보증', esc(v.established_assurance)),
          kv('협조 집합', esc(v.cooperation_set)), kv('참조 진술', `${(v.evidence_refs || []).length}건 · 서명 무효 ${(v.invalid_signature_refs || []).length}건`),
          kv('발행 시각', d.verdictAt != null ? `${Math.round(d.verdictAt)} ms · T 시계` : '요청 시작 이전 (사후 조회)')]
        : [kv('원장 리프', '없음 — 큐 보관', true, 'var(--na)'), kv('판정', r.t_error ? esc(r.t_error) : '아직 조회하지 않음', true, 'var(--na)'),
          kv('제출 대기', s ? `${s.pending_evidence}건` : '—'), kv('갱신', "'T 사후 판정 갱신' 으로 조회")],
      chips: v ? [['인증된 T 판정', 'pass']] : [['결손 — 위반이 아님', 'not_evaluable']]};
    default: { const failed = Object.entries(checks).filter(([, x]: [string, any]) => x.result === 'fail').map(([k]) => k);
      return {role: 'U', title: 'U Gate 집행', sub: 'itx/enforce/user_gate.py', state: g ? g.action : (r.state || '—'), color: colOf(actionRes(g?.action)),
      rows: [kv('모드', esc(r.mode)), kv('로컬 검증', failed.length ? `실패 — ${failed.join(', ')}` : '전 항목 일치', true, failed.length ? 'var(--fail)' : 'var(--pass)'),
        kv('공개 여부', d.released != null ? `공개 · ${Math.round(d.released)} ms` : g?.action === 'reject_timeout' ? '거부 — 판정 대기 만료' : '차단 — 애플리케이션 전달 없음', false, colOf(actionRes(g?.action))),
        kv('사유', esc((g?.reasons || []).join(' · ') || '—'), false), kv('대기', g ? `${g.waited_ms} ms` : '—'), kv('집행 시각', ms(d.decided))],
      chips: [chip('response_binding', '종단 응답 결합'), chip('receipt_present', '영수증 동봉')]}; }
  }
}
function inspectorHtml(d: TraceData, sel: string): string {
  const i = inspector(d, sel);
  return `<div class="wf-card"><div class="hd"><span class="badge${i.role === 'T' ? ' t' : ''}">${i.role}</span><span style="min-width:0;flex:1"><span class="ti">${esc(i.title)}</span><span class="sb">${esc(i.sub)}</span></span><span class="stt" style="color:${i.color}">${esc(i.state)}</span></div>
    <div class="bd">${i.rows.map(row => `<div class="wf-row"><span class="k">${esc(row.k)}</span><span class="v${row.mono === false ? ' sans' : ''}" style="color:${row.color || 'var(--fg)'}">${row.v}</span></div>`).join('')}
      <div class="chips">${i.chips.map(([text, res]) => `<span class="wf-chip" style="color:${colOf(res)};border-color:${colOf(res)}">${glyphOf(res)} ${esc(text)}</span>`).join('')}</div></div></div>`;
}
function eqPanelHtml(d: TraceData): string {
  const r = d.record, v = r.t_verdict?.payload, g = r.gate, checks: Data = r.checks || {};
  const eq = v?.equations?.E10, chk = checks.response_binding || {};
  const result: string = eq?.result || chk.result || 'not_evaluable', fail = result === 'fail', col = colOf(result);
  const reason = eq?.reason || chk.reason || '기록 없음 — T 사후 판정을 갱신하면 등식 사유가 채워진다.';
  const cmp: string[] = eq?.compared || [];
  const disc = (v?.discrepancies || []).find((x: Data) => /RESP/.test(String(x.code))) || (v?.discrepancies || [])[0];
  const action = g?.action || '';
  const actionText = action === 'accept' ? '수용 — 원본 응답으로 공개' : action === 'accept_unverified' ? '공개 — observe 모드는 차단하지 않음'
    : action === 'reject_timeout' ? '거부 — 기한 내 T 판정 없음' : action === 'quarantine' ? '격리 — 애플리케이션 출력 공개 선제 차단' : action ? `${action}` : '결정 없음';
  const note = action === 'quarantine' ? '변조된 본문은 화면·도구·후속 업무로 넘어가지 않습니다. 증거는 T 재제출 큐에 남습니다.'
    : action === 'accept_unverified' ? '노출 구간은 타임라인의 해칭 막대입니다. 사용 이후 T 판정까지가 피해 노출입니다.'
    : action === 'reject_timeout' ? 'protect 모드라면 로컬 증거만으로 계속 진행할 수 있습니다. 비용은 대기 대신 노출입니다.'
    : action === 'accept' ? '요청 계약·경로·시도 결합까지 확인했으므로 업무에 그대로 씁니다.' : '';
  // 등식의 비교 대상은 "M.response_commit vs U.resp_commit" 꼴 한 줄이다 — 양변을 A/B 로 나눠 보인다.
  const sides: string[] = cmp.flatMap(x => String(x).split(/\s+vs\s+|\s*==\s*|\s*≠\s*|\s*!=\s*/).map(y => y.trim()).filter(Boolean));
  const diff = sides.length ? sides.slice(0, 2).map((x, i) => `<div class="wf-diff${fail && i > 0 ? ' bad' : ''}"><span class="tg">${String.fromCharCode(65 + i)}</span><span class="who">${i === 0 ? 'M 이 서명한 응답' : 'U 가 받은 응답'}</span><span class="hs" style="color:${fail && i > 0 ? 'var(--fail)' : 'var(--fg)'}">${esc(x)}${fail && i > 0 ? '  ← 불일치' : ''}</span></div>`).join('')
    : `<div class="wf-diff"><span class="tg">A</span><span class="who">M 이 서명한 응답</span><span class="hs muted">영수증 커밋 — 로컬 검사 ${esc(chk.result || '—')}</span></div><div class="wf-diff${fail ? ' bad' : ''}"><span class="tg">B</span><span class="who">U 가 받은 응답</span><span class="hs muted">수신 본문 해시 — T 판정 갱신 후 비교 대상이 채워진다</span></div>`;
  return `<div class="wf-card eq" style="border-color:${fail ? 'var(--fail)' : 'var(--line)'}"><div class="hd"><span class="eqid" style="color:${col}">E10</span><span class="ti" style="flex:1">종단 응답 결합</span><span class="wf-chip" style="color:${col};border-color:${col}">${fail ? '실패' : result === 'pass' ? '일치' : result}</span></div>
    <div class="bd"><div class="reason">${esc(reason)}</div><div class="diffs">${diff}</div>
      <div class="act"><div class="lb">조치</div><div class="ac" style="color:${colOf(actionRes(action))}">${esc(actionText)}</div><div class="nt">${esc(note)}</div></div>
      <div class="wf-cells"><div><div class="k">등식</div><div class="v">E10</div></div><div><div class="k">신뢰 등급</div><div class="v">${esc(eq?.trust_grade || 'local check')}</div></div>
        <div><div class="k">귀속</div><div class="v" style="color:${disc ? 'var(--fail)' : 'var(--na)'}">${disc ? esc(disc.attribution) : '해당 없음'}</div></div>
        <div><div class="k">불일치 코드</div><div class="v" style="color:${(v?.discrepancies || []).length ? 'var(--fail)' : 'var(--na)'}">${(v?.discrepancies || []).length ? (v.discrepancies as Data[]).map(x => esc(x.code)).join(', ') : '없음'}</div></div></div></div></div>`;
}

// ---------- 마크업 · 마운트 ----------
export function traceTopHtml(d: TraceData, t = d.tEnd): string {
  return `<div data-trace-banner>${bannerHtml(d, t)}</div>
    <div class="wf-sec"><h3>1단 — 라이프사이클 파이프라인</h3><span class="wf-hint">단계를 누르면 3단 인스펙터가 그 단계의 증명으로 바뀝니다</span></div>
    <div class="wf-steps" data-trace-steps>${stepsHtml(d, t, 'gate')}</div>`;
}
export function traceBottomHtml(d: TraceData): string {
  return `<div class="wf-sec"><h3>3단 — 스플릿 인스펙터</h3><span class="wf-hint">왼쪽 · 선택 단계의 암호 증명 &nbsp;/&nbsp; 오른쪽 · 판정 근거</span></div>
    <div class="wf-insp"><div data-trace-insp>${inspectorHtml(d, 'gate')}</div>${eqPanelHtml(d)}</div>`;
}
export function mountTrace(root: HTMLElement, d: TraceData, _pb: Playback | null) {
  let sel = 'gate', tone = '';
  const stepsEl = root.querySelector<HTMLElement>('[data-trace-steps]'), bannerEl = root.querySelector<HTMLElement>('[data-trace-banner]'), inspEl = root.querySelector<HTMLElement>('[data-trace-insp]');
  if (!stepsEl || !bannerEl || !inspEl) return;
  const ph = phases(d);
  const update = (t: number) => {
    const nextTone = (bannerEl.firstElementChild as HTMLElement | null)?.dataset.tone ?? '';
    const want = t >= d.decided && d.record.gate ? actionRes(d.record.gate.action) : 'na';
    if (want !== nextTone || tone !== want) { bannerEl.innerHTML = bannerHtml(d, t); tone = want; }
    else { const at = bannerEl.querySelector<HTMLElement>('.at'); if (at && want === 'na') at.textContent = `t = ${Math.round(t)} ms`; }
    ph.forEach((p, i) => {
      const el = stepsEl.querySelectorAll<HTMLElement>('.wf-step')[i]; if (!el) return;
      const s = stateOf(d, p, t), col = colOf(s.res), next = ph[i + 1];
      const gl = el.querySelector<HTMLElement>('[data-gl]'), stt = el.querySelector<HTMLElement>('[data-state]'), at = el.querySelector<HTMLElement>('[data-at]'), bar = el.querySelector<HTMLElement>('[data-bar]');
      if (gl) { gl.textContent = glyphOf(s.res); gl.style.color = col; }
      if (stt) { stt.textContent = s.label; stt.style.color = col; }
      if (at) at.textContent = t >= p.t0 ? `t = ${Math.round(Math.min(t, p.t1))} ms` : `t = ${Math.round(p.t0)} ms`;
      if (bar) { bar.style.background = col; bar.style.width = (Math.max(0, Math.min(1, (t - p.t0) / Math.max(1, p.t1 - p.t0))) * 100).toFixed(1) + '%'; }
      const conn = stepsEl.querySelectorAll<HTMLElement>('[data-conn]')[i];
      if (conn && next) { conn.style.background = t >= p.t1 ? 'var(--accent)' : 'var(--line-strong)'; conn.style.width = (Math.max(0, Math.min(1, (t - p.t1) / Math.max(1, (next.t0 - p.t1) || 1))) * 100).toFixed(1) + '%'; }
    });
  };
  stepsEl.addEventListener('click', e => {
    const b = (e.target as HTMLElement).closest<HTMLElement>('[data-trace-step]'); if (!b) return;
    sel = b.dataset.traceStep!;
    stepsEl.querySelectorAll('.wf-step').forEach(n => n.classList.toggle('on', (n as HTMLElement).dataset.traceStep === sel));
    inspEl.innerHTML = inspectorHtml(d, sel);
  });
  // 재생 엔진의 프레임 이벤트(캔버스에서 버블)로 세 단이 같은 시점을 본다.
  root.addEventListener('playbackframe', e => update((e as CustomEvent<{t: number}>).detail.t));
  update(d.tEnd);
}
