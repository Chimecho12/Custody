import type { AgentCall, ActionBinder, Data } from './types';
import { get, badge, el, pretty, notice, fail } from './dom';

export function createActionBinder(call: AgentCall, isBusy: () => boolean): ActionBinder {
  function action(id: string, operation: string, args: () => Data = () => ({}), target = 'evidence-output', after?: (result: Data) => void, disabled: () => boolean = () => false) {
    get(id).onclick = async () => {
      if (isBusy()) { notice('진행 요청이 끝난 뒤 실행하세요.'); return; }
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
      } catch (e) { fail(e); } finally { b.disabled = disabled(); }
    };
  }
  return action;
}
