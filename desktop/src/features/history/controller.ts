import type { AgentCall, Data } from '../../shared/types';
import { get, el, badge, color, button, setHint, fail } from '../../shared/dom';
import { STATE_NAMES, SCENARIO_NAMES, verdictOf, releaseLabel } from '../request/view';

export function createHistory(call: AgentCall, onInspect: (record: Data) => void) {
  // ---------- 사건 기록: 검색 · 필터 · 표 ----------
  const historyFilter = {query: '', mode: 'all', verdict: 'all', range: 'all'};
  let historyCache: Data[] = [];
  const FILTERS: {key: 'mode' | 'verdict' | 'range'; label: string; options: [string, string][]}[] = [
    {key: 'range', label: '기간', options: [['all', '전체'], ['today', '오늘']]},
    {key: 'mode', label: '집행 정책', options: [['all', '전체'], ['protect', '기본 보호'], ['strict', '제3자 확인'], ['observe', '관찰 전용']]},
    {key: 'verdict', label: '검증 결과', options: [['all', '전체'], ['pass', '통과'], ['fail', '실패'], ['na', '판정 없음']]},
  ];
  function renderHistoryFilters() {
    // 네 축(요청 ID · 기간 · 집행 정책 · 검증 결과)은 전부 실제 조사에서 쓰인다. 줄을 바꿀 뿐 축을 감추지 않는다.
    get('history-filters').innerHTML = FILTERS.map(f => `<span class="itx-filter-label">${f.label}</span><div class="itx-seg" role="group" aria-label="${f.label}">${f.options.map(([v, label]) =>
      `<button type="button" class="${historyFilter[f.key] === v ? 'on' : ''}" aria-pressed="${historyFilter[f.key] === v}" data-filter="${f.key}" data-value="${v}">${label}</button>`).join('')}</div>`).join('');
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
    const wrap = el('div', 'table-wrap'), table = el('table', 'itx-table history-table'), head = el('tr');
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
      const action = el('td'); action.append(button('조사', () => { onInspect(record); })); row.append(action); table.append(row);
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
  return { show: loadHistory };
}
