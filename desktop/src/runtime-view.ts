// 요청 화면: U Agent 의 실제 기록(record)을 Console v3 구조로 그린다.
//   1) 결과 요약 — 검증 결과와 응답 공개 여부는 별개의 두 축이다. 한 줄에 섞으면 둘 중 하나를 잘못 읽는다.
//   2) 응답 본문 — 공개된 경우에만 원문. 격리·거부·대기는 점선 상자와 이유만.
//   3) 경로 상세 — 홉 지도(flow.ts 그래프 캔버스) · 추적 3단 · 로컬 검사 · T 판정 · 시간선. 기본 화면은 결론이고 이것은 근거다.
// U 가 실측한 것은 전송·수신·결정·공개 시각뿐이다. R·M 내부 구간은 비율 추정이며 그렇게 표기한다.
import {
  Data, esc, short, CV, makeSpan, PlayContext, timeBoxHtml, Mark, evidenceRowsHtml, stripGridHtml,
  checksTableHtml, equationTableHtml, codesHtml, gateColor, checkChipsHtml, st, playControlsHtml,
} from './console';
import { FlowData, flowCanvasHtml, flowLegs, footHtml, eqFromChecks, eqFromEquations, actionTone, toneOf } from './flow';
import { TraceData, traceTopHtml, traceBottomHtml } from './trace';

export const STATE_NAMES: Record<string, string> = {accept: '검증 후 수용', accept_unverified: '미검증 수용', quarantine: '응답 격리', reject: '수용 거부', reject_timeout: 'T 판정 기한 초과', cancelled: '취소 · 미공개', interrupted: '종료로 중단 · 미공개', pending: '진행 중', error: '요청 오류'};
export const CHECK_NAMES: Record<string, string> = {M_authority: 'M 발행자·역할 인증', R_authority: 'R 발행자·역할 인증', not_expired: '계약 유효기간', receipt_present: '모델 영수증', receipt_signature: '영수증 서명', nonce_match: 'nonce 결합', request_binding: '승인된 요청 결합', response_binding: '종단 응답 결합', attempt_match: '시도 ID 결합', model_hash_reference: '등록 기준 해시', route_allowed: '허용 모델 경로', tool_policy: '도구 실행 정책'};
export const SCENARIO_NAMES: Record<string, string> = {normal: '정상 경로', response_tamper: 'R 의 응답 변조', request_tamper: 'R 의 요청 변조', missing_receipt: 'M 영수증 제거'};
/** 집행 정책 카드. 제목은 사람 말, 코드는 실제 값. 본문이 곧 이전 화면의 mode-help 였다. */
export const MODES: {code: string; title: string; body: string}[] = [
  {code: 'protect', title: '기본 보호', body: '로컬 검증에 실패하면 응답을 업무에 넘기지 않고 격리합니다. T 가 연결되지 않아도 필수 로컬 증거와 유효한 정책이 있으면 계속합니다.'},
  {code: 'strict', title: '제3자 확인 후 수용', body: '로컬 검사와 T 의 등록 판정을 모두 요구합니다. 기한 내 판정이 없으면 거부합니다.'},
  {code: 'observe', title: '관찰 전용', body: '상태만 알리고 차단하지 않습니다. 검증 실패 응답도 그대로 공개됩니다 — 공격을 관측하기 위한 대조군이며 방어 모드가 아닙니다.'},
];

interface Moments { sent: number | null; received: number | null; released: number | null; quarantined: number | null; aborted: number | null; waitedT: boolean }
export function moments(record: Data): Moments {
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

// ---------- 결과 요약: 검증 결과 / 응답 공개 여부 / 다음 행동 ----------
export type VerdictTone = 'pass' | 'fail' | 'na' | 'wait';
export type ReleaseTone = 'open' | 'blocked' | 'wait';

/** 검증 축. 색을 쓰는 유일한 축이다. 결손(판정 없음·취소)은 fail 이 아니라 na 다. */
export function verdictOf(record: Data | null): VerdictTone {
  if (!record || record.state === 'pending') return 'wait';
  const checks: Data = record.checks || {};
  const failed = Object.values(checks).some((c: any) => c && c.result === 'fail');
  const v = record.t_verdict?.payload;
  if (failed || v?.verification_status === 'failed') return 'fail';
  if (['cancelled', 'interrupted', 'error'].includes(record.state) || !Object.keys(checks).length) return 'na';
  if (record.gate?.action === 'reject_timeout') return 'na';
  return 'pass';
}
/** 공개 축. 색을 쓰지 않는다 — 공개는 사건이지 판정이 아니다. */
export function releaseOf(record: Data | null): ReleaseTone {
  if (!record || record.state === 'pending') return 'wait';
  return record.response != null ? 'open' : 'blocked';
}
export function releaseLabel(record: Data | null): string {
  const r = releaseOf(record), a = record?.gate?.action;
  if (r === 'wait') return '대기';
  if (r === 'open') return a === 'accept_unverified' ? '공개됨 · 검증 실패' : '공개됨';
  if (a === 'quarantine') return '공개 안 됨 · 격리';
  if (a === 'reject_timeout' || a === 'reject') return '공개 안 됨 · 거부';
  if (a === 'no_response') return '공개 안 됨 · 응답 없음';
  if (record?.state === 'cancelled' || record?.state === 'interrupted') return '공개 안 됨 · 취소';
  if (record?.state === 'error') return '공개 안 됨 · 오류';
  return '공개 안 됨';
}

const FAILED = (record: Data) => Object.entries(record.checks || {}).filter(([, c]: [string, any]) => c && c.result === 'fail');

export function summaryHtml(record: Data | null, busy = false): string {
  const vt = busy ? 'wait' : verdictOf(record), rt = busy ? 'wait' : releaseOf(record);
  const g = record?.gate, v = record?.t_verdict?.payload, a: string = g?.action || '';
  const mm = record ? moments(record) : null;
  const decided = g && mm ? (mm.released ?? mm.quarantined ?? (mm.received !== null ? mm.received + Math.max(0, g.decided_at - g.received_at) : null)) : null;
  const failed = record ? FAILED(record) : [];

  let vTitle: string, vBody: string;
  if (vt === 'wait') { vTitle = busy ? '검증 진행 중' : '아직 실행한 요청이 없습니다'; vBody = busy ? '응답과 영수증이 아직 집행 모듈에 도착하지 않았습니다. 이 단계에서는 어떤 판정도 확정하지 않습니다.' : '요청을 실행하면 검증 결과와 응답 공개 여부가 여기에 두 줄로 나뉘어 표시됩니다.'; }
  else if (vt === 'pass') { vTitle = '검증 통과'; vBody = `M 이 서명한 응답 해시와 받은 응답 해시가 같습니다. 승인 경로·모델·시도 결합까지 로컬에서 확인했습니다.${v ? ` T 사후 판정 ${esc(v.verification_status)} · 완전성 ${esc(v.completeness)}.` : ' T 사후 판정은 아직 조회하지 않았습니다.'}`; }
  else if (vt === 'fail') {
    const names = failed.map(([k]) => CHECK_NAMES[k] || k);
    const reasons = failed.map(([, c]: [string, any]) => c.reason).filter(Boolean);
    const r = record!.checks || {};
    const attribution = r.response_binding?.result === 'fail' && r.R_authority?.result === 'pass' ? ' R 의 진술은 자기 정합적이므로 차이는 중개 구간에서 생겼습니다.' : '';
    vTitle = `검증 실패 — ${names.join(', ') || (v ? 'T 판정 ' + esc(v.verification_status) : '')}`;
    vBody = `${reasons.map(esc).join(' · ') || (v ? (v.notes || []).map(esc).join(' · ') : '')}${attribution}`;
  } else if (a === 'reject_timeout') { vTitle = '판정 대기 — 기한 내 T 판정 없음'; vBody = 'strict 정책은 T 의 등록 판정까지 기다립니다. T 가 응답하지 않아 판정이 없습니다. 결손이며 위반이 아닙니다.'; }
  else if (record?.state === 'error') { vTitle = '요청 오류'; vBody = esc(record.error || '요청이 오류로 끝났습니다.'); }
  else { vTitle = '결정 없음 — 취소·중단'; vBody = '게이트 결정 전에 끝났습니다. 원격 실행이 완료됐는지는 알 수 없으며 자동 재실행하지 않습니다.'; }

  let rTitle: string, rBody: string;
  if (rt === 'wait') { rTitle = '대기'; rBody = '집행 판단이 아직 내려지지 않았습니다.'; }
  else if (rt === 'open') { rTitle = a === 'accept_unverified' ? '공개됨 — 검증 실패 상태로' : '공개됨'; rBody = a === 'accept_unverified' ? '관찰 전용 정책은 차단하지 않습니다. 검증에 실패한 응답이 업무에 노출되었습니다.' : '응답이 애플리케이션으로 전달되었습니다.'; }
  else if (a === 'quarantine') { rTitle = '공개 안 됨 — 격리'; rBody = '변조된 본문은 화면·도구·후속 업무로 넘어가지 않았습니다. 증거는 재제출 큐에 남습니다.'; }
  else if (a === 'reject_timeout' || a === 'reject') { rTitle = '공개 안 됨 — 거부'; rBody = a === 'reject_timeout' ? '기한 내 제3자 판정이 없어 응답을 업무에 쓰지 않았습니다.' : `응답을 업무에 쓰지 않았습니다. ${(g?.reasons || []).map(esc).join(' · ')}`; }
  else if (a === 'no_response') { rTitle = '공개 안 됨 — 응답 없음'; rBody = '중개 경로에서 응답이 돌아오지 않았습니다. 공개할 본문이 없으므로 게이트는 아무것도 수용하지 않습니다.'; }
  else { rTitle = `공개 안 됨 — ${esc(STATE_NAMES[record?.state || ''] || record?.state || '')}`; rBody = record?.state === 'error' ? esc(record.error || '') : '응답은 공개되지 않았습니다.'; }

  const next = vt === 'wait' ? (busy ? '검증이 끝나면 조치가 여기에 표시됩니다. 지금은 응답과 영수증이 도착하는 중입니다.' : '프롬프트와 집행 정책을 확인한 뒤 「요청 실행」을 누르세요.')
    : a === 'quarantine' ? `격리 사유(${failed.map(([k]) => CHECK_NAMES[k] || k).join(', ') || '로컬 검사 실패'})를 확인하고 R 에게 이의를 제기합니다. 재요청은 같은 계약으로 즉시 가능합니다.`
    : a === 'accept_unverified' ? '노출 범위를 확인하고 정책을 기본 보호로 올리는 것을 검토합니다.'
    : a === 'reject_timeout' ? 'T 복구를 기다리거나, 로컬 증거만으로 진행하려면 기본 보호로 낮춥니다.'
    : a === 'accept' ? (v ? '추가 조치가 필요하지 않습니다. 증거 번들은 감사 자료에서 내보낼 수 있습니다.' : '「T 사후 판정 갱신」으로 등록 판정을 조회하면 등식 E1~E12 근거가 채워집니다.')
    : '취소·오류 사건입니다. 필요하면 같은 계약으로 다시 요청합니다.';

  const vTone = vt === 'wait' ? 'na' : vt, dashedV = vt === 'na' || vt === 'wait';
  const vGlyph = vt === 'pass' ? '✓' : vt === 'fail' ? '✗' : vt === 'na' ? '–' : '…';
  const rGlyph = rt === 'open' ? '◆' : rt === 'blocked' ? '⛔' : '…';
  const vAt = vt === 'wait' ? '' : decided != null ? `t = ${Math.round(decided)} ms` : '';
  const rAt = rt === 'open' && mm?.released != null ? `t = ${Math.round(mm.released)} ms` : rt === 'blocked' ? '공개 없음' : '';
  return `<div class="v3-sum-row tone-${vTone}"><span class="v3-sum-icon${dashedV ? ' dashed' : ''}">${vGlyph}</span>
      <span class="v3-sum-text"><span class="v3-sum-k">검증 결과</span><span class="v3-sum-t ${vTone === 'na' ? 'na' : vTone}">${vTitle}</span><span class="v3-sum-b">${vBody}</span></span>
      <span class="v3-sum-at mono">${vAt}</span></div>
    <div class="v3-sum-row tone-neutral"><span class="v3-sum-icon${rt !== 'open' ? ' dashed' : ''}">${rGlyph}</span>
      <span class="v3-sum-text"><span class="v3-sum-k">응답 공개 여부</span><span class="v3-sum-t">${rTitle}</span><span class="v3-sum-b">${rBody}</span></span>
      <span class="v3-sum-at mono">${rAt}</span></div>
    <div class="v3-sum-next"><b>다음 행동</b><span>${next}</span>${record ? '<button type="button" class="v3-btn outline" data-open-detail>경로 상세 열기</button>' : ''}</div>`;
}

// ---------- 응답 본문 ----------
export function bodyHtml(record: Data): string {
  let body: string;
  if (record.content_pruned_at) body = `<div class="v3-body absent">보관 정책에 따라 본문이 삭제됐습니다. 당시의 집행 결과와 서명 증거는 유지됩니다.</div>`;
  else if (record.response != null) body = `<div class="v3-body open">${esc(record.response)}</div>`;
  else if (record.state === 'pending') body = `<div class="v3-body absent">응답이 아직 도착하지 않았습니다. 집행 판단 전에는 본문을 표시하지 않습니다.</div>`;
  else body = `<div class="v3-body absent">${esc(record.error || (record.gate?.action === 'quarantine' ? '격리된 본문은 표시하지 않습니다. 해시와 영수증만 증거로 남습니다.' : '응답이 공개되지 않았습니다. 원문을 화면·업무 소비자에 전달하지 않습니다.'))}</div>`;
  const v = record.t_verdict?.payload;
  return `${body}
    <div class="v3-body-foot mono">
      <span>요청 ID</span><span class="hashchip" data-copy="${esc(record.sub || '')}" role="button" tabindex="0" title="클릭하면 전체 값을 복사합니다">${esc(String(record.sub || '').slice(-18))}</span>
      <span class="muted">시도 ID</span><span class="chipv">${esc(String(record.attempt_id || '—').slice(-14))}</span>
      <span class="muted">소요</span><span class="chipv">${record.elapsed_ms ?? '—'} ms · 실측</span>
      <span class="muted">T 판정</span><span class="badge ${v ? (v.verification_status === 'passed' ? 'green' : 'red') : 'amber'}">${v ? esc(v.verification_status) : '사후 판정 대기'}</span>
    </div>`;
}

// ---------- 경로 상세 안의 근거: 게이트 · 로컬 검사 · T 판정 · 원 기록 ----------
export function detailHtml(record: Data): string {
  const v = record.t_verdict?.payload;
  const g = record.gate;
  return `<div class="v3-sub"><div class="v3-sub-head"><span class="v3-card-title">집행 · 로컬 검사</span><span class="v3-meta">응답 공개 전 U 가 직접 확인한 항목</span></div>
    ${g ? `<div class="small" style="margin-bottom:8px"><span class="mono" style="font-weight:700;color:${CV(gateColor(g.action))}">${esc(g.action)}</span> · ${(g.reasons || []).map(esc).join(' · ')}</div>${checkChipsHtml(g.local_checks || {})}` : ''}
    ${checksTableHtml(record.checks || {}, CHECK_NAMES)}
    <div class="result-actions"><button type="button" class="v3-btn" data-refresh>T 사후 판정 갱신</button><span class="badge ${v ? (v.verification_status === 'passed' ? 'green' : 'red') : 'amber'}">${v ? 'T: ' + esc(v.verification_status) : 'T: 사후 판정 대기'}</span></div></div>
    ${v ? `<div class="v3-sub"><div class="v3-sub-head"><span class="v3-card-title">T 판정 — 등식 E1~E12 와 증거 범위</span><span class="v3-meta">세션 종료 후 T 가 서명·등록한 판정</span></div>
      <p class="small" style="margin:0 0 6px"><span class="mono" style="font-weight:700;color:${CV(st(v.verification_status))}">${esc(v.verification_status)}</span><span class="small muted" style="margin-left:10px">완전성 <b>${esc(v.completeness)}</b></span><span class="small muted" style="margin-left:10px">협조 ${esc(v.cooperation_set)}</span><span class="small muted" style="margin-left:10px">보증 <b>${esc(v.established_assurance)}</b></span></p>
      ${codesHtml(v.discrepancies || [])}
      ${equationTableHtml(v.equations || {})}
      <ul class="tight small muted">${(v.notes || []).map((n: string) => `<li>${esc(n)}</li>`).join('')}</ul></div>` : ''}
    ${record.t_error && !v ? `<p class="field-help">T 판정 미확인: ${esc(record.t_error)}</p>` : ''}
    <details><summary>집행 기록 · 수용된 응답 포함</summary><pre>${esc(JSON.stringify(record, null, 2))}</pre></details>`;
}

/** 이전 화면 호환: 본문과 근거를 한 덩어리로. */
export function resultHtml(record: Data): string { return bodyHtml(record) + detailHtml(record); }

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
