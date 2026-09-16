import type { Data } from '../shared/types';
import { get, notice, fail } from '../shared/dom';
import { createActionBinder } from '../shared/actions';
import { call, native, listenToAgent } from '../services/agent';
import { ReportView } from '../features/simulation/view';
import { StandardsView } from '../features/standards/view';
import { KeysView } from '../features/keys/view';
import { createRequest } from '../features/request/controller';
import { createHistory } from '../features/history/controller';
import { createConnection } from '../features/connection/controller';
import { initializeAudit } from '../features/audit/controller';
import { initializeDeployment } from '../features/deployment/controller';
import { initializeEvidence, renderBundle } from '../features/evidence/controller';
import { initializeShell } from './shell';

export async function bootstrap() {
  const titles: Record<string, string> = {request: '요청', history: '사건 기록', audit: '제3자 검증', simulation: '참조 시나리오', settings: '연결', deployment: '배포 설정', evidence: '감사 자료', standards: '표준 적합성', keys: '키 · 신뢰 기준점'};

  initializeShell();
  const connection = createConnection(call);
  const request = createRequest((data: Data) => { connection.render(data); renderBundle(data); });
  const history = createHistory(call, record => { showView('request').catch(fail); request.inspect(record); });
  const action = createActionBinder(call, request.isBusy);
  initializeAudit(call);
  initializeDeployment(action);
  initializeEvidence(action, connection.preflight);
  // ---------- 화면 전환: 본문만 바뀌고 스크롤은 항상 맨 위로 ----------
  const report = new ReportView(get('view-simulation'), call, fail);
  const standards = new StandardsView(get('view-standards'), call, fail);
  const keys = new KeysView(get('view-keys'), call, fail);
  async function showView(name: string) {
    for (const node of document.querySelectorAll<HTMLElement>('.view')) node.hidden = node.id !== 'view-' + name;
    for (const node of document.querySelectorAll<HTMLButtonElement>('nav button')) node.classList.toggle('selected', node.dataset.view === name);
    get('breadcrumb').textContent = '워크스페이스 / ' + titles[name];
    window.scrollTo({top: 0, behavior: 'auto'});
    if (name !== 'request') { request.leave(); }
    if (name === 'history') await history.show();
    if (name === 'settings') await request.updateStatus();
    if (name === 'simulation') await report.show();
    if (name === 'standards') await standards.show(request.selectedSub());
    if (name === 'keys') await keys.show();
  }
  for (const b of document.querySelectorAll<HTMLButtonElement>('nav button')) b.onclick = () => { showView(b.dataset.view!).catch(fail); };
  get('back-to-log').onclick = () => { showView('history').catch(fail); };

  request.initialize();
  if (!native) {
    get('agent-status').textContent = '데스크톱 연결 없음'; get('source').textContent = 'UI 미리보기';
    notice('브라우저 미리보기입니다. 표본 데이터로 화면만 확인하며, 실제 실행은 itx 설치형 앱에서 합니다.');
  } else {
    await listenToAgent(request.progress, request.failure);
  }
  await request.updateStatus();
}
