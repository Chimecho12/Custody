import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import './style.css';

type Data = Record<string, any>;
const get = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
function el(tag: string, className = '', text?: string): HTMLElement {
  const item = document.createElement(tag);
  item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}
let connection: Data | null = null;
let selected: Data | null = null;
let activeToken = '';
let busy = false;
let view = 'request';
const native = '__TAURI_INTERNALS__' in window;
const titles: Record<string, string> = {request: '요청과 보호', history: '사건 기록', audit: '제3자 검증', simulation: '참조 시나리오', settings: '연결 설정', deployment:'배포와 키', evidence:'감사 자료'};
const stateNames: Record<string, string> = {accept: '검증 후 수용', accept_unverified: '미검증 수용', quarantine: '응답 격리', reject: '수용 거부', reject_timeout: 'T 판정 기한 초과', cancelled: '취소 · 미공개', interrupted: '종료로 중단 · 미공개', pending: '진행 중', error: '요청 오류'};
const checkNames: Record<string, string> = {M_authority: 'M 발행자·역할 인증', R_authority: 'R 발행자·역할 인증', not_expired: '계약 유효기간', receipt_present: '모델 영수증', receipt_signature: '영수증 서명', nonce_match: 'nonce 결합', request_binding: '승인된 요청 결합', response_binding: '종단 응답 결합', attempt_match: '시도 ID 결합', model_hash_reference: '등록 기준 해시', route_allowed: '허용 모델 경로', tool_policy: '도구 실행 정책'};
async function call<T = Data>(operation: string, args: Data = {}): Promise<T> {
  if (!native) throw new Error('이 화면은 Tauri 앱에서 실행해야 Agent에 연결됩니다.');
  return invoke<T>('dispatch', {operation, args});
}
function notice(message: string, error = false) {
  const target = get('notice'); target.hidden = false; target.classList.toggle('error', error); target.textContent = message;
}
function fail(error: unknown) { notice(String(error instanceof Error ? error.message : error), true); }
function badge(text: string, tone = '') { return el('span', 'badge ' + tone, text); }
function color(state: string) { return state === 'accept' ? 'green' : ['quarantine', 'reject', 'reject_timeout', 'error'].includes(state) ? 'red' : 'amber'; }
function pretty(value: unknown) { const pre = el('pre'); pre.textContent = JSON.stringify(value, null, 2); return pre; }
function details(label: string, value: unknown) { const item = el('details'); item.append(el('summary', '', label), pretty(value)); return item; }
function button(text: string, action: () => void, className = '') {
  const b = el('button', className, text) as HTMLButtonElement; b.type = 'button'; b.onclick = action; return b;
}
function setBusy(value: boolean) {
  busy = value;
  get<HTMLButtonElement>('send').disabled = value || !connection;
  get<HTMLButtonElement>('cancel').disabled = !value;
  get<HTMLButtonElement>('send').textContent = value ? '검증 진행 중…' : '요청 실행 ↗';
  for (const id of ['connect', 'use-lab', 'run-sim']) get<HTMLButtonElement>(id).disabled = value;
  for (const b of get('topology').querySelectorAll('button')) b.disabled = value;
}
async function showView(name: string) {
  view = name;
  for (const node of document.querySelectorAll<HTMLElement>('.view')) node.hidden = node.id !== 'view-' + name;
  for (const node of document.querySelectorAll<HTMLButtonElement>('nav button')) node.classList.toggle('selected', node.dataset.view === name);
  get('breadcrumb').textContent = '워크스페이스 / ' + titles[name];
  if (name === 'history') await loadHistory();
  if (name === 'settings') await updateStatus();
}
for (const b of document.querySelectorAll<HTMLButtonElement>('nav button')) b.onclick = () => {showView(b.dataset.view!).catch(fail);};

function renderConnection(data: Data) {
  connection = data;
  const isLab = data.source === 'network_lab';
  get('source').textContent = isLab ? 'TLS 실험실 · 단일 운영자' : '연결 모드 · evaluation';
  get('agent-status').textContent = 'U Agent 연결됨';
  get<HTMLButtonElement>('run-witness').disabled = !data.witness_configured;
  get('policy-state').textContent = Date.now() < data.policy_expires_at ? '로컬 정책 유효' : '정책 만료';
  get('policy-state').className = 'badge ' + (Date.now() < data.policy_expires_at ? 'green' : 'red');
  const scenario = get<HTMLSelectElement>('scenario'); scenario.disabled = !isLab;
  if (!isLab) scenario.value = 'normal';
  const topology = get('topology'); topology.replaceChildren();
  for (const [role, title, subtitle] of [['U', '사용자', '전송 · 수용 게이트'], ['R', '중개자', '승인된 업무 경로'], ['M', '모델 운영자', data.model_kind === 'deterministic_mock' ? '결정적 모형 모델' : '실제 모델 어댑터'], ['T', '독립 검증 역할', '증거 대조 · 판정']]) {
    if (role !== 'U' && role !== 'T') topology.append(el('span', 'arrow', '⇄'));
    const n = el('div', 'node' + (role === 'T' ? ' node-t' : ''));
    n.append(el('span', 'node-letter', role));
    const text = el('div'); text.append(el('strong', '', title), el('small', '', subtitle));
    if (role === 'T' && data.services) {
      const running = data.services.T.running;
      text.append(button(running ? '실험: T 중단' : 'T 복구', async () => {
        try { renderConnection(await call(running ? 'stop_t' : 'start_t')); notice(running ? 'T를 중단했습니다. protect와 strict의 동작을 비교할 수 있습니다.' : 'T를 복구했습니다. 대기 증거가 자동으로 재제출됩니다.'); }
        catch (e) {fail(e);}
      }));
    }
    n.append(text); topology.append(n);
  }
  const target = get('connection-details'); target.replaceChildren(el('h2', '', '현재 연결과 신뢰 기준'));
  const rows: [string, string][] = [['환경', data.source], ['모델', data.model_id + ' / ' + data.model_kind], ['운영 주체', data.governance], ['대기 증거', String(data.pending_evidence) + '건'], ['정책 만료', new Date(data.policy_expires_at).toLocaleString('ko-KR')], ['정책 해시', data.policy_hash], ['설정 파일', data.config_path]];
  for (const r of ['R','M','T']) rows.push([r + ' TLS 주소', data.endpoints[r]]);
  for (const r of ['U','R','M','T']) rows.push([r + ' 고정 공개키', data.identities[r].public_key]);
  if (data.witness_configured) rows.push(['W 고정 공개키', data.identities.W.public_key], ['W TLS 주소', data.endpoints.W]);
  if (data.deployment_hash) rows.push(['배포 지문', data.deployment_hash], ['정책 세대', String(data.epoch)]);
  for (const [key, value] of rows) { const row = el('div', 'detail-row'); row.append(el('span','',key), el('code','',value)); target.append(row); }
  if (data.deployment_history?.length) target.append(details('서명으로 연결된 배포·체크포인트 이력', data.deployment_history));
  setBusy(busy);
}
async function updateStatus() { try {renderConnection(await call('status'));} catch (e) {fail(e);} }
function addEvent(event: Data) {
  const li = el('li'); li.append(el('time','',`${event.t_ms} ms · ${event.actor}`), el('span','',event.kind)); get('events').append(li);
}
function checksTable(checks: Data) {
  const table = el('table','checks');
  const head = el('tr'); for (const title of ['검사 항목','결과','근거']) head.append(el('th','',title)); table.append(head);
  for (const [key, value] of Object.entries(checks)) {
    const row = el('tr'); row.append(el('td','',checkNames[key] || value.title || key), el('td',value.result === 'pass' ? 'good' : value.result === 'fail' ? 'bad' : 'muted',value.result === 'pass' ? '일치' : value.result === 'fail' ? '실패' : '미확인'), el('td','muted',value.reason)); table.append(row);
  }
  return table;
}
function renderResult(record: Data) {
  selected = record;
  const result = get('result'); result.replaceChildren();
  const heading = el('div','result-head'); heading.append(el('h3','',stateNames[record.state] || record.state), el('span','muted',`${record.elapsed_ms ?? '—'} ms · 실측`)); result.append(heading);
  get('request-state').className = 'badge ' + color(record.state); get('request-state').textContent = stateNames[record.state] || record.state;
  if (record.content_pruned_at) result.append(el('div','empty','보관 정책에 따라 본문이 삭제됐습니다. 당시의 집행 결과와 서명 증거는 유지됩니다.'));
  else if (record.response != null) result.append(el('div','response-box',record.response));
  else result.append(el('div','blocked-box',record.error || '응답이 공개되지 않았습니다. 원문을 화면·업무 소비자에 전달하지 않습니다.'));
  if (record.gate?.reasons) result.append(el('p','field-help',record.gate.reasons.join(' · ')));
  result.append(checksTable(record.checks || {}));
  const v = record.t_verdict?.payload;
  const actions = el('div','result-actions'); actions.append(button('T 사후 판정 갱신', async () => {
    const sub = record.sub;
    try {const fresh = await call('refresh',{sub}); if (selected?.sub === sub) renderResult(fresh); notice('T 판정을 갱신했습니다. 기존 집행 결과는 바뀌지 않습니다.');} catch (e) {fail(e);}
  }), badge(v ? 'T: ' + v.verification_status : 'T: 사후 판정 대기', v ? (v.verification_status === 'passed' ? 'green' : 'red') : 'amber'));
  result.append(actions);
  if (v) {const d = el('details'); d.append(el('summary','','등식 E1~E12와 증거 범위'), checksTable(v.equations), pretty({completeness:v.completeness, cooperation:v.cooperation_set, discrepancies:v.discrepancies})); result.append(d);}
  if (record.t_error && !v) result.append(el('p','field-help','T 판정 미확인: ' + record.t_error));
  result.append(details('집행 기록 · 수용된 응답 포함', record));
  get('events').replaceChildren(); for (const item of record.timeline || []) addEvent(item);
}
get<HTMLSelectElement>('mode').onchange = () => {
  const mode = get<HTMLSelectElement>('mode').value;
  get('mode-help').textContent = mode === 'protect' ? 'T가 연결되지 않아도 필수 로컬 증거와 유효한 정책이 있으면 계속합니다.' : mode === 'strict' ? '로컬 검사와 유효한 T 판정을 모두 요구합니다. T 장애 시 기한 후 거부합니다.' : '검증 실패 응답도 공개합니다. 공격을 관측하기 위한 대조군이며 방어 모드가 아닙니다.';
};
get<HTMLFormElement>('request-form').onsubmit = async event => {
  event.preventDefault();
  if (busy) return;
  activeToken = crypto.randomUUID();
  setBusy(true); get('notice').hidden = true; get('events').replaceChildren(); get('result').replaceChildren(el('div','empty','응답을 보류하고 검증합니다…'));
  get('request-state').textContent = '진행 중'; get('request-state').className = 'badge amber';
  try {
    const record = await call('request',{token:activeToken,prompt:get<HTMLTextAreaElement>('prompt').value,mode:get<HTMLSelectElement>('mode').value,scenario:get<HTMLSelectElement>('scenario').value});
    renderResult(record);
    if (record.state !== 'error' && record.state !== 'cancelled' && !record.t_verdict) {
      setTimeout(async () => {try {const fresh = await call('refresh',{sub:record.sub}); if (!busy && selected?.sub === record.sub) renderResult(fresh);} catch { /* T outage remains explicit pending state. */ }}, 900);
    }
  } catch (e) {fail(e); get('result').replaceChildren(el('div','blocked-box','요청을 완료하지 못했습니다. Agent 상태를 확인하세요.'));}
  finally {activeToken = ''; setBusy(false); await updateStatus();}
};
get('cancel').onclick = async () => {try {await call('cancel',{token:activeToken}); notice('취소를 요청했습니다. 원격 호출의 완료 여부와 별개로, 취소가 처리되면 응답을 공개하지 않습니다.');} catch (e) {fail(e);}};

async function loadHistory() {
  const target = get('history-content');
  try {
    const records = await call<Data[]>('history'); target.replaceChildren();
    if (!records.length) {target.append(el('div','empty','저장된 요청이 없습니다.')); return;}
    const wrap = el('div','table-wrap'), table = el('table','history-table'), head = el('tr');
    for (const title of ['요청 시각','요청 ID','정책','집행','소요 시간','']) head.append(el('th','',title)); table.append(head);
    for (const record of records) { const row = el('tr'); row.append(el('td','',new Date(record.started_at).toLocaleString('ko-KR')), el('td','',record.sub.slice(-10)),el('td','',record.mode)); const state = el('td'); state.append(badge(stateNames[record.state] || record.state,color(record.state))); row.append(state,el('td','',`${record.elapsed_ms ?? '—'} ms`)); const action = el('td'); action.append(button('조사',()=>{showView('request').catch(fail);renderResult(record);})); row.append(action); table.append(row); }
    wrap.append(table); target.append(wrap);
  } catch (e) {fail(e);}
}
get('reload-history').onclick = () => {loadHistory().catch(fail);};
get('run-audit').onclick = async () => {
  const b = get<HTMLButtonElement>('run-audit'); b.disabled = true;
  try {
    const a = await call('audit'), target = get('audit-content'); target.replaceChildren();
    target.append(badge(a.ok ? (a.private_scope === 'partial' ? '공개 검사 일치 · 비공개 일부 미검증' : '모든 과거 판정 감사 일치') : '불일치 또는 미완료 증거 발견',a.ok ? 'green' : 'red'));
    const stats = el('div','stat-row');
    for (const [label,value] of [['T 신원·정책','고정 기준 확인'],['과거 판정 전수 검사',String(a.verdict_count) + '건'],['불일치 요청',String(a.verdict_mismatches.length) + '건']]) {const d = el('div');d.append(el('small','',label),el('strong','',value));stats.append(d);} target.append(stats);
    target.append(el('p','field-help',a.previous_checkpoint ? '이전에 사용자 PC에 보관한 체크포인트와 비교했습니다.' : '첫 체크포인트입니다. 다음 감사부터 이전 이력과 비교합니다.'));
    target.append(details('트리·앵커·판정 검증 상세',a));
  } catch (e) {fail(e);} finally {b.disabled = false;}
};
get('export').onclick = async () => {try {const result = await call('export'); notice('수용된 응답과 판정 기록을 저장했습니다: ' + result.path);} catch (e) {fail(e);}};
get('connect').onclick = async () => {try {renderConnection(await call('connect',{path:get<HTMLInputElement>('config-path').value})); selected = null; notice('선택한 신뢰 설정으로 연결했습니다. 새 요청부터 적용됩니다.');} catch (e) {fail(e);}};
get('use-lab').onclick = async () => {try {renderConnection(await call('lab')); notice('로컬 TLS 실험실로 전환했습니다.');} catch (e) {fail(e);}};
const scenarios = ['정상 · 셋 협조','R 요청 변경','R 응답 변경','승인된 폴백','일방 폴백','숨은 폴백','정상 재시도','과거 응답 재사용','R 비협조','T 정지','T 지연','큐 포화','T 오판','T 기록 재작성','R+M 공모 · 탐지 한계','프롬프트 인젝션 · 도구 정책','M 실행 전 검사'];
scenarios.forEach((name,i)=>{const o = document.createElement('option');o.value = 'S' + String(i+1).padStart(2,'0');o.textContent = o.value + ' · ' + name;get('sim-scenario').append(o);});
get('run-sim').onclick = async () => {
  const b = get<HTMLButtonElement>('run-sim'); b.disabled = true;
  try {const r = await call('simulation',{scenario:get<HTMLSelectElement>('sim-scenario').value,mode:get<HTMLSelectElement>('sim-mode').value}); const target=get('sim-content');target.className='';target.replaceChildren(badge('mock_result · 모의 시계와 모형 모델','amber'));
    const a = r.attempts.at(-1); target.append(el('h3','',r.scenario.title),el('p','',`${stateNames[a.gate.action]} · 판정 ${a.final_verdict.verification_status} · 감사 ${r.audit.ok ? '일치' : '불일치 발견'}`),checksTable(a.final_verdict.equations),details('전체 시나리오 근거',r));
  } catch (e) {fail(e);} finally {b.disabled=false;}
};
async function boot() {
  if (!native) {get('agent-status').textContent='데스크톱 연결 없음'; get('source').textContent='UI 미리보기 · 실행 불가'; notice('브라우저 미리보기입니다. 실제 실행은 itx 설치형 앱에서 사용할 수 있습니다.'); return;}
  await listen<Data>('agent-progress', e => {if (e.payload.token === activeToken) addEvent(e.payload);});
  await listen<string>('agent-failure', e => {connection=null;setBusy(false);get('agent-status').textContent='Agent 연결 종료';fail(e.payload);});
  await updateStatus();
}
boot().catch(fail);

const input = (id:string) => get<HTMLInputElement>(id).value.trim();
const lines = (id:string) => input(id).split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
function action(id:string, operation:string, args:()=>Data = ()=>({}), target='evidence-output', after?:(result:Data)=>void) {
  get(id).onclick = async () => {
    if (busy) {notice('진행 요청이 끝난 뒤 실행하세요.'); return;}
    const b=get<HTMLButtonElement>(id); b.disabled=true;
    try {
      const result=await call(operation,args());
      const output=get(target); output.replaceChildren();
      if ('ok' in result) output.append(badge(result.ok ? (result.private_scope === 'partial' ? '공개 검사 일치 · 비공개 미검증' : '검사 일치') : '불일치 또는 미완료',result.ok?'green':'red'));
      if (result.path) output.append(el('p','','저장 경로: '+result.path));
      if (result.fingerprint) output.append(el('p','','SHA-256 지문: '+result.fingerprint));
      output.append(pretty(result));
      after?.(result);
      notice('작업 결과와 저장 경로를 확인하세요.');
    } catch(e) {fail(e);} finally {b.disabled=id==='retention-apply' && !retentionToken;}
  };
}
action('prepare-operator','enroll_prepare',()=>({role:input('operator-role'),endpoint:input('operator-endpoint')}),'deployment-output',r=>{
  get<HTMLInputElement>('endorse-operator').value=r.directory; get<HTMLInputElement>('activate-operator').value=r.directory;
});
action('propose-deployment','enroll_propose',()=>({card_paths:lines('deployment-cards'),previous_bundle:input('deployment-previous'),checkpoint:input('deployment-checkpoint'),model_kind:input('deployment-model-kind'),model_id:input('deployment-model-id'),model_hash:input('deployment-model-hash'),model_name:input('deployment-model-name'),pre_exec:get<HTMLInputElement>('deployment-pre-exec').checked}),'deployment-output',r=>{
  get<HTMLInputElement>('endorse-proposal').value=r.path; get<HTMLInputElement>('assemble-proposal').value=r.path;
});
action('endorse-deployment','enroll_endorse',()=>({operator_directory:input('endorse-operator'),proposal:input('endorse-proposal'),fingerprint:input('endorse-fingerprint'),previous_config:input('endorse-previous')}),'deployment-output');
action('assemble-deployment','enroll_assemble',()=>({proposal:input('assemble-proposal'),endorsement_paths:lines('assemble-endorsements'),previous_bundle:input('assemble-previous')}),'deployment-output',r=>{get<HTMLInputElement>('activate-bundle').value=r.path;});
action('inspect-deployment','enroll_inspect',()=>({bundle:input('activate-bundle')}),'deployment-output');
action('activate-deployment','enroll_activate',()=>({operator_directory:input('activate-operator'),bundle:input('activate-bundle'),fingerprint:input('activate-fingerprint'),bind:input('activate-bind'),model_endpoint:input('activate-model-endpoint'),previous_config:input('activate-previous')}),'deployment-output',r=>{get<HTMLInputElement>('config-path').value=r.config_path;});
action('preflight','preflight');
action('run-witness','witness');
action('export-checkpoint','export_checkpoint');
action('export-trust','export_trust');
action('export-public','export_evidence');
action('create-recipient','recipient_create');
action('export-encrypted','export_evidence',()=>{if(!input('recipient-path')||!input('recipient-fingerprint')) throw new Error('감사자 공개키 파일과 별도 확인한 지문이 필요합니다.'); return {recipient_path:input('recipient-path'),recipient_fingerprint:input('recipient-fingerprint')};});
action('verify-evidence','audit_verify',()=>({package:input('verify-package'),trust:input('verify-trust'),fingerprint:input('verify-fingerprint'),recipient_directory:input('verify-recipient')}));
let retentionToken='';
action('retention-preview','retention_preview',()=>({}),'evidence-output',r=>{
  retentionToken=r.token; get('retention-description').textContent=`${r.retention_days}일 경과 ${r.count}건 · 제출 대기로 제외 ${r.withheld_pending}건. ${r.effect}`;
  get<HTMLButtonElement>('retention-apply').disabled=!r.count;
});
action('retention-apply','retention_apply',()=>({token:retentionToken}),'evidence-output',()=>{retentionToken='';get('retention-description').textContent='정리를 적용했습니다. 추가 정리 전 미리보기를 다시 실행하세요.';});
