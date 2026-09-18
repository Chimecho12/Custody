// 경로검증 콘솔의 공용 시각 요소. 보고서(itx/report/html.py)의 구현을 앱 안으로 옮긴 것이다.
// 홉 지도 좌표는 탐색안 1a 를 그대로 쓴다. 색은 항상 실제 검사·등식 결과에서 나온다.
// Public console API. Implementation modules must import their direct dependencies.
export * from './format';
export * from './preferences';
export * from './components';
export * from './playback';
export * from './interactions';
export {
  HOP_MS, PROC_MS, SIGN_MS, MODEL_LATENCY_MS, DEFAULT_SHAPE, FILLET_R,
  computeLegs, packetPos, trailLength, trailPoints, makeSpan, filletPolyline,
  type NodeKey, type Pt, type Leg, type Span,
} from './timeline';
