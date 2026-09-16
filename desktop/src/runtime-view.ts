// 요청과 보호 화면: U Agent 의 실제 기록(record)을 콘솔 요소로 그린다.
// U 가 실측한 것은 전송·수신·결정·공개 시각뿐이다. R·M 내부 구간은 비율 추정이며 그렇게 표기한다.
// 홉 지도는 flow.ts 의 그래프 캔버스(Claude Design Hopmap Console v2 원안)로 그린다.
import {
  Data, esc, short, CV, makeSpan, PlayContext, timeBoxHtml, Mark, evidenceRowsHtml, stripGridHtml,
  checksTableHtml, equationTableHtml, codesHtml, gateColor, checkChipsHtml, st, playControlsHtml,
} from './console';
import { FlowData, flowCanvasHtml, flowLegs, footHtml, eqFromChecks, eqFromEquations, actionTone, toneOf } from './flow';
import { TraceData, traceTopHtml, traceBottomHtml } from './trace';

export const STATE_NAMES: Record<string, string> = {accept: '검증 후 수용', accept_unverified: '미검증 수용', quarantine: '응답 격리', reject: '수용 거부', reject_timeout: 'T 판정 기한 초과', cancelled: '취소 · 미공개', interrupted: '종료로 중단 · 미공개', pending: '진행 중', error: '요청 오류'};
export const CHECK_NAMES: Record<string, string> = {M_authority: 'M 발행자·역할 인증', R_authority: 'R 발행자·역할 인증', not_expired: '계약 유효기간', receipt_present: '모델 영수증', receipt_signature: '영수증 서명', nonce_match: 'nonce 결합', request_binding: '승인된 요청 결합', response_binding: '종단 응답 결합', attempt_match: '시도 ID 결합', model_hash_reference: '등록 기준 해시', route_allowed: '허용 모델 경로', tool_policy: '도구 실행 정책'};
const SCENARIO_NAMES: Record<string, string> = {normal: '정상 경로', response_tamper: 'R 의 응답 변조', request_tamper: 'R 의 요청 변조', missing_receipt: 'M 영수증 제거'};

interface Moments { sent: number | null; received: number | null; released: number | null; quarantined: number | null; aborted: number | null; waitedT: boolean }
function moments(record: Data): Moments {
  const m: Moments = {sent: null, received: null, released: null, quarantined: null, aborted: null, waitedT: false};
  for (const e of record.timeline || []) {
    const k: string = e.kind, t: number = e.t_ms;
    if (k.includes('요청 전송')) m.sent = t;
    else if (k.includes('응답 수신')) m.received = t;
    else if (k.includes('공개') && !k.includes('미공개') && !k.includes('않음')) m.released = t;
    else if (k.includes('격리')) m.quarantined = t;
    else if (k.includes('중단')) m.aborted = t;
    else if (k.includes('T 판정 대기')) m.waitedT = true;
  }
  return m;
}
export const isAttack = (record: Data) => !!record.lab_scenario && record.lab_scenario !== 'normal';

export type MapMode = 'checks' | 'equations';
export interface RouteCard { html: string; ctx: PlayContext | null; flow: FlowData; trace: TraceData | null }

// 실행 전 상태: 모든 검사가 회색이다. 부재를 사건처럼 그리지 않는다.
export function idleRouteHtml(status: Data | null): RouteCard {
  const flow: FlowData = {key: 'req', eq: {}, rowTitle: Object.fromEntries(Object.entries(CHECK_NAMES).map(([k, v]) => [checkEq(k), v])),
    regs: {U: null, R: null, M: null}, sent: 0, received: 1, latency: 200, sm: null,
    info: {id: status ? esc(status.source) : '연결 전', title: '아직 실행한 요청이 없다', verdict: '대기', verdictTone: 'na', action: '—', actionTone: 'na', note: 'evaluation'},
    foot: '<p class="small muted" style="margin:0">첫 요청 뒤 U 의 로컬 검사 결과가 이 지도에 표시된다.</p>'};
  const html = `<div class="card-head"><h3>경로 — 업무 데이터 경로(실선)와 T 의 증거·통제 경로(점선)</h3><div class="badges"><span>${status ? esc(status.source) : '연결 전'}</span><span>evaluation</span></div></div>
    ${flowCanvasHtml(flow)}`;
  return {html, ctx: null, flow, trace: null};
}
const checkEq = (k: string) => ({not_expired: 'E12', tool_policy: 'E1', nonce_match: 'E5', route_allowed: 'E8', model_hash_reference: 'E9', attempt_match: 'E11', request_binding: 'E2', R_authority: 'E3', receipt_signature: 'E4', M_authority: 'E6', receipt_present: 'E7', response_binding: 'E10'} as Record<string, string>)[k] || k;

export function routeCard(record: Data, status: Data | null, mode: MapMode): RouteCard {
  const mm = moments(record);
  const checks: Data = record.checks || {};
  const v = record.t_verdict?.payload;
  const g = record.gate;
  const attack = isAttack(record);
  const sent = mm.sent ?? 0;
  const received = mm.received ?? (mm.aborted ?? record.elapsed_ms ?? sent);
  const released = mm.released;
  // 게이트의 벽시계(15 ms 해상도)와 시간선의 단조 시계를 섞지 않는다: 결정 직후 기록된 공개·격리 이벤트를 결정 시각으로 쓴다.
  const decided = g ? (released ?? mm.quarantined ?? (mm.received !== null ? received + Math.max(0, g.decided_at - g.received_at) : null)) : null;
  const verdictAt = typeof record.t_verdict?.issued_at === 'number' && record.t_verdict.issued_at > record.started_at ? record.t_verdict.issued_at - record.started_at : null;
  const harmExposed = attack && released !== null;
  const useEq = mode === 'equations' && !!v;
  const eqInfo = useEq ? {eq: eqFromEquations(v.equations), rowTitle: undefined as Record<string, string> | undefined} : eqFromChecks(checks, CHECK_NAMES);
  const canPlay = mm.sent !== null && received > sent;
  const legs = canPlay ? flowLegs(sent, received, 200) : null;

  let ctx: PlayContext | null = null, timebox = '';
  if (legs) {
    const breakpoint = Math.max(60, Math.round(received * 1.4 / 10) * 10);
    const tEnd = Math.max(breakpoint + 40, received, decided ?? 0, released ?? 0, mm.quarantined ?? 0, verdictAt ?? 0, record.elapsed_ms ?? 0) * 1.08;
    const span = makeSpan(breakpoint, tEnd);
    ctx = {legs, tEnd, span, reqFail: checks.request_binding?.result === 'fail', respFail: checks.response_binding?.result === 'fail', consumedAt: released, verdictAt, harmExposed, detectable: true};
    // 원안의 마크: 전송 · M 서명 · 수신 · 사용 · T 판정(또는 판정 없음). 시각은 실측·추정값.
    const marks: Mark[] = [
      {label: '전송', at: `${Math.round(sent)} ms`, pos: span(sent), color: 'muted'},
      {label: 'M 서명', at: `${Math.round(legs[4].t1)} ms · 추정`, pos: span(legs[4].t1), color: 'muted'},
      {label: mm.received === null ? '응답 없음' : '수신', at: `${Math.round(received)} ms`, pos: span(received), color: 'accent'},
    ];
    if (decided !== null && g) marks.push({label: '집행', at: `${Math.round(decided)} ms`, pos: span(decided), color: actionTone(g.action)});
    if (released !== null) marks.push({label: '사용', at: `${Math.round(released)} ms`, pos: span(released), color: 'fail'});
    marks.push(verdictAt !== null ? {label: 'T 판정', at: `${Math.round(verdictAt)} ms`, pos: span(verdictAt), color: 'pass'}
                                  : {label: '판정 없음', at: v ? '사후 조회' : '기한 초과', pos: span(tEnd), color: 'na'});
    timebox = timeBoxHtml(marks);
  } else {
    timebox = `<p class="small muted" style="margin:0">전송 전에 중단되어 시점 축이 없다.</p>`;
  }
  // 원안의 증거 3행. 런타임에서 U 가 아는 것은 동봉 여부뿐이고 등록 시각은 T 원장에만 있다.
  const evidence = evidenceRowsHtml([
    {key: 'U', name: 'U 요청 진술', detail: 'contract · nonce · 허용 모델 집합', reg: null, present: true},
    {key: 'R', name: 'R 중계 진술', detail: '전달 해시 · 변환 선언', reg: null, present: checks.R_authority?.result === 'pass'},
    {key: 'M', name: 'M 응답 영수증', detail: '응답 커밋 · 시도 ID 서명', reg: null, present: checks.M_authority?.result === 'pass'},
  ]);
  const flow: FlowData = {key: 'req', eq: eqInfo.eq, rowTitle: eqInfo.rowTitle, regs: {U: null, R: null, M: null},
    sent, received: canPlay ? received : sent + 1, latency: 200,
    sm: g ? {mode: record.mode, gateAction: g.action, decidedAt: decided ?? received, consumedAt: released, verdictAt} : null,
    info: {id: String(record.sub || '').split(':').pop() || String(record.sub || ''),
      title: record.lab_scenario ? SCENARIO_NAMES[record.lab_scenario] || record.lab_scenario : '연결 모드 · 공격 주입 없음',
      verdict: v ? v.verification_status : '사후 판정 대기', verdictTone: toneOf(v?.verification_status),
      action: g ? g.action : (STATE_NAMES[record.state] || record.state), actionTone: g ? actionTone(g.action) : 'na',
      note: `${record.mode} · ${record.elapsed_ms ?? '—'} ms 실측`},
    foot: footHtml(timebox, evidence), controls: ctx ? playControlsHtml() : ''};
  // 추적 3단(배너·파이프라인·인스펙터)은 재생 구간이 있을 때만 한 시계로 묶인다.
  const trace: TraceData | null = legs && ctx ? {record, status, legs, sent, received, decided: decided ?? received, released, verdictAt, tEnd: ctx.tEnd} : null;
  const toggle = v ? `<div class="tabs" data-map-toggle><button type="button" class="pill${!useEq ? ' on' : ''}" data-map="checks">U 로컬 검사</button><button type="button" class="pill${useEq ? ' on' : ''}" data-map="equations">T 등식 E1~E12</button></div>` : '';
  const html = `<div class="card-head"><h3>경로 — 업무 데이터 경로(실선)와 T 의 증거·통제 경로(점선)</h3>
      <div class="badges"><span>${esc(record.source)}</span><span>evaluation</span><span>${record.lab_scenario ? '실험 조건 · ' + esc(SCENARIO_NAMES[record.lab_scenario] || record.lab_scenario) : '연결 모드 · 공격 주입 없음'}</span></div></div>
    ${trace ? traceTopHtml(trace) : ''}
    <div class="wf-sec"><h3>2단 — 홉 지도 · 패킷 트래커</h3><span class="wf-hint">홉 20ms · 중개 처리 5ms · 서명 2ms · 추론 200ms — 실제 지연 비율</span></div>
    ${toggle ? `<div style="margin:0 0 10px">${toggle}</div>` : ''}
    ${flowCanvasHtml(flow)}
    <p class="small muted" style="margin:10px 0 0">${timeNote(record, mm, g, decided, released, verdictAt, attack)} 등록 시각은 T 의 원장에만 있다. 제출 대기 ${status ? status.pending_evidence : '—'}건 · 사후 판정은 '제3자 검증'에서 갱신한다.</p>
    ${trace ? traceBottomHtml(trace) : ''}
    <div style="margin-top:12px">${stripGridHtml([
      {k: '정책 해시', v: status ? short(status.policy_hash) : '—'}, {k: '모델', v: esc(record.model_kind || '—')},
      {k: '정책 세대', v: status?.epoch != null ? esc(String(status.epoch)) : '실험실'}, {k: '집행 모드', v: esc(record.mode)}])}</div>`;
  return {html, ctx, flow, trace};
}
function timeNote(record: Data, mm: Moments, g: Data | null, decided: number | null, released: number | null, verdictAt: number | null, attack: boolean): string {
  if (record.state === 'cancelled' || record.state === 'interrupted') return '취소·중단된 요청이다. 응답은 공개되지 않았다. 원격 실행이 완료됐는지는 알 수 없으며 자동 재실행하지 않는다.';
  if (record.state === 'error') return '요청이 오류로 끝났다. 응답은 공개되지 않았다.';
  if (released === null) return `응답 공개 없음. ${g ? `게이트 ${g.action} · 대기 ${g.waited_ms} ms.` : ''} 이 사건에서 방어는 '변조된 응답이 업무에 쓰이기 전에 U 가 거부했다' 로 기록된다.`;
  if (attack) return `실험 조건에서 주입한 공격 응답이 ${released} ms 에 공개되었다${verdictAt !== null ? ` · T 판정 ${verdictAt} ms` : ''}. ${record.mode === 'observe' ? 'observe 는 미검증 수용이므로 안전 완료로 세지 않는다.' : '탐지는 되었지만 방어는 실패한 사건이다.'}`;
  return `정상 요청이 검증 뒤 ${released} ms 에 공개되었다. 대기 비용 ${g ? g.waited_ms : decided ?? '—'} ms${mm.waitedT ? ' · T 판정 대기 포함' : ''}.`;
}

export function resultHtml(record: Data): string {
  const v = record.t_verdict?.payload;
  const state = STATE_NAMES[record.state] || record.state;
  let body: string;
  if (record.content_pruned_at) body = `<div class="empty">보관 정책에 따라 본문이 삭제됐습니다. 당시의 집행 결과와 서명 증거는 유지됩니다.</div>`;
  else if (record.response != null) body = `<div class="response-box">${esc(record.response)}</div>`;
  else body = `<div class="blocked-box">${esc(record.error || '응답이 공개되지 않았습니다. 원문을 화면·업무 소비자에 전달하지 않습니다.')}</div>`;
  const g = record.gate;
  return `<div class="result-head"><h3>${esc(state)}</h3><span class="muted small mono">${record.elapsed_ms ?? '—'} ms · 실측</span></div>
    ${body}
    ${g ? `<div class="small"><span class="mono" style="font-weight:700;color:${CV(gateColor(g.action))}">${esc(g.action)}</span> · ${(g.reasons || []).map(esc).join(' · ')}</div>${checkChipsHtml(g.local_checks || {})}` : ''}
    <h3>U 로컬 검사 — 응답 공개 전</h3>
    ${checksTableHtml(record.checks || {}, CHECK_NAMES)}
    <div class="result-actions"><button type="button" data-refresh>T 사후 판정 갱신</button><span class="badge ${v ? (v.verification_status === 'passed' ? 'green' : 'red') : 'amber'}">${v ? 'T: ' + esc(v.verification_status) : 'T: 사후 판정 대기'}</span></div>
    ${v ? `<details open><summary>T 판정 — 등식 E1~E12와 증거 범위</summary>
      <p class="small" style="margin:8px 0 6px"><span class="mono" style="font-weight:700;color:${CV(st(v.verification_status))}">${esc(v.verification_status)}</span><span class="small muted" style="margin-left:10px">완전성 <b>${esc(v.completeness)}</b></span><span class="small muted" style="margin-left:10px">협조 ${esc(v.cooperation_set)}</span><span class="small muted" style="margin-left:10px">보증 <b>${esc(v.established_assurance)}</b></span></p>
      ${codesHtml(v.discrepancies || [])}
      ${equationTableHtml(v.equations || {})}
      <ul class="tight small muted">${(v.notes || []).map((n: string) => `<li>${esc(n)}</li>`).join('')}</ul></details>` : ''}
    ${record.t_error && !v ? `<p class="field-help">T 판정 미확인: ${esc(record.t_error)}</p>` : ''}
    <details><summary>집행 기록 · 수용된 응답 포함</summary><pre>${esc(JSON.stringify(record, null, 2))}</pre></details>`;
}

// 실행 시간선: U 의 단조 시계. 붉은 행 = 응답 공개, 녹색 행 = 격리·중단 결정.
export function timelineHtml(record: Data | null): string {
  const rows = record?.timeline || [];
  if (!rows.length) return `<p class="small muted" style="margin:0">아직 실행한 요청이 없습니다.</p>`;
  const body = rows.map((e: Data, i: number) => {
    const k: string = e.kind;
    const mark = (k.includes('공개') && !k.includes('미공개') && !k.includes('않음')) ? 'mark' : (k.includes('격리') || k.includes('중단')) ? 'decide' : '';
    return `<tr><td class="muted">${i + 1}</td><td class="mono">${e.t_ms}</td><td><b>${esc(e.actor)}</b></td><td class="${mark}">${esc(k)}</td></tr>`;
  }).join('');
  return `<div class="tablewrap"><table class="lanes" style="font-size:12px"><thead><tr><th>#</th><th>t ms</th><th>주체</th><th>사건</th></tr></thead><tbody>${body}</tbody></table></div>`;
}
