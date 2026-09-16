import type { ActionBinder, Data } from '../../shared/types';
import { get, input } from '../../shared/dom';

export function renderBundle(data: Data) {
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

export function initializeEvidence(action: ActionBinder, onPreflight: (data: Data) => void) {
  let retentionToken = '';
  action('preflight', 'preflight', () => ({}), 'evidence-output', onPreflight);
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
  action('retention-apply', 'retention_apply', () => ({token: retentionToken}), 'evidence-output', () => { retentionToken = ''; get('retention-description').textContent = '정리를 적용했습니다. 추가 정리 전 미리보기를 다시 실행하세요.'; }, () => !retentionToken);
}
