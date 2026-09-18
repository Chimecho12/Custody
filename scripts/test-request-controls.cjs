// 요청 화면의 노드 메뉴 규칙. DOM 없이 순수 함수만 검사한다 — 화면 배치는 다루지 않는다.
const assert = require('node:assert/strict');
const path = require('node:path');
const {test} = require('node:test');
const {loadTypeScript} = require('./testing/load-typescript.cjs');
const {nodeControls, routeAction} = loadTypeScript(path.join(__dirname, '../desktop/src/features/request/controls'));

const lab = (over = {}) => ({scenario: 'normal', canInject: true, tRunning: true, busy: false, ...over});
const connected = (over = {}) => ({scenario: 'normal', canInject: false, tRunning: null, busy: false, ...over});
const rOptions = ctl => nodeControls(ctl, ctl.scenario, false).nodeMenu.R.options;

test('연결 모드: R 옵션이 모두 잠기고 안내도 고정이라고 말한다', () => {
  const menu = nodeControls(connected(), 'normal', false).nodeMenu.R;
  assert.ok(menu.options.every(o => o.disabled), '연결 모드에서는 어떤 옵션도 고를 수 없다');
  // 안내와 실제 상태가 어긋나면 안 된다. 하나라도 고를 수 있다면 '고정' 이 아니라 '선택' 이라고 적어야 한다.
  assert.match(menu.note, /고정된다/);
  assert.doesNotMatch(menu.note, /선택된다/);
});

test('연결 모드: 지도에서 온 R 조작은 통과하지 못한다', () => {
  assert.equal(routeAction(connected(), 'R', 'response_tamper'), null);
  assert.equal(routeAction(connected(), 'R', 'normal'), null);
});

test('실험실 · 대기 중: 옵션을 고를 수 있고 지도 조작이 통과한다', () => {
  assert.ok(rOptions(lab()).every(o => !o.disabled));
  assert.deepEqual(routeAction(lab(), 'R', 'response_tamper'), {kind: 'scenario', value: 'response_tamper'});
});

test('실행 중: 옵션이 잠기지만 안내는 실험실 문구를 유지한다', () => {
  const menu = nodeControls(lab({busy: true}), 'normal', false).nodeMenu.R;
  assert.ok(menu.options.every(o => o.disabled), '실행 중에는 다음 조건을 바꾸지 못한다');
  // 잠금은 연결 종류가 아니라 진행 상태다 — 실험실에 있는데 연결 모드 안내가 나오면 안 된다.
  assert.match(menu.note, /실험실 배포에서만/);
  assert.equal(routeAction(lab({busy: true}), 'R', 'response_tamper'), null);
});

test('T 메뉴는 실험실에서만 있고, 같은 상태로는 전환하지 않는다', () => {
  assert.equal(nodeControls(connected(), 'normal', false).nodeMenu.T, undefined);
  assert.deepEqual(routeAction(lab({tRunning: true}), 'T', 'stop'), {kind: 't-service', running: false});
  assert.equal(routeAction(lab({tRunning: true}), 'T', 'start'), null, '이미 가동 중이면 전환하지 않는다');
  assert.equal(routeAction(lab({tRunning: true, busy: true}), 'T', 'stop'), null);
});

test('노드 표식은 지금 고른 조건과 지나간 기록을 구분한다', () => {
  assert.equal(nodeControls(lab(), 'response_tamper', false).nodeState.R.flag, '다음 요청 · 응답 변조');
  assert.equal(nodeControls(lab(), 'response_tamper', true).nodeState.R.flag, '이 요청 · 응답 변조');
  assert.equal(nodeControls(lab(), 'normal', false).nodeState.R, undefined, '정상 경로에는 표식을 붙이지 않는다');
  assert.equal(nodeControls(lab({tRunning: false}), 'normal', false).nodeState.T.down, true);
});
