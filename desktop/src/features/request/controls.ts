import type { NodeKey } from '../../shared/console';
import type { NodeMenu, NodeState } from '../../shared/flow';

export const SCENARIO_NAMES: Record<string, string> = {normal: '정상 경로', response_tamper: 'R 의 응답 변조', request_tamper: 'R 의 요청 변조', missing_receipt: 'M 영수증 제거', missing_relay: 'R 의 진술 보류 (결손 · 위반 아님)'};
/** 집행 정책 카드. 제목은 사람 말, 코드는 실제 값. 본문이 곧 이전 화면의 mode-help 였다. */
export const MODES: {code: string; title: string; body: string}[] = [
  {code: 'protect', title: '기본 보호', body: '로컬 검증에 실패하면 응답을 업무에 넘기지 않고 격리합니다. T 가 연결되지 않아도 필수 로컬 증거와 유효한 정책이 있으면 계속합니다.'},
  {code: 'strict', title: '제3자 확인 후 수용', body: '로컬 검사와 T 의 등록 판정을 모두 요구합니다. 기한 내 판정이 없으면 거부합니다.'},
  {code: 'observe', title: '관찰 전용', body: '상태만 알리고 차단하지 않습니다. 검증 실패 응답도 그대로 공개됩니다 — 공격을 관측하기 위한 대조군이며 방어 모드가 아닙니다.'},
];

/** 그림을 조작판으로 쓰기 위한 현재 상태. 그림은 이 값을 보여주고 이벤트로 알릴 뿐, 값을 바꾸는 것은 컨트롤러다. */
export interface RouteControls { scenario: string; canInject: boolean; tRunning: boolean | null; busy: boolean }
// 실험 조건 select 의 값과 1:1 이다. 런타임에서 이 다섯 가지는 모두 R 이 전달 과정에서 하는 일이다 (영수증 제거도 R 이 뗀다).
const R_ACTIONS: {value: string; label: string; flag: string | null; tone?: 'fail' | 'na'}[] = [
  {value: 'normal', label: '정상적으로 전달한다', flag: null},
  {value: 'response_tamper', label: '응답을 바꿔서 전달한다', flag: '응답 변조'},
  {value: 'request_tamper', label: '요청을 바꿔서 전달한다', flag: '요청 변조'},
  {value: 'missing_receipt', label: 'M 의 영수증을 떼고 전달한다', flag: '영수증 제거'},
  {value: 'missing_relay', label: '자기 진술을 내지 않는다', flag: '진술 보류', tone: 'na'},
];
/** 노드 메뉴·표식. shown 은 그림이 보여주는 요청의 시나리오(기록이면 그 기록, 실행 전이면 지금 고른 값). */
export function nodeControls(ctl: RouteControls | undefined, shown: string | null, shownIsRecord: boolean): {nodeMenu?: Partial<Record<NodeKey, NodeMenu>>; nodeState?: Partial<Record<NodeKey, NodeState>>} {
  if (!ctl) return {};
  const nodeMenu: Partial<Record<NodeKey, NodeMenu>> = {
    R: {title: '다음 요청에서 중개자 R 이 할 일', current: ctl.scenario,
        options: R_ACTIONS.map(a => ({value: a.value, label: a.label, hint: SCENARIO_NAMES[a.value] || a.value, disabled: ctl.busy || !ctl.canInject})),
        note: ctl.canInject ? '실험실 배포에서만 주입된다. 여기서 고른 값은 위 「실험 조건」과 같은 값이다.' : '연결 모드에서는 공격을 주입할 수 없어 정상 경로만 선택된다.'},
  };
  if (ctl.tRunning !== null) nodeMenu.T = {title: '독립 제3자 T 의 상태', current: ctl.tRunning ? 'start' : 'stop',
    options: [{value: 'start', label: '정상적으로 판정한다', hint: 'T 서비스 가동', disabled: ctl.busy}, {value: 'stop', label: '멈춘다 (실험)', hint: 'T 서비스를 중단해 protect 와 strict 의 차이를 본다', disabled: ctl.busy}],
    note: '실제 프로세스를 종료·복구한다. 대기 증거는 큐에 보관되고 복구 뒤 재제출된다.'};
  const nodeState: Partial<Record<NodeKey, NodeState>> = {};
  const r = R_ACTIONS.find(a => a.value === (shown || 'normal'));
  if (r?.flag) nodeState.R = {flag: (shownIsRecord ? '이 요청 · ' : '다음 요청 · ') + r.flag, tone: r.tone || 'fail'};
  if (ctl.tRunning === false) nodeState.T = {flag: '지금 중단됨', tone: 'na', down: true};
  return {nodeMenu, nodeState};
}

export type RouteAction = {kind: 'scenario'; value: string} | {kind: 't-service'; running: boolean};

/** Only valid actions that are available in the current connection may leave the map. */
export function routeAction(ctl: RouteControls, node: unknown, value: unknown): RouteAction | null {
  if (ctl.busy) return null;
  if (node === 'R' && ctl.canInject && R_ACTIONS.some(a => a.value === value)) {
    return {kind: 'scenario', value: value as string};
  }
  if (node === 'T' && ctl.tRunning !== null && (value === 'start' || value === 'stop')) {
    const running = value === 'start';
    if (running !== ctl.tRunning) return {kind: 't-service', running};
  }
  return null;
}

