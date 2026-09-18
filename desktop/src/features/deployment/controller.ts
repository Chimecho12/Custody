import type { ActionBinder } from '../../shared/types';
import { get, input, lines } from '../../shared/dom';

export function initializeDeployment(action: ActionBinder) {
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

}
