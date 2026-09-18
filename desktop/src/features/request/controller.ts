import type { Data } from '../../shared/types';
import { call, native, setAgentOperations } from '../../services/agent';
import { get, color, notice, fail } from '../../shared/dom';
import { esc } from '../../shared/console';
import { createRequestRoute } from './route';
import { SCENARIO_NAMES, MODES, type RouteControls } from './controls';
import { STATE_NAMES, summaryHtml, bodyHtml, detailHtml, timelineHtml, releaseLabel } from './view';

export function createRequest(onConnection: (data: Data) => void) {
  let connection: Data | null = null;
  let selected: Data | null = null;
  let liveEvents: Data[] = [];
  let activeToken = '';
  let busy = false;
  let changingT = false;
  let fromLog: Data | null = null;   // 사건 기록에서 「조사」로 들어온 경우 — 돌아가기 버튼과 제목이 바뀐다
  const route = createRequestRoute(get('route-map'), get('view-request'),
    () => ({connection, record: selected, controls: controls()}), action => {
      if (action.kind === 'scenario') selectScenario(action.value);
      else void setTRunning(action.running);
    });
  function setBusy(value: boolean) {
    busy = value;
    const locked = value || changingT;
    get<HTMLButtonElement>('send').disabled = locked || !connection;
    get<HTMLButtonElement>('cancel').disabled = !value;
    get<HTMLButtonElement>('send').textContent = value ? '실행 중…' : '요청 실행 ↗';
    get('run-live').hidden = !value;
    for (const id of ['connect', 'use-lab', 'lab-t']) get<HTMLButtonElement>(id).disabled = locked;
    get<HTMLSelectElement>('scenario').disabled = locked || connection?.source !== 'network_lab';
    renderScenarioPills();
  }

  // ---------- 요청 화면 ----------
  function controls(): RouteControls {
    return {scenario: get<HTMLSelectElement>('scenario').value,
      canInject: connection?.source === 'network_lab', busy: busy || changingT,
      tRunning: connection?.source === 'network_lab' && connection.services && native
        ? !!connection.services.T?.running : null};
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
    // 가시성은 연결 종류로만 정하고 진행 상태와 섞지 않는다. sel.disabled 로 판단하면 실험실에서
    // 요청이 도는 동안 연결 모드용 안내가 떴다 사라진다. 실행 중 잠금은 pill 의 disabled 로 나타낸다.
    const canInject = connection?.source === 'network_lab';
    get('scenario-pills').innerHTML = [...sel.options].map(o => `<button type="button" class="pill${sel.value === o.value ? ' on' : ''}" data-scenario="${esc(o.value)}" role="radio" aria-checked="${sel.value === o.value}" title="${esc(o.textContent || '')}"${sel.disabled ? ' disabled' : ''}>${esc(o.textContent || '')}</button>`).join('');
    get('scenario-help').hidden = canInject;
    get('scenario-on-map').hidden = !canInject;
    renderModeCards();
    route.syncControls();
  }
  // 지도와 실험 조건 버튼은 같은 선택 경로를 사용한다.
  function selectScenario(value: string) {
    const sel = get<HTMLSelectElement>('scenario');
    if (sel.disabled || ![...sel.options].some(option => option.value === value)) return;
    sel.value = value;
    renderScenarioPills();
  }
  get<HTMLSelectElement>('scenario').onchange = renderScenarioPills;
  get('scenario-on-map').onclick = () => {
    setDetail(true);
    get('route-map').scrollIntoView({behavior: 'smooth', block: 'start'});
    route.openRelayMenu();
  };
  get('scenario-pills').addEventListener('click', e => {
    const b = (e.target as HTMLElement).closest<HTMLButtonElement>('[data-scenario]'); if (!b || b.disabled) return;
    selectScenario(b.dataset.scenario!);
  });

  async function setTRunning(running: boolean) {
    const ctl = controls();
    if (ctl.busy || ctl.tRunning === null || ctl.tRunning === running) return;
    changingT = true; setBusy(busy);
    try {
      renderConnection(await call(running ? 'start_t' : 'stop_t'));
      notice(running ? 'T를 복구했습니다. 대기 증거가 자동으로 재제출됩니다.' : 'T를 중단했습니다. protect와 strict의 동작을 비교할 수 있습니다.');
    } catch (e) { fail(e); }
    finally { changingT = false; setBusy(busy); }
  }

  function renderConnection(data: Data) {
    connection = data;
    // 구 Agent 는 이 필드를 내지 않는다. 그때는 null 로 두어 사전 차단을 하지 않고,
    // 호출이 실패하면 call() 이 재패키징 안내를 붙인다.
    setAgentOperations(data);
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
    if (isLab && data.services && native) {
      const running = data.services.T.running;
      labT.hidden = false; labT.textContent = running ? '실험: T 중단' : 'T 복구';
      labT.onclick = () => { void setTRunning(!running); };
    } else labT.hidden = true;
    onConnection(data);
    route.render();
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
    route.render();
    setDetail(true);
  }
  get<HTMLFormElement>('request-form').onsubmit = async event => {
    event.preventDefault();
    if (busy || changingT || !connection) return;
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

  get('connect').onclick = async () => { try { renderConnection(await call('connect', {path: get<HTMLInputElement>('config-path').value})); selected = null; route.render(); renderTimeline(null); notice('선택한 신뢰 설정으로 연결했습니다. 새 요청부터 적용됩니다.'); } catch (e) { fail(e); } };
  get('use-lab').onclick = async () => { try { renderConnection(await call('lab')); notice('로컬 TLS 실험실로 전환했습니다.'); } catch (e) { fail(e); } };
  return {
    isBusy: () => busy || changingT,
    selectedSub: () => selected?.sub ?? '',
    leave: () => { fromLog = null; get('back-to-log').hidden = true; },
    inspect: (record: Data) => { fromLog = record; renderResult(record); },
    updateStatus,
    initialize: () => {
      get('summary').innerHTML = summaryHtml(null);
      renderModeCards(); renderScenarioPills(); route.render(); renderTimeline(null);
    },
    progress: (data: Data) => {
      if (data.token !== activeToken) return;
      liveEvents.push(data); renderTimeline({timeline: liveEvents});
      get('run-live-text').textContent = `검증 진행 중 · ${data.kind || ''} · t = ${Math.round(data.t_ms ?? 0)} ms`;
    },
    failure: (error: string) => {
      connection = null; setBusy(false); get('agent-status').textContent = 'Agent 연결 종료';
      get('agent-dot').className = 'live-dot off'; fail(error);
    },
  };
}
