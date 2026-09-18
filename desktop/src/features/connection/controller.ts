import type { AgentCall, Data } from '../../shared/types';
import { get, el, details, button, notice, fail } from '../../shared/dom';

export function createConnection(call: AgentCall) {
  // ---------- 연결: 역할별 패널. 값은 인스펙터 행(필드명 / 값)으로, 실측한 것만 적는다. ----------
  const ROLE_NAME: Record<string, string> = {U: '사용자 · 집행 모듈', R: '중개자 (클라우드 대행)', M: '모델 운영자', T: '독립 제3자 원장', W: '목격자'};
  let lastPreflight: Data | null = null;
  function renderConnectionCards(data: Data) {
    const target = get('connection-details'); target.replaceChildren();
    get('settings-meta').textContent = `${data.source === 'network_lab' ? 'TLS 실험실' : '연결 모드'} · 정책 세대 ${data.epoch ?? '실험실'}`;
    const copyable = (value: string) => { const code = el('code', 'copyable', value); code.dataset.copy = value; code.tabIndex = 0; code.title = '클릭하면 전체 값을 복사합니다'; return code; };
    const row = (k: string, v: string | HTMLElement, cls = '') => {
      const r = el('div', 'itx-kv-row'); r.append(el('span', 'itx-kv-k mono-meta', k));
      const val = typeof v === 'string' ? el('span', cls, v) : v; val.classList.add('itx-kv-v', 'mono-data', 'v'); r.append(val); return r;
    };
    const panel = (role: string, title: string, meta: string | HTMLElement) => {
      const card = el('section', 'itx-panel'), head = el('div', 'itx-panel-head');
      head.append(el('span', 'itx-role' + (role === 'T' ? ' t' : ''), role), el('span', 'itx-panel-title ui-subtitle', title), el('span', 'itx-spacer'));
      head.append(typeof meta === 'string' ? el('span', 'itx-panel-meta mono-meta', meta) : meta);
      card.append(head); return card;
    };

    // 이 연결 자체 — 격자 첫 줄 전체를 차지한다
    const self = panel('U', '이 연결', data.governance); self.classList.add('itx-panel--self');
    const sb = el('div', 'itx-kv'); self.append(sb);
    sb.append(row('환경', data.source), row('모델', `${data.model_id} / ${data.model_kind}`), row('운영 주체', data.governance), row('대기 증거', `${data.pending_evidence}건`),
      row('정책 만료', new Date(data.policy_expires_at).toLocaleString('ko-KR')), row('정책 해시', copyable(data.policy_hash)), row('설정 파일', copyable(data.config_path)),
      row('U 고정 공개키', copyable(data.identities.U.public_key)));
    if (data.deployment_hash) sb.append(row('배포 지문', copyable(data.deployment_hash)), row('정책 세대', String(data.epoch)));
    if (data.deployment_history?.length) { const d = el('div', 'itx-section'); d.append(details('서명으로 연결된 배포·체크포인트 이력', data.deployment_history)); self.append(d); }
    target.append(self);

    // 상대 역할 — 실측한 것만 적는다. 응답 지연은 「연결 확인」(preflight) 을 돌린 뒤 채워진다.
    const roles = ['R', 'M', 'T', ...(data.witness_configured ? ['W'] : [])];
    for (const role of roles) {
      const state = el('span', 'itx-panel-meta mono-meta', '확인 전'); state.dataset.role = role;
      const card = panel(role, ROLE_NAME[role], state);
      const body = el('div', 'itx-kv'); card.append(body);
      body.append(row('엔드포인트', copyable(data.endpoints[role])), row('고정 공개키', copyable(data.identities[role].public_key)),
        row('기준점 목록', role === 'T' ? '자기 서명 — 상위 기준점 없음' : '배포 설정에 고정', role === 'T' ? 'warn' : 'pass'));
      const latency = row('응답 지연', '연결 확인 뒤 표시', 'muted'); latency.dataset.latencyFor = role; body.append(latency);
      const foot = el('div', 'itx-panel-foot');
      foot.append(button('연결 확인', async () => {
        try { lastPreflight = await call('preflight'); applyPreflight(); notice(lastPreflight!.ok ? '모든 역할이 응답했습니다.' : '응답하지 않은 역할이 있습니다. 카드의 상태를 확인하세요.'); } catch (e) { fail(e); }
      })); card.append(foot);
      target.append(card);
    }
    if (lastPreflight) applyPreflight();
  }
  function applyPreflight() {
    const services: Data = lastPreflight?.services || {};
    for (const [role, s] of Object.entries(services) as [string, Data][]) {
      const state = document.querySelector<HTMLElement>(`#connection-details [data-role="${role}"]`), lat = document.querySelector<HTMLElement>(`#connection-details [data-latency-for="${role}"] .v`);
      if (state) { state.textContent = s.ok ? `확인 완료 · 연결됨${s.accepting_requests === false ? ' · 요청 거부 중' : ''}` : '확인 완료 · 응답 없음'; state.className = 'itx-panel-meta mono-meta ' + (s.ok ? 'pass' : 'fail'); }
      if (lat) { lat.textContent = s.ok ? `왕복 ${s.elapsed_ms} ms · 대기열 ${s.queue_depth ?? 0}` : (s.error || '응답 없음'); lat.className = 'itx-kv-v mono-data v ' + (s.ok ? '' : 'fail'); }
    }
  }
  return { render: renderConnectionCards, preflight: (result: Data) => { lastPreflight = result; applyPreflight(); } };
}
