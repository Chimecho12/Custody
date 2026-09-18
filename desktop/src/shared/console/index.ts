// Public console API. Implementation modules must import their direct dependencies.
export * from './format';
export * from './preferences';
export * from './components';
export * from './playback';
export * from './interactions';
export {
  HOP_MS, PROC_MS, SIGN_MS, MODEL_LATENCY_MS, DEFAULT_SHAPE,
  computeLegs, packetPos, trailLength, trailPoints, makeSpan,
  type NodeKey, type Pt, type Leg, type Span,
} from './timeline';
