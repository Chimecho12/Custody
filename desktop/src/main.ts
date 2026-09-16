import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import './style.css';
import { Data, esc, Playback, installConsoleInteractions } from './console';
import { ReportView } from './report';
import { previewCall } from './preview';
import { STATE_NAMES, MapMode, routeCard, idleRouteHtml, resultHtml, timelineHtml } from './runtime-view';
import { renderAudit } from './audit-view';
import { mountFlow } from './flow';
import { mountTrace } from './trace';
import { StandardsView } from './standards-view';
import { KeysView } from './keys-view';

const get = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
function el(tag: string, className = '', text?: string): HTMLElement {
  const item = document.createElement(tag);
  item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}
let connection: Data | null = null;
let selected: Data | null = null;
let liveEvents: Data[] = [];
let activeToken = '';
let busy = false;
let mapMode: MapMode = 'checks';
const native = '__TAURI_INTERNALS__' in window;
const titles: Record<string, string> = {request: '요청과 보호', history: '사건 기록', audit: '제3자 검증', simulation: '참조 시나리오', settings: '연결 설정', deployment: '배포와 키', evidence: '감사 자료', standards: '표준 적합성', keys: '키 · 신뢰 기준점'};

// 동봉된 Agent 는 별도로 패키징되는 exe 라서 앱보다 오래된 빌드일 수 있다. 그러면
// 화면은 멀쩡한데 명령만 거부당하고, 메시지만으로는 원인을 알 수 없다. status 가
// 알려 준 명령 목록으로 부르기 전에 걸러 낸다.
const REBUILD_HINT = 'scripts/dev-desktop.ps1 -RebuildAgent 로 사이드카를 다시 패키징하세요.';
let agentOperations: string[] | null = null;

function staleAgent(operation: string): string | null {
  if (!native || !agentOperations) return null;
  if (agentOperations.includes(operation)) return null;
  return `동봉된 Agent 가 '${operation}' 을 모릅니다. 앱보다 오래된 빌드입니다 — ${REBUILD_HINT}`;
}

async function call<T = Data>(operation: string, args: Data = {}): Promise<T> {
  const stale = staleAgent(operation);
  if (stale) throw new Error(stale);
  if (!native) return previewCall(operation, args);
  try {
    return await invoke<T>('dispatch', {operation, args});
  } catch (error) {
    // 목록을 아직 못 받았거나(구 Agent 는 이 필드를 내지 않는다) Rust 쪽에서 막힌 경우.
    const text = String(error);
    if (text.includes('모릅니다') || text.includes('허용되지 않은 명령')
        || text.includes('Unsupported Agent operation')) {
      throw new Error(`${text} (${REBUILD_HINT})`);
    }
    throw error;
  }
}
function notice(message: string, error = false) {
  const target = get('notice');
  target.hidden = false; target.classList.toggle('error', error);
  get('notice-text').textContent = message;
}
get('notice').title = '클릭하면 닫힙니다';
get('notice').onclick = () => { get('notice').hidden = true; };
// 등식 ↔ 표 연동 하이라이트와 해시 복사는 문서 전역에서 한 번만 건다.
installConsoleInteractions();
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
  for (const id of ['connect', 'use-lab', 'lab-t']) get<HTMLButtonElement>(id).disabled = value;
}

// ---------- 테마: 시스템 → 밝게 → 어둡게 ----------
const THEME_LABEL: Record<string, string> = {auto: '◐ 시스템', light: '○ 밝게', dark: '● 어둡게'};
function applyTheme(theme: string) {
  if (theme === 'auto') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = theme;
  get('theme').textContent = THEME_LABEL[theme] || THEME_LABEL.auto;
  try { localStorage.setItem('itx-theme', theme); } catch { /* 저장 불가 환경에서는 세션 동안만 유지 */ }
}
get('theme').onclick = () => {
  const order = ['auto', 'light', 'dark'];
  const current = document.documentElement.dataset.theme || 'auto';
  applyTheme(order[(order.indexOf(current) + 1) % order.length]);
};
try { applyTheme(localStorage.getItem('itx-theme') || 'auto'); } catch { applyTheme('auto'); }

// ---------- 화면 전환: 본문만 바뀌고 스크롤은 항상 맨 위로 ----------
const report = new ReportView(get('view-simulation'), call, fail);
const standards = new StandardsView(get('view-standards'), call, fail);
const keys = new KeysView(get('view-keys'), call, fail);
async function showView(name: string) {
  for (const node of document.querySelectorAll<HTMLElement>('.view')) node.hidden = node.id !== 'view-' + name;
  for (const node of document.querySelectorAll<HTMLButtonElement>('nav button')) node.classList.toggle('selected', node.dataset.view === name);
  get('breadcrumb').textContent = '워크스페이스 / ' + titles[name];
  window.scrollTo({top: 0, behavior: 'auto'});
  if (name === 'history') await loadHistory();
  if (name === 'settings') await updateStatus();
  if (name === 'simulation') await report.show();
  if (name === 'standards') await standards.show(selected?.sub ?? '');
  if (name === 'keys') await keys.show();
}
for (const b of document.querySelectorAll<HTMLButtonElement>('nav button')) b.onclick = () => { showView(b.dataset.view!).catch(fail); };

// ---------- 요청과 보호 ----------
const requestPlay = new Playback(get('view-request'), 'req');
get('route-map').addEventListener('click', e => {
  const b = (e.target as HTMLElement).closest<HTMLElement>('button[data-map]');
  if (!b) return;
  mapMode = b.dataset.map as MapMode; renderRoute();
});
function renderRoute() {
  const root = get('route-map');
  const card = selected ? routeCard(selected, connection, mapMode) : idleRouteHtml(connection);
  root.innerHTML = card.html;
  mountFlow(root, card.flow, requestPlay); // 캔버스(줌·팬·미니맵·상태 머신)를 붙인 뒤 재생 상태를 넣는다
  if (card.trace) mountTrace(root, card.trace, requestPlay); // 배너·파이프라인·인스펙터가 같은 시계를 본다
  requestPlay.set(card.ctx);
}
function renderTimeline(record: Data | null) { get('timeline').innerHTML = timelineHtml(record); }
function renderConnection(data: Data) {
  connection = data;
  // 구 Agent 는 이 필드를 내지 않는다. 그때는 null 로 두어 사전 차단을 하지 않고,
  // 호출이 실패하면 call() 이 재패키징 안내를 붙인다.
  agentOperations = Array.isArray(data.operations) ? data.operations as string[] : null;
  const isLab = data.source === 'network_lab';
  get('source').textContent = isLab ? 'TLS 실험실 · 단일 운영자' : '연결 모드 · evaluation';
  get('source').className = 'badge';
  get('agent-status').textContent = native ? 'U Agent 연결됨' : 'UI 미리보기 · 표본 데이터';
  get('agent-dot').className = 'live-dot' + (native ? '' : ' warn');
  get<HTMLButtonElement>('run-witness').disabled = !data.witness_configured;
  const policyOk = Date.now() < data.policy_expires_at;
  get('policy-state').textContent = policyOk ? '로컬 정책 유효' : '정책 만료';
  get('policy-state').className = 'badge ' + (policyOk ? 'green' : 'red');
  const scenario = get<HTMLSelectElement>('scenario'); scenario.disabled = !isLab;
  if (!isLab) scenario.value = 'normal';
  const labT = get<HTMLButtonElement>('lab-t');
  if (data.services && native) {
    const running = data.services.T.running;
    labT.hidden = false; labT.textContent = running ? '실험: T 중단' : 'T 복구';
    labT.onclick = async () => {
      try { renderConnection(await call(running ? 'stop_t' : 'start_t')); notice(running ? 'T를 중단했습니다. protect와 strict의 동작을 비교할 수 있습니다.' : 'T를 복구했습니다. 대기 증거가 자동으로 재제출됩니다.'); }
      catch (e) { fail(e); }
    };
  } else labT.hidden = true;
  const target = get('connection-details'); target.replaceChildren(el('h2', '', '현재 연결과 신뢰 기준'));
  const rows: [string, string][] = [['환경', data.source], ['모델', data.model_id + ' / ' + data.model_kind], ['운영 주체', data.governance], ['대기 증거', String(data.pending_evidence) + '건'], ['정책 만료', new Date(data.policy_expires_at).toLocaleString('ko-KR')], ['정책 해시', data.policy_hash], ['설정 파일', data.config_path]];
  for (const r of ['R', 'M', 'T']) rows.push([r + ' TLS 주소', data.endpoints[r]]);
  for (const r of ['U', 'R', 'M', 'T']) rows.push([r + ' 고정 공개키', data.identities[r].public_key]);
  if (data.witness_configured) rows.push(['W 고정 공개키', data.identities.W.public_key], ['W TLS 주소', data.endpoints.W]);
  if (data.deployment_hash) rows.push(['배포 지문', data.deployment_hash], ['정책 세대', String(data.epoch)]);
  for (const [key, value] of rows) {
    const row = el('div', 'detail-row'), code = el('code', 'copyable', value) as HTMLElement;
    // 공개키·해시·경로는 눈으로 옮겨 적는 값이 아니다. 누르면 전체 값이 복사된다.
    code.dataset.copy = value; code.tabIndex = 0; code.title = '클릭하면 전체 값을 복사합니다';
    row.append(el('span', '', key), code); target.append(row);
  }
  if (data.deployment_history?.length) target.append(details('서명으로 연결된 배포·체크포인트 이력', data.deployment_history));
  renderRoute();
  setBusy(busy);
}
async function updateStatus() { try { renderConnection(await call('status')); } catch (e) { fail(e); } }
function renderResult(record: Data) {
  selected = record;
  const result = get('result'); result.innerHTML = resultHtml(record);
  get('request-state').className = 'badge ' + color(record.state); get('request-state').textContent = STATE_NAMES[record.state] || record.state;
  result.querySelector<HTMLButtonElement>('button[data-refresh]')!.onclick = async () => {
    const sub = record.sub;
    try { const fresh = await call('refresh', {sub}); if (selected?.sub === sub) renderResult(fresh); notice('T 판정을 갱신했습니다. 기존 집행 결과는 바뀌지 않습니다.'); } catch (e) { fail(e); }
  };
  renderTimeline(record);
  renderRoute();
}
get<HTMLSelectElement>('mode').onchange = () => {
  const mode = get<HTMLSelectElement>('mode').value;
  get('mode-help').textContent = mode === 'protect' ? 'T가 연결되지 않아도 필수 로컬 증거와 유효한 정책이 있으면 계속합니다.' : mode === 'strict' ? '로컬 검사와 유효한 T 판정을 모두 요구합니다. T 장애 시 기한 후 거부합니다.' : '검증 실패 응답도 공개합니다. 공격을 관측하기 위한 대조군이며 방어 모드가 아닙니다.';
};
get<HTMLFormElement>('request-form').onsubmit = async event => {
  event.preventDefault();
  if (busy) return;
  activeToken = crypto.randomUUID();
  setBusy(true); get('notice').hidden = true; liveEvents = []; renderTimeline(null);
  get('result').innerHTML = `<div class="busybar"></div><div class="empty"><div class="empty-glyph">◇</div><h3>응답을 보류하고 검증합니다</h3><p>서명·요청·응답 결합을 확인하기 전에는 원문을 공개하지 않습니다.</p></div>`;
  get('request-state').textContent = '진행 중'; get('request-state').className = 'badge amber';
  try {
    const record = await call('request', {token: activeToken, prompt: get<HTMLTextAreaElement>('prompt').value, mode: get<HTMLSelectElement>('mode').value, scenario: get<HTMLSelectElement>('scenario').value});
    renderResult(record);
    if (record.state !== 'error' && record.state !== 'cancelled' && !record.t_verdict) {
      setTimeout(async () => { try { const fresh = await call('refresh', {sub: record.sub}); if (!busy && selected?.sub === record.sub) renderResult(fresh); } catch { /* T 장애는 명시적 대기 상태로 남긴다 */ } }, 900);
    }
  } catch (e) { fail(e); get('result').innerHTML = '<div class="blocked-box">요청을 완료하지 못했습니다. Agent 상태를 확인하세요.</div>'; }
  finally { activeToken = ''; setBusy(false); await updateStatus(); }
};
// 요청 내용은 여러 줄이므로 Enter 는 줄바꿈으로 두고, 실행은 Ctrl/⌘+Enter 로 받는다.
get<HTMLTextAreaElement>('prompt').addEventListener('keydown', event => {
  if (event.key !== 'Enter' || !(event.ctrlKey || event.metaKey)) return;
  event.preventDefault();
  if (!busy && connection) get<HTMLFormElement>('request-form').requestSubmit();
});
get('cancel').onclick = async () => { try { await call('cancel', {token: activeToken}); notice('취소를 요청했습니다. 원격 호출의 완료 여부와 별개로, 취소가 처리되면 응답을 공개하지 않습니다.'); } catch (e) { fail(e); } };

// ---------- 사건 기록 ----------
async function loadHistory() {
  const target = get('history-content');
  try {
    const records = await call<Data[]>('history'); target.replaceChildren();
    if (!records.length) { target.append(el('div', 'empty', '저장된 요청이 없습니다.')); return; }
    const wrap = el('div', 'table-wrap'), table = el('table', 'history-table'), head = el('tr');
    for (const title of ['요청 시각', '요청 ID', '정책', '실험 조건', '집행', 'T 판정', '소요 시간', '']) head.append(el('th', '', title)); table.append(head);
    for (const record of records) {
      const row = el('tr');
      row.append(el('td', '', new Date(record.started_at).toLocaleString('ko-KR')), el('td', 'mono', record.sub.slice(-10)), el('td', 'mono', record.mode), el('td', 'small', record.lab_scenario || '—'));
      const state = el('td'); state.append(badge(STATE_NAMES[record.state] || record.state, color(record.state))); row.append(state);
      const v = record.t_verdict?.payload; const tv = el('td'); tv.append(badge(v ? v.verification_status : '대기', v ? (v.verification_status === 'passed' ? 'green' : 'red') : '')); row.append(tv);
      row.append(el('td', 'mono', `${record.elapsed_ms ?? '—'} ms`));
      const action = el('td'); action.append(button('조사', () => { showView('request').catch(fail); renderResult(record); })); row.append(action); table.append(row);
    }
    wrap.append(table); target.append(wrap);
  } catch (e) { fail(e); }
}
get('reload-history').onclick = () => { loadHistory().catch(fail); };

// ---------- 제3자 검증 ----------
get('run-audit').onclick = async () => {
  const b = get<HTMLButtonElement>('run-audit'); b.disabled = true;
  try {
    // 트리 헤드·앵커·판정 대조 다이어그램과, 그 근거가 되는 JSON 을 양방향으로 연동해 보인다 (audit-view.ts).
    renderAudit(get('audit-content'), await call('audit'));
  } catch (e) { fail(e); } finally { b.disabled = false; }
};
get('export').onclick = async () => { try { const result = await call('export'); notice('수용된 응답과 판정 기록을 저장했습니다: ' + result.path); } catch (e) { fail(e); } };
get('connect').onclick = async () => { try { renderConnection(await call('connect', {path: get<HTMLInputElement>('config-path').value})); selected = null; renderRoute(); renderTimeline(null); notice('선택한 신뢰 설정으로 연결했습니다. 새 요청부터 적용됩니다.'); } catch (e) { fail(e); } };
get('use-lab').onclick = async () => { try { renderConnection(await call('lab')); notice('로컬 TLS 실험실로 전환했습니다.'); } catch (e) { fail(e); } };

// ---------- 배포·감사 작업 ----------
const input = (id: string) => get<HTMLInputElement>(id).value.trim();
const lines = (id: string) => input(id).split(/\r?\n/).map(s => s.trim()).filter(Boolean);
let retentionToken = '';
function action(id: string, operation: string, args: () => Data = () => ({}), target = 'evidence-output', after?: (result: Data) => void) {
  get(id).onclick = async () => {
    if (busy) { notice('진행 요청이 끝난 뒤 실행하세요.'); return; }
    const b = get<HTMLButtonElement>(id); b.disabled = true;
    try {
      const result = await call(operation, args());
      const output = get(target); output.replaceChildren();
      if ('ok' in result) output.append(badge(result.ok ? (result.private_scope === 'partial' ? '공개 검사 일치 · 비공개 미검증' : '검사 일치') : '불일치 또는 미완료', result.ok ? 'green' : 'red'));
      if (result.path) output.append(el('p', '', '저장 경로: ' + result.path));
      if (result.fingerprint) output.append(el('p', 'mono', 'SHA-256 지문: ' + result.fingerprint));
      output.append(pretty(result));
      after?.(result);
      notice('작업 결과와 저장 경로를 확인하세요.');
    } catch (e) { fail(e); } finally { b.disabled = id === 'retention-apply' && !retentionToken; }
  };
}
action('prepare-operator', 'enroll_prepare', () => ({role: input('operator-role'), endpoint: input('operator-endpoint')}), 'deployment-output', r => {
  get<HTMLInputElement>('endorse-operator').value = r.directory; get<HTMLInputElement>('activate-operator').value = r.directory;
});
action('propose-deployment', 'enroll_propose', () => ({card_paths: lines('deployment-cards'), previous_bundle: input('deployment-previous'), checkpoint: input('deployment-checkpoint'), model_kind: input('deployment-model-kind'), model_id: input('deployment-model-id'), model_hash: input('deployment-model-hash'), model_name: input('deployment-model-name'), pre_exec: get<HTMLInputElement>('deployment-pre-exec').checked}), 'deployment-output', r => {
  get<HTMLInputElement>('endorse-proposal').value = r.path; get<HTMLInputElement>('assemble-proposal').value = r.path;
});
action('endorse-deployment', 'enroll_endorse', () => ({operator_directory: input('endorse-operator'), proposal: input('endorse-proposal'), fingerprint: input('endorse-fingerprint'), previous_config: input('endorse-previous')}), 'deployment-output');
action('assemble-deployment', 'enroll_assemble', () => ({proposal: input('assemble-proposal'), endorsement_paths: lines('assemble-endorsements'), previous_bundle: input('assemble-previous')}), 'deployment-output', r => { get<HTMLInputElement>('activate-bundle').value = r.path; });
action('inspect-deployment', 'enroll_inspect', () => ({bundle: input('activate-bundle')}), 'deployment-output');
action('activate-deployment', 'enroll_activate', () => ({operator_directory: input('activate-operator'), bundle: input('activate-bundle'), fingerprint: input('activate-fingerprint'), bind: input('activate-bind'), model_endpoint: input('activate-model-endpoint'), previous_config: input('activate-previous')}), 'deployment-output', r => { get<HTMLInputElement>('config-path').value = r.config_path; });
action('preflight', 'preflight');
action('run-witness', 'witness');
action('export-checkpoint', 'export_checkpoint');
action('export-trust', 'export_trust');
action('export-public', 'export_evidence');
action('create-recipient', 'recipient_create');
action('export-encrypted', 'export_evidence', () => { if (!input('recipient-path') || !input('recipient-fingerprint')) throw new Error('감사자 공개키 파일과 별도 확인한 지문이 필요합니다.'); return {recipient_path: input('recipient-path'), recipient_fingerprint: input('recipient-fingerprint')}; });
action('verify-evidence', 'audit_verify', () => ({package: input('verify-package'), trust: input('verify-trust'), fingerprint: input('verify-fingerprint'), recipient_directory: input('verify-recipient')}));
action('retention-preview', 'retention_preview', () => ({}), 'evidence-output', r => {
  retentionToken = r.token; get('retention-description').textContent = `${r.retention_days}일 경과 ${r.count}건 · 제출 대기로 제외 ${r.withheld_pending}건. ${r.effect}`;
  get<HTMLButtonElement>('retention-apply').disabled = !r.count;
});
action('retention-apply', 'retention_apply', () => ({token: retentionToken}), 'evidence-output', () => { retentionToken = ''; get('retention-description').textContent = '정리를 적용했습니다. 추가 정리 전 미리보기를 다시 실행하세요.'; });

// ---------- 시작 ----------
async function boot() {
  renderRoute(); renderTimeline(null);
  if (!native) {
    get('agent-status').textContent = '데스크톱 연결 없음'; get('source').textContent = 'UI 미리보기';
    notice('브라우저 미리보기입니다. 표본 데이터로 화면만 확인하며, 실제 실행은 itx 설치형 앱에서 합니다.');
    await updateStatus();
    return;
  }
  await listen<Data>('agent-progress', e => { if (e.payload.token === activeToken) { liveEvents.push(e.payload); renderTimeline({timeline: liveEvents}); } });
  await listen<string>('agent-failure', e => { connection = null; setBusy(false); get('agent-status').textContent = 'Agent 연결 종료'; get('agent-dot').className = 'live-dot off'; fail(e.payload); });
  await updateStatus();
}
boot().catch(fail);
