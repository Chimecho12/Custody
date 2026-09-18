import type { AgentCall } from '../../shared/types';
import { get, setHint, notice, fail } from '../../shared/dom';
import { renderAudit, auditCardsHtml } from './view';

export function initializeAudit(call: AgentCall) {
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

}
