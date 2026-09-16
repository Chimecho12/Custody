import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import './style.css';
import { Data, esc, Playback, installConsoleInteractions } from './console';
import { ReportView } from './report';
import { previewCall } from './preview';
import { STATE_NAMES, SCENARIO_NAMES, MODES, MapMode, routeCard, idleRouteHtml, summaryHtml, bodyHtml, detailHtml, timelineHtml, verdictOf, releaseLabel } from './runtime-view';
import { renderAudit, auditCardsHtml } from './audit-view';
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
let fromLog: Data | null = null;   // 사건 기록에서 「조사」로 들어온 경우 — 돌아가기 버튼과 제목이 바뀐다
const native = '__TAURI_INTERNALS__' in window;
const titles: Record<string, string> = {request: '요청', history: '사건 기록', audit: '제3자 검증', simulation: '참조 시나리오', settings: '연결', deployment: '배포 설정', evidence: '감사 자료', standards: '표준 적합성', keys: '키 · 신뢰 기준점'};

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
function button(text: string, action: () => void, className = 'v3-btn') {
  const b = el('button', className, text) as HTMLButtonElement; b.type = 'button'; b.onclick = action; return b;
}
function setBusy(value: boolean) {
  busy = value;
  get<HTMLButtonElement>('send').disabled = value || !connection;
  get<HTMLButtonElement>('cancel').disabled = !value;
  get<HTMLButtonElement>('send').textContent = value ? '실행 중…' : '요청 실행 ↗';
  get('run-live').hidden = !value;
  for (const id of ['connect', 'use-lab', 'lab-t']) get<HTMLButtonElement>(id).disabled = value;
}

// ---------- 화면 설명(ⓘ): 모든 화면이 같은 방식으로 연다 ----------
for (const b of document.querySelectorAll<HTMLButtonElement>('[data-guide]')) b.onclick = () => {
  const text = document.querySelector<HTMLElement>(`[data-guide-text="${b.dataset.guide}"]`);
  if (!text) return;
  text.hidden = !text.hidden;
  b.setAttribute('aria-expanded', String(!text.hidden));
  b.classList.toggle('on', !text.hidden);
};

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
  if (name !== 'request') { fromLog = null; get('back-to-log').hidden = true; }
  if (name === 'history') await loadHistory();
  if (name === 'settings') await updateStatus();
  if (name === 'simulation') await report.show();
  if (name === 'standards') await standards.show(selected?.sub ?? '');
  if (name === 'keys') await keys.show();
}
for (const b of document.querySelectorAll<HTMLButtonElement>('nav button')) b.onclick = () => { showView(b.dataset.view!).catch(fail); };
get('back-to-log').onclick = () => { showView('history').catch(fail); };
const setHint = (view: string, text: string) => { const h = document.querySelector<HTMLElement>(`[data-hint="${view}"]`); if (h) h.textContent = text; };

// ---------- 요청 화면 ----------
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

// 경로 상세는 접이식이다. 기본 화면은 결론이고, 경로는 그 근거다 — 결과가 오면 자동으로 펼친다.
function setDetail(open: boolean) {
  get('detail-body').hidden = !open;
  get('detail-toggle').setAttribute('aria-expanded', String(open));
  get('detail-label').textContent = open ? '접기 ▴' : '펼치기 ▾';
}
get('detail-toggle').onclick = () => setDetail(get('detail-body').hidden);
get('summary').addEventListener('click', e => {
  if (!(e.target as HTMLElement).closest('[data-open-detail]')) return;
  setDetail(true);
  get('detail-card').scrollIntoView({behavior: 'smooth', block: 'start'});
});

// 집행 정책은 select 값이 진실이고, 카드는 그 값을 고르는 입력 장치다. 기존 코드와 점검 스크립트가 select 를 읽는다.
function renderModeCards() {
  const sel = get<HTMLSelectElement>('mode');
  get('mode-cards').innerHTML = MODES.map(m => `<button type="button" class="v3-mode-card${sel.value === m.code ? ' on' : ''}" data-mode="${m.code}" role="radio" aria-checked="${sel.value === m.code}">
      <span class="h"><b>${m.title}</b><span class="mono muted">${m.code}</span></span><span class="b">${m.body}</span></button>`).join('');
  get('mode-help').textContent = MODES.find(m => m.code === sel.value)?.body || '';
  get('run-note').textContent = `사건 ${SCENARIO_NAMES[get<HTMLSelectElement>('scenario').value] || '정상 경로'} · 정책 ${sel.value}`;
}
get('mode-cards').addEventListener('click', e => {
  const b = (e.target as HTMLElement).closest<HTMLElement>('[data-mode]'); if (!b) return;
  get<HTMLSelectElement>('mode').value = b.dataset.mode!; renderModeCards();
});
get<HTMLSelectElement>('mode').onchange = renderModeCards;
function renderScenarioPills() {
  const sel = get<HTMLSelectElement>('scenario');
  get('scenario-pills').innerHTML = [...sel.options].map(o => `<button type="button" class="pill${sel.value === o.value ? ' on' : ''}" data-scenario="${esc(o.value)}" role="radio" aria-checked="${sel.value === o.value}" title="${esc(o.textContent || '')}"${sel.disabled ? ' disabled' : ''}>${esc(o.textContent || '')}</button>`).join('');
  get('scenario-help').hidden = !sel.disabled;
  renderModeCards();
}
get('scenario-pills').addEventListener('click', e => {
  const b = (e.target as HTMLElement).closest<HTMLButtonElement>('[data-scenario]'); if (!b || b.disabled) return;
  get<HTMLSelectElement>('scenario').value = b.dataset.scenario!; renderScenarioPills();
});

function renderConnection(data: Data) {
  connection = data;
  // 구 Agent 는 이 필드를 내지 않는다. 그때는 null 로 두어 사전 차단을 하지 않고,
  // 호출이 실패하면 call() 이 재패키징 안내를 붙인다.
  agentOperations = Array.isArray(data.operations) ? data.operations as string[] : null;
  const isLab = data.source === 'network_lab';
  get('source').textContent = isLab ? 'TLS 실험실 · 단일 운영자' : '연결 모드 · evaluation';
  get('source').className = 'badge';
  get('env-badge').textContent = isLab ? '평가 환경 · 실험실 · air-local' : '연결 모드 · evaluation · air-local';
  get('agent-status').textContent = native ? 'U Agent 연결됨' : 'UI 미리보기 · 표본 데이터';
  get('agent-dot').className = 'live-dot' + (native ? '' : ' warn');
  get<HTMLButtonElement>('run-witness').disabled = !data.witness_configured;
  const policyOk = Date.now() < data.policy_expires_at;
  get('policy-state').textContent = policyOk ? '로컬 정책 유효' : '정책 만료';
  get('policy-state').className = 'badge ' + (policyOk ? 'green' : 'red');
  get('model-field').textContent = `${data.model_id} · ${data.model_kind}`;
  const scenario = get<HTMLSelectElement>('scenario'); scenario.disabled = !isLab;
  if (!isLab) scenario.value = 'normal';
  renderScenarioPills();
  const labT = get<HTMLButtonElement>('lab-t');
  if (data.services && native) {
    const running = data.services.T.running;
    labT.hidden = false; labT.textContent = running ? '실험: T 중단' : 'T 복구';
    labT.onclick = async () => {
      try { renderConnection(await call(running ? 'stop_t' : 'start_t')); notice(running ? 'T를 중단했습니다. protect와 strict의 동작을 비교할 수 있습니다.' : 'T를 복구했습니다. 대기 증거가 자동으로 재제출됩니다.'); }
      catch (e) { fail(e); }
    };
  } else labT.hidden = true;
  renderConnectionCards(data);
  renderBundle(data);
  renderRoute();
  setBusy(busy);
}
async function updateStatus() { try { renderConnection(await call('status')); } catch (e) { fail(e); } }

function renderResult(record: Data) {
  selected = record;
  get('summary').innerHTML = summaryHtml(record);
  get('result').innerHTML = bodyHtml(record);
  get('result-details').innerHTML = detailHtml(record);
  get('request-state').className = 'badge ' + color(record.state); get('request-state').textContent = STATE_NAMES[record.state] || record.state;
  get('body-meta').textContent = releaseLabel(record);
  get('request-title').textContent = fromLog ? '사건 조사' : '요청';
  get('request-meta').textContent = `${String(record.sub || '').slice(-18)} · ${new Date(record.started_at).toLocaleString('ko-KR')}`;
  get('back-to-log').hidden = !fromLog;
  get('view-request').querySelector<HTMLButtonElement>('button[data-refresh]')!.onclick = async () => {
    const sub = record.sub;
    try { const fresh = await call('refresh', {sub}); if (selected?.sub === sub) renderResult(fresh); notice('T 판정을 갱신했습니다. 기존 집행 결과는 바뀌지 않습니다.'); } catch (e) { fail(e); }
  };
  renderTimeline(record);
  renderRoute();
  setDetail(true);
}
get<HTMLFormElement>('request-form').onsubmit = async event => {
  event.preventDefault();
  if (busy) return;
  activeToken = crypto.randomUUID();
  fromLog = null; get('back-to-log').hidden = true; get('request-title').textContent = '요청'; get('request-meta').textContent = '';
  setBusy(true); get('notice').hidden = true; liveEvents = []; renderTimeline(null);
  get('summary').innerHTML = summaryHtml(null, true);
  get('result').innerHTML = `<div class="busybar"></div><div class="empty"><div class="empty-glyph">◇</div><h3>응답을 보류하고 검증합니다</h3><p>서명·요청·응답 결합을 확인하기 전에는 원문을 공개하지 않습니다.</p></div>`;
  get('result-details').innerHTML = '';
  get('request-state').textContent = '진행 중'; get('request-state').className = 'badge amber'; get('body-meta').textContent = '대기';
  try {
    const record = await call('request', {token: activeToken, prompt: get<HTMLTextAreaElement>('prompt').value, mode: get<HTMLSelectElement>('mode').value, scenario: get<HTMLSelectElement>('scenario').value});
    renderResult(record);
    if (record.state !== 'error' && record.state !== 'cancelled' && !record.t_verdict) {
      setTimeout(async () => { try { const fresh = await call('refresh', {sub: record.sub}); if (!busy && selected?.sub === record.sub) renderResult(fresh); } catch { /* T 장애는 명시적 대기 상태로 남긴다 */ } }, 900);
    }
  } catch (e) { fail(e); get('result').innerHTML = '<div class="v3-body absent">요청을 완료하지 못했습니다. Agent 상태를 확인하세요.</div>'; get('summary').innerHTML = summaryHtml(null); }
  finally { activeToken = ''; setBusy(false); await updateStatus(); }
};
// 요청 내용은 여러 줄이므로 Enter 는 줄바꿈으로 두고, 실행은 Ctrl/⌘+Enter 로 받는다.
get<HTMLTextAreaElement>('prompt').addEventListener('keydown', event => {
  if (event.key !== 'Enter' || !(event.ctrlKey || event.metaKey)) return;
  event.preventDefault();
  if (!busy && connection) get<HTMLFormElement>('request-form').requestSubmit();
});
get('cancel').onclick = async () => { try { await call('cancel', {token: activeToken}); notice('취소를 요청했습니다. 원격 호출의 완료 여부와 별개로, 취소가 처리되면 응답을 공개하지 않습니다.'); } catch (e) { fail(e); } };

// ---------- 사건 기록: 검색 · 필터 · 표 ----------
const historyFilter = {query: '', mode: 'all', verdict: 'all', range: 'all'};
let historyCache: Data[] = [];
const FILTERS: {key: 'mode' | 'verdict' | 'range'; label: string; options: [string, string][]}[] = [
  {key: 'range', label: '기간', options: [['all', '전체'], ['today', '오늘']]},
  {key: 'mode', label: '집행 정책', options: [['all', '전체'], ['protect', '기본 보호'], ['strict', '제3자 확인'], ['observe', '관찰 전용']]},
  {key: 'verdict', label: '검증 결과', options: [['all', '전체'], ['pass', '통과'], ['fail', '실패'], ['na', '판정 없음']]},
];
function renderHistoryFilters() {
  get('history-filters').innerHTML = FILTERS.map(f => `<div class="v3-filter"><div class="v3-label">${f.label}</div><div class="v3-pills">${f.options.map(([v, label]) =>
    `<button type="button" class="pill${historyFilter[f.key] === v ? ' on' : ''}" data-filter="${f.key}" data-value="${v}">${label}</button>`).join('')}</div></div>`).join('');
}
get('history-filters').addEventListener('click', e => {
  const b = (e.target as HTMLElement).closest<HTMLElement>('[data-filter]'); if (!b) return;
  (historyFilter as Data)[b.dataset.filter!] = b.dataset.value; renderHistoryFilters(); renderHistoryTable();
});
get<HTMLInputElement>('history-query').addEventListener('input', () => { historyFilter.query = get<HTMLInputElement>('history-query').value.trim(); renderHistoryTable(); });
get('history-clear').onclick = () => { Object.assign(historyFilter, {query: '', mode: 'all', verdict: 'all', range: 'all'}); get<HTMLInputElement>('history-query').value = ''; renderHistoryFilters(); renderHistoryTable(); };
function renderHistoryTable() {
  const target = get('history-content');
  const today = new Date().toDateString();
  const rows = historyCache.filter(r => {
    if (historyFilter.query && !String(r.sub).includes(historyFilter.query) && !String(r.attempt_id || '').includes(historyFilter.query)) return false;
    if (historyFilter.mode !== 'all' && r.mode !== historyFilter.mode) return false;
    if (historyFilter.verdict !== 'all' && (verdictOf(r) === 'wait' ? 'na' : verdictOf(r)) !== historyFilter.verdict) return false;
    if (historyFilter.range === 'today' && new Date(r.started_at).toDateString() !== today) return false;
    return true;
  });
  get('history-count').textContent = `${rows.length} / ${historyCache.length} 건`;
  target.replaceChildren();
  if (!historyCache.length) { target.append(el('div', 'empty', '저장된 요청이 없습니다.')); return; }
  if (!rows.length) { target.append(el('div', 'empty', '조건에 맞는 사건이 없습니다. 필터를 초기화해 보세요.')); return; }
  const wrap = el('div', 'table-wrap'), table = el('table', 'history-table v3-table'), head = el('tr');
  for (const title of ['요청 ID · 시각', '정책', '실험 조건', '검증 결과', '응답 공개', '집행', 'T 판정', '소요', '']) head.append(el('th', '', title)); table.append(head);
  const VERDICT_KO: Record<string, string> = {pass: '검증 통과', fail: '검증 실패', na: '판정 없음', wait: '진행 중'};
  const GLYPH: Record<string, string> = {pass: '✓', fail: '✗', na: '–', wait: '…'};
  for (const record of rows) {
    const row = el('tr');
    const id = el('td'); id.append(el('div', 'mono', String(record.sub).slice(-18)), el('div', 'mono muted small', new Date(record.started_at).toLocaleString('ko-KR'))); row.append(id);
    row.append(el('td', 'mono', record.mode), el('td', 'small', SCENARIO_NAMES[record.lab_scenario] || record.lab_scenario || '—'));
    const vt = verdictOf(record); const vc = el('td'); const vs = el('span', vt === 'wait' ? 'na' : vt, `${GLYPH[vt]} ${VERDICT_KO[vt]}`); vc.append(vs); row.append(vc);
    row.append(el('td', 'small', releaseLabel(record)));
    const state = el('td'); state.append(badge(STATE_NAMES[record.state] || record.state, color(record.state))); row.append(state);
    const v = record.t_verdict?.payload; const tv = el('td'); tv.append(badge(v ? v.verification_status : '대기', v ? (v.verification_status === 'passed' ? 'green' : 'red') : '')); row.append(tv);
    row.append(el('td', 'mono', `${record.elapsed_ms ?? '—'} ms`));
    const action = el('td'); action.append(button('조사', () => { fromLog = record; showView('request').catch(fail); renderResult(record); })); row.append(action); table.append(row);
  }
  wrap.append(table); target.append(wrap);
}
async function loadHistory() {
  try {
    historyCache = await call<Data[]>('history');
    setHint('history', String(historyCache.length));
    renderHistoryFilters(); renderHistoryTable();
  } catch (e) { fail(e); }
}
get('reload-history').onclick = () => { loadHistory().catch(fail); };

// ---------- 제3자 검증 ----------
get('run-audit').onclick = async () => {
  const b = get<HTMLButtonElement>('run-audit'); b.disabled = true;
  try {
    const a = await call('audit');
    // 요약 카드 4장 위에, 트리 헤드·앵커·판정 대조 다이어그램과 그 근거 JSON 을 양방향으로 연동해 보인다 (audit-view.ts).
    get('audit-cards').innerHTML = auditCardsHtml(a);
    get('audit-meta').textContent = `검사기 ${a.auditor_checker_version || '—'} · ${new Date().toLocaleString('ko-KR')}`;
    setHint('audit', (a.verdict_mismatches || []).length ? `불일치 ${a.verdict_mismatches.length}` : '');
    renderAudit(get('audit-content'), a);
  } catch (e) { fail(e); } finally { b.disabled = false; }
};
get('export').onclick = async () => { try { const result = await call('export'); notice('수용된 응답과 판정 기록을 저장했습니다: ' + result.path); } catch (e) { fail(e); } };
get('connect').onclick = async () => { try { renderConnection(await call('connect', {path: get<HTMLInputElement>('config-path').value})); selected = null; renderRoute(); renderTimeline(null); notice('선택한 신뢰 설정으로 연결했습니다. 새 요청부터 적용됩니다.'); } catch (e) { fail(e); } };
get('use-lab').onclick = async () => { try { renderConnection(await call('lab')); notice('로컬 TLS 실험실로 전환했습니다.'); } catch (e) { fail(e); } };

// ---------- 연결: 역할별 카드 ----------
const ROLE_NAME: Record<string, string> = {U: '사용자 · 집행 모듈', R: '중개자 (클라우드 대행)', M: '모델 운영자', T: '독립 제3자 원장', W: '목격자'};
let lastPreflight: Data | null = null;
function renderConnectionCards(data: Data) {
  const target = get('connection-details'); target.replaceChildren();
  get('settings-meta').textContent = `${data.source === 'network_lab' ? 'TLS 실험실' : '연결 모드'} · 정책 세대 ${data.epoch ?? '실험실'}`;
  const copyable = (value: string) => { const code = el('code', 'copyable', value); code.dataset.copy = value; code.tabIndex = 0; code.title = '클릭하면 전체 값을 복사합니다'; return code; };
  const row = (k: string, v: string | HTMLElement, cls = '') => { const r = el('div', 'v3-kv'); r.append(el('span', 'k', k)); const val = typeof v === 'string' ? el('span', 'v ' + cls, v) : v; val.classList.add('v'); r.append(val); return r; };

  // 이 연결 자체
  const self = el('section', 'v3-card'); const sh = el('div', 'v3-card-head'); sh.append(el('span', 'role-badge', 'U'), el('span', 'v3-card-title', '이 연결'), el('span', 'v3-meta', data.governance)); self.append(sh);
  const sb = el('div', 'v3-card-body v3-kvs'); self.append(sb);
  sb.append(row('환경', data.source), row('모델', `${data.model_id} / ${data.model_kind}`), row('운영 주체', data.governance), row('대기 증거', `${data.pending_evidence}건`),
    row('정책 만료', new Date(data.policy_expires_at).toLocaleString('ko-KR')), row('정책 해시', copyable(data.policy_hash)), row('설정 파일', copyable(data.config_path)),
    row('U 고정 공개키', copyable(data.identities.U.public_key)));
  if (data.deployment_hash) sb.append(row('배포 지문', copyable(data.deployment_hash)), row('정책 세대', String(data.epoch)));
  if (data.deployment_history?.length) sb.append(details('서명으로 연결된 배포·체크포인트 이력', data.deployment_history));
  target.append(self);

  // 상대 역할 — 실측한 것만 적는다. 응답 지연은 「연결 확인」(preflight) 을 돌린 뒤 채워진다.
  const grid = el('div', 'v3-endpoint-grid'); target.append(grid);
  const roles = ['R', 'M', 'T', ...(data.witness_configured ? ['W'] : [])];
  for (const role of roles) {
    const card = el('section', 'v3-card'); const head = el('div', 'v3-card-head');
    const state = el('span', 'v3-meta', '확인 전'); state.dataset.role = role;
    head.append(el('span', 'role-badge' + (role === 'T' ? ' t' : ''), role), el('span', 'v3-card-title', ROLE_NAME[role]), state); card.append(head);
    const body = el('div', 'v3-card-body v3-kvs'); card.append(body);
    body.append(row('엔드포인트', copyable(data.endpoints[role])), row('고정 공개키', copyable(data.identities[role].public_key)),
      row('기준점 목록', role === 'T' ? '자기 서명 — 상위 기준점 없음' : '배포 설정에 고정', role === 'T' ? 'warn' : 'pass'));
    const latency = row('응답 지연', '연결 확인 뒤 표시', 'muted'); latency.dataset.latencyFor = role; body.append(latency);
    const actions = el('div', 'button-row'); actions.style.marginTop = '10px';
    actions.append(button('연결 확인', async () => {
      try { lastPreflight = await call('preflight'); applyPreflight(); notice(lastPreflight!.ok ? '모든 역할이 응답했습니다.' : '응답하지 않은 역할이 있습니다. 카드의 상태를 확인하세요.'); } catch (e) { fail(e); }
    })); body.append(actions);
    grid.append(card);
  }
  if (lastPreflight) applyPreflight();
}
function applyPreflight() {
  const services: Data = lastPreflight?.services || {};
  for (const [role, s] of Object.entries(services) as [string, Data][]) {
    const state = document.querySelector<HTMLElement>(`#connection-details [data-role="${role}"]`), lat = document.querySelector<HTMLElement>(`#connection-details [data-latency-for="${role}"] .v`);
    if (state) { state.textContent = s.ok ? `확인 완료 · 연결됨${s.accepting_requests === false ? ' · 요청 거부 중' : ''}` : '확인 완료 · 응답 없음'; state.className = 'v3-meta ' + (s.ok ? 'pass' : 'fail'); }
    if (lat) { lat.textContent = s.ok ? `왕복 ${s.elapsed_ms} ms · 대기열 ${s.queue_depth ?? 0}` : (s.error || '응답 없음'); lat.className = 'v ' + (s.ok ? '' : 'fail'); }
  }
}

// ---------- 감사 자료: 번들 구성 (현재 연결에서 실제로 나가는 것만 적는다) ----------
function renderBundle(data: Data) {
  const items: [string, string, string, 'ok' | 'partial' | 'absent'][] = [
    ['원장 내보내기 · U/R/M/T 진술 전부', 'log_export', '등록된 모든 진술과 트리 헤드 서명 — 공개 패키지 포함', 'ok'],
    ['요청별 salt · 원문 해시', 'private_by_sub', '암호화 패키지에만 · 지정한 감사자 키로', 'partial'],
    ['체크포인트 앵커', 'anchors', 'T 체크포인트 저장 뒤 포함 — 파일 기반 모사, 실체인 게시 아님', 'partial'],
    ['목격자 영수증', 'witness_receipts', data.witness_configured ? 'W 확인 요청 뒤 포함 · T 와 같은 호스트' : '목격자 없음 — 결손 사실과 함께 반출', data.witness_configured ? 'partial' : 'absent'],
    ['배포 이력 · 배포 묶음', 'deployment_history', data.deployment_hash ? `배포 지문 ${String(data.deployment_hash).slice(0, 12)}…` : '실험실 — 배포 묶음 없음', data.deployment_hash ? 'ok' : 'partial'],
  ];
  const STATE: Record<string, [string, string]> = {ok: ['포함', 'pass'], partial: ['조건부 · 모사', 'warn'], absent: ['결손 — 사실과 함께 반출', 'na']};
  get('bundle-items').innerHTML = items.map(([title, key, note, state]) => `<div class="v3-bundle-row${state === 'absent' ? ' absent' : ''}">
      <span class="v3-bundle-mark ${STATE[state][1]}">${state === 'ok' ? '✓' : state === 'partial' ? '!' : '–'}</span>
      <span class="t"><b>${title}</b><span class="mono muted">${key}</span></span><span class="n">${note}</span><span class="mono ${STATE[state][1]}">${STATE[state][0]}</span></div>`).join('');
  get('bundle-meta').textContent = `공개 패키지 ${items.filter(i => i[3] === 'ok').length}항목 확정 · 검증 명령과 결손 목록을 담은 README 가 함께 나갑니다`;
}

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

// 배포 위저드. 탭은 자유롭게 오간다 — 운영자마다 다른 PC 에서 다른 단계를 수행하므로 선형 게이트는 기능 퇴행이다.
const STEPS: {key: string; title: string}[] = [{key: 'identity', title: '신원 생성'}, {key: 'propose', title: '배포 제안'}, {key: 'endorse', title: '검토·서명'}, {key: 'assemble', title: '승인 모으기'}, {key: 'activate', title: '활성화'}];
const stepDone: Record<string, string> = {};
let stepKey = 'identity';
function renderWizard() {
  const i = STEPS.findIndex(s => s.key === stepKey);
  get('deploy-tabs').innerHTML = STEPS.map((s, n) => {
    const done = !!stepDone[s.key], on = s.key === stepKey;
    return `<div class="v3-step-wrap"><button type="button" class="v3-step${on ? ' on' : ''}${done ? ' done' : ''}" data-step-tab="${s.key}">
      <span class="hd"><span class="num">${done ? '✓' : n + 1}</span><span class="mono muted">0${n + 1}</span></span><span class="ti">${s.title}</span><span class="st ${done ? 'pass' : on ? 'accent' : 'muted'}">${done ? '완료 · ' + stepDone[s.key] : on ? '진행 중' : '대기'}</span></button>
      ${n < STEPS.length - 1 ? `<span class="v3-step-conn${done ? ' done' : ''}"></span>` : ''}</div>`;
  }).join('');
  document.querySelectorAll<HTMLElement>('#view-deployment [data-step]').forEach(s => { s.hidden = s.dataset.step !== stepKey; });
  get<HTMLButtonElement>('deploy-prev').disabled = i <= 0;
  get<HTMLButtonElement>('deploy-next').disabled = i >= STEPS.length - 1;
  get('deploy-next').textContent = i >= STEPS.length - 1 ? '마지막 단계' : '다음 단계 →';
  get('deploy-meta').textContent = `${Object.keys(stepDone).length} / 5 단계 완료 · 이 PC 기준`;
}
get('deploy-tabs').addEventListener('click', e => { const b = (e.target as HTMLElement).closest<HTMLElement>('[data-step-tab]'); if (!b) return; stepKey = b.dataset.stepTab!; renderWizard(); });
get('deploy-prev').onclick = () => { const i = STEPS.findIndex(s => s.key === stepKey); if (i > 0) { stepKey = STEPS[i - 1].key; renderWizard(); } };
get('deploy-next').onclick = () => { const i = STEPS.findIndex(s => s.key === stepKey); if (i < STEPS.length - 1) { stepKey = STEPS[i + 1].key; renderWizard(); } };
const markDone = (key: string, note: string) => { stepDone[key] = note; get('deploy-result-meta').textContent = `${STEPS.find(s => s.key === key)?.title} · ${new Date().toLocaleTimeString('ko-KR')}`; renderWizard(); };
renderWizard();

action('prepare-operator', 'enroll_prepare', () => ({role: input('operator-role'), endpoint: input('operator-endpoint')}), 'deployment-output', r => {
  get<HTMLInputElement>('endorse-operator').value = r.directory; get<HTMLInputElement>('activate-operator').value = r.directory; markDone('identity', input('operator-role'));
});
action('propose-deployment', 'enroll_propose', () => ({card_paths: lines('deployment-cards'), previous_bundle: input('deployment-previous'), checkpoint: input('deployment-checkpoint'), model_kind: input('deployment-model-kind'), model_id: input('deployment-model-id'), model_hash: input('deployment-model-hash'), model_name: input('deployment-model-name'), pre_exec: get<HTMLInputElement>('deployment-pre-exec').checked}), 'deployment-output', r => {
  get<HTMLInputElement>('endorse-proposal').value = r.path; get<HTMLInputElement>('assemble-proposal').value = r.path; markDone('propose', String(r.fingerprint || '').slice(0, 8));
});
action('endorse-deployment', 'enroll_endorse', () => ({operator_directory: input('endorse-operator'), proposal: input('endorse-proposal'), fingerprint: input('endorse-fingerprint'), previous_config: input('endorse-previous')}), 'deployment-output', () => markDone('endorse', '서명'));
action('assemble-deployment', 'enroll_assemble', () => ({proposal: input('assemble-proposal'), endorsement_paths: lines('assemble-endorsements'), previous_bundle: input('assemble-previous')}), 'deployment-output', r => { get<HTMLInputElement>('activate-bundle').value = r.path; markDone('assemble', String(r.fingerprint || '').slice(0, 8)); });
action('inspect-deployment', 'enroll_inspect', () => ({bundle: input('activate-bundle')}), 'deployment-output');
action('activate-deployment', 'enroll_activate', () => ({operator_directory: input('activate-operator'), bundle: input('activate-bundle'), fingerprint: input('activate-fingerprint'), bind: input('activate-bind'), model_endpoint: input('activate-model-endpoint'), previous_config: input('activate-previous')}), 'deployment-output', r => { get<HTMLInputElement>('config-path').value = r.config_path; markDone('activate', '활성'); });
action('preflight', 'preflight', () => ({}), 'evidence-output', r => { lastPreflight = r; applyPreflight(); });
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
  get('summary').innerHTML = summaryHtml(null);
  renderModeCards(); renderScenarioPills(); renderRoute(); renderTimeline(null);
  if (!native) {
    get('agent-status').textContent = '데스크톱 연결 없음'; get('source').textContent = 'UI 미리보기';
    notice('브라우저 미리보기입니다. 표본 데이터로 화면만 확인하며, 실제 실행은 itx 설치형 앱에서 합니다.');
    await updateStatus();
    return;
  }
  await listen<Data>('agent-progress', e => { if (e.payload.token === activeToken) { liveEvents.push(e.payload); renderTimeline({timeline: liveEvents}); get('run-live-text').textContent = `검증 진행 중 · ${e.payload.kind || ''} · t = ${Math.round(e.payload.t_ms ?? 0)} ms`; } });
  await listen<string>('agent-failure', e => { connection = null; setBusy(false); get('agent-status').textContent = 'Agent 연결 종료'; get('agent-dot').className = 'live-dot off'; fail(e.payload); });
  await updateStatus();
}
boot().catch(fail);
