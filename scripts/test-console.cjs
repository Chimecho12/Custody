// Playback behavior in a minimal DOM fixture. This does not claim browser/layout coverage.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const {loadTypeScript} = require('./testing/load-typescript.cjs');
// 보고서 콘솔의 스크립트. itx/report/html.py 가 이 파일을 그대로 인라인한다.
const reportScript = readFileSync(path.join(__dirname, '../itx/report/assets/report.js'), 'utf8');

class Element {
  constructor(tag = 'div', attributes = {}, children = []) {
    this.tag = tag; this.attributes = new Map(Object.entries(attributes));
    this.dataset = Object.fromEntries(Object.entries(attributes).filter(([key]) => key.startsWith('data-'))
      .map(([key, value]) => [key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase()), value]));
    const classes = new Set((attributes.class || '').split(' ').filter(Boolean));
    this.classList = {contains: name => classes.has(name), add: (...names) => names.forEach(n => classes.add(n)),
      remove: (...names) => names.forEach(n => classes.delete(n)), toggle: (name, on = !classes.has(name)) => {
        if (on) classes.add(name); else classes.delete(name); return on;
      }};
    this.children = children; children.forEach(child => { child.parent = this; });
    this.style = {}; this.hidden = false; this.isConnected = true; this.textContent = '';
    this.offsetWidth = 200; this.rect = {left: 100, width: 400};
    this.listeners = new Map(); this.captures = new Set();
  }
  matches(selector) {
    return selector.split(',').some(part => {
      const s = part.trim();
      const tag = s.match(/^[a-z]+/i)?.[0];
      if (tag && tag !== this.tag) return false;
      if ([...s.matchAll(/#([\w-]+)/g)].some(([, id]) => this.getAttribute('id') !== id)) return false;
      if ([...s.matchAll(/\.([\w-]+)/g)].some(([, name]) => !this.classList.contains(name))) return false;
      return [...s.matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)]
        .every(([, key, value]) => this.hasAttribute(key) && (value === undefined || this.getAttribute(key) === value));
    });
  }
  closest(selector) { return this.matches(selector) ? this : this.parent?.closest(selector) ?? null; }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
  contains(child) { return child === this || this.children.some(item => item.contains(child)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  setAttribute(name, value) { this.attributes.set(name, value); }
  hasAttribute(name) { return this.attributes.has(name); }
  getBoundingClientRect() { return this.rect; }
  setPointerCapture(id) { this.captures.add(id); }
  hasPointerCapture(id) { return this.captures.has(id); }
  releasePointerCapture(id) { this.captures.delete(id); }
  focus() { this.focused = true; }
  addEventListener(type, callback) { const list = this.listeners.get(type) || []; list.push(callback); this.listeners.set(type, list); }
  emit(type, target, fields = {}) {
    const event = {target, button: 0, isPrimary: true, pointerId: 1, clientX: 300,
      defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...fields};
    for (const callback of this.listeners.get(type) || []) callback(event);
    return event;
  }
}

function fixture() {
  const frames = new Map(); let serial = 0; let motionChanged;
  const context = vm.createContext({exports: {}, window: {matchMedia: () => ({matches: false,
    addEventListener: (_, callback) => { motionChanged = callback; }})},
    requestAnimationFrame: callback => { frames.set(++serial, callback); return serial; },
    cancelAnimationFrame: id => frames.delete(id)});
  const api = loadTypeScript(path.join(__dirname, '../desktop/src/shared/console'), context);
  const tip = new Element('div', {'data-scrubtip': ''}); tip.hidden = true;
  const box = new Element('div', {'data-scrub': '', role: 'slider'}, [tip]);
  const play = new Element('button', {'data-play': ''});
  const reset = new Element('button', {'data-reset': ''});
  const back = new Element('button', {'data-step': '-1'});
  const next = new Element('button', {'data-step': '1'});
  const speed = new Element('button', {'data-speed': ''});
  const controls = new Element('div', {class: 'playctl'}, [reset, back, play, next, speed]);
  const trail = new Element('polyline', {id: 'test-trail', class: 'packettrail'});
  const gradient = new Element('linearGradient', {id: 'test-trail-gradient'});
  const lines = ['U', 'R', 'M'].map(key => new Element('line', {id: `test-ev${key}`, class: 'evline'}));
  const rows = ['U', 'R', 'M'].map(key => new Element('div', {class: `evrow${key === 'M' ? ' absent-row' : ''}`,
    'data-ev-key': key, ...(key === 'M' ? {} : {'data-ev-reg': '10'})}, [new Element('span', {class: 'evstate'})]));
  const nodes = ['U', 'R', 'M'].map(key => new Element('div', {class: 'fcnode', 'data-node': key}));
  const root = new Element('section', {}, [box, controls, trail, gradient, ...lines, ...rows, ...nodes,
    new Element('circle', {id: 'test-ripple', class: 'packet-ripple'}), new Element('circle', {id: 'test-aura', class: 'packet-aura'}),
    new Element('circle', {id: 'test-packet', class: 'packet'}), new Element('div', {'data-tlabel': ''})]);
  const playback = new api.Playback(root, 'test');
  const ctx = {legs: api.computeLegs(20, 314), tEnd: 600, span: api.makeSpan(420, 600),
    reqFail: false, respFail: false, consumedAt: null, verdictAt: null, harmExposed: false, detectable: true};
  playback.set(ctx);
  return {api, root, box, tip, play, reset, back, next, speed, trail, gradient, lines, nodes, playback, ctx, frames,
    time: () => Number(box.getAttribute('aria-valuenow')),
    frame: ts => { const [id, callback] = frames.entries().next().value; frames.delete(id); callback(ts); },
    reduce: matches => motionChanged({matches})};
}

test('primary pointer seeks immediately, focuses and shows a bounded tooltip', () => {
  const f = fixture();
  for (const x of [100, 300, 500]) {
    f.root.emit('pointerdown', f.box, {clientX: x});
    assert.equal(f.time(), Math.round(f.ctx.span.inv((x - 100) / 4)));
    assert.equal(f.box.focused, true); assert.equal(f.tip.hidden, false);
    const center = parseFloat(f.tip.style.left);
    assert.ok(center >= f.tip.offsetWidth / 2 && center <= 400 - f.tip.offsetWidth / 2);
    f.root.emit('pointerup', f.box, {clientX: x});
    assert.equal(f.tip.hidden, true); assert.equal(f.box.captures.size, 0);
  }
});

test('right click and secondary touch cannot seek or steal a drag', () => {
  const f = fixture();
  f.root.emit('pointerdown', f.box, {button: 2});
  f.root.emit('pointerdown', f.box, {isPrimary: false, pointerId: 2});
  assert.equal(f.time(), 600); assert.equal(f.box.captures.size, 0);
  f.root.emit('pointerdown', f.box, {clientX: 200}); const before = f.time();
  f.root.emit('pointermove', f.box, {pointerId: 2, clientX: 500});
  f.root.emit('pointerup', f.box, {pointerId: 2});
  assert.equal(f.time(), before); assert.equal(f.box.hasPointerCapture(1), true);
  f.root.emit('pointermove', f.box, {clientX: 500}); assert.equal(f.time(), 600);
});

test('cancel, lost capture and selection changes end scrubbing', () => {
  for (const end of ['pointercancel', 'lostpointercapture', 'selection']) {
    const f = fixture(); f.root.emit('pointerdown', f.box, {clientX: 200});
    if (end === 'selection') f.playback.set(f.ctx); else f.root.emit(end, f.box);
    const before = f.time();
    assert.equal(f.tip.hidden, true); assert.equal(f.box.captures.size, 0);
    f.root.emit('pointermove', f.box, {clientX: 500}); assert.equal(f.time(), before);
  }
});

test('pause cancels the frame and stops evidence animation, including missing evidence', () => {
  const f = fixture(); f.playback.seek(100); f.playback.toggle(); f.frame(16);
  assert.equal(f.lines[0].classList.contains('flowing'), true);
  assert.equal(f.lines[2].classList.contains('flowing'), false);
  assert.equal(f.lines[0].getAttribute('stroke'), 'var(--accent)');
  f.playback.toggle();
  assert.equal(f.frames.size, 0); assert.equal(f.play.getAttribute('aria-pressed'), 'false');
  assert.ok(f.lines.every(line => !line.classList.contains('flowing')));
});

test('keyboard hop navigation is scoped, preserves shortcuts, and ignores held Space', () => {
  const f = fixture(); f.playback.seek(0);
  f.root.emit('keydown', f.box, {key: 'ArrowRight'}); assert.equal(f.time(), 20);
  f.root.emit('keydown', f.box, {key: 'ArrowLeft'}); assert.equal(f.time(), 0);
  f.root.emit('keydown', f.box, {key: 'End'}); assert.equal(f.time(), 600);
  assert.equal(f.root.emit('keydown', f.box, {key: 'r', ctrlKey: true}).defaultPrevented, false);
  assert.equal(f.time(), 600);
  f.root.emit('keydown', f.box, {key: 'R'}); assert.equal(f.time(), 0);
  f.root.emit('keydown', new Element('input'), {key: 'End'}); assert.equal(f.time(), 0);
  f.root.emit('keydown', f.box, {key: ' '}); assert.equal(f.frames.size, 1);
  f.root.emit('keydown', f.box, {key: ' ', repeat: true}); assert.equal(f.frames.size, 1);
  f.root.emit('keydown', f.box, {key: ' '}); assert.equal(f.frames.size, 0);
});

test('step/reset buttons and speed control affect playback', () => {
  const f = fixture();
  f.root.emit('click', f.reset); assert.equal(f.time(), 0);
  f.root.emit('click', f.next); assert.equal(f.time(), 20);
  f.root.emit('click', f.back); assert.equal(f.time(), 0);
  for (const label of ['2×', '0.5×', '1×']) {
    f.root.emit('click', f.speed); assert.equal(f.speed.textContent, label);
  }
  // 속도는 벽시계 진행량을 곱한다: 같은 자리에서 한 프레임(16 ms) 간 t 의 전진이 2× 에서 두 배다.
  const advance = (times) => { f.root.emit('click', f.reset); f.playback.seek(100); f.root.emit('click', f.play); f.frame(16); const d = f.time() - 100; f.root.emit('click', f.play); return d; };
  const at1 = advance(); // 현재 배속 1×
  f.root.emit('click', f.speed); assert.equal(f.speed.textContent, '2×');
  const at2 = advance();
  assert.ok(at1 > 0 && Math.abs(at2 - 2 * at1) <= 1, `2× 전진(${at2})은 1× 전진(${at1})의 두 배여야 한다`);
  f.root.emit('click', f.reset); assert.equal(f.time(), 0); assert.equal(f.frames.size, 0);
});

test('playback paces hops to a perceptual floor and caps long stays, while t stays real', () => {
  const f = fixture();
  const legs = f.ctx.legs, sched = f.api.paceSchedule(legs, f.ctx.tEnd);
  // 배분표는 실측 t 를 그대로 잇는다 — 어떤 구간도 t 를 왜곡하지 않는다.
  assert.equal(sched[0].t0, 0); assert.equal(sched[sched.length - 1].t1, f.ctx.tEnd);
  for (let i = 1; i < sched.length; i++) assert.equal(sched[i].t0, sched[i - 1].t1);
  const wallOf = (L) => { const s = sched.find(x => x.t0 === L.t0 && x.t1 === L.t1); return s.p1 - s.p0; };
  for (const L of legs.filter(l => !l.work)) assert.ok(wallOf(L) >= 450, `홉 이동 구간은 최소 450 ms 의 벽시계를 받는다 (${wallOf(L)})`);
  assert.ok(wallOf(legs[3]) <= 800, `추론 구간은 800 ms 를 넘지 않는다 (${wallOf(legs[3])})`);
  // 실제 재생: 20 ms 짜리 첫 홉을 지나는 데 최소 28 프레임(≈450 ms)이 걸린다.
  f.playback.seek(0); f.root.emit('click', f.play);
  let frames = 0; while (f.time() < legs[0].t1 && frames < 200) { f.frame(16 * (frames + 1)); frames++; }
  assert.ok(frames >= 28, `첫 홉을 지나는 프레임 수 ${frames}`);
  assert.equal(f.frames.size, 1); // 여전히 재생 중
  // 뒤로 스크러빙한 뒤 재생하면 그 자리의 벽시계에서 이어 간다 (t 가 튀지 않는다).
  f.root.emit('click', f.play); f.playback.seek(legs[1].t0); f.root.emit('click', f.play); f.frame(9999);
  assert.ok(f.time() > legs[1].t0 && f.time() < legs[1].t1 + 1, `이어 재생 뒤 t=${f.time()}`);
  f.root.emit('click', f.play);
});

test('tamper ripple fires once on the colour change and the reached node absorbs the packet', () => {
  const f = fixture(); f.ctx.reqFail = true; f.playback.set(f.ctx);
  const packet = f.root.querySelector('#test-packet'), aura = f.root.querySelector('#test-aura'), ripple = f.root.querySelector('#test-ripple');
  const legs = f.ctx.legs, R = f.nodes[1];
  // 스크러빙(정지 상태)으로 변조 구간에 들어가면 색만 바뀌고 파문은 없다.
  f.playback.seek(legs[1].t0 + 1);
  assert.equal(packet.getAttribute('fill'), 'var(--fail)'); assert.equal(aura.getAttribute('fill'), 'var(--fail)');
  assert.equal(ripple.classList.contains('go'), false); assert.equal(packet.classList.contains('hit'), false);
  // 재생 중 색이 바뀌는 프레임에는 파문·흔들림이 한 번 붙고, 도달 상자는 흡수, 일하는 상자는 호흡한다.
  f.playback.seek(legs[0].t0 + 1); f.root.emit('click', f.play);
  let n = 0; while (!ripple.classList.contains('go') && n < 400) f.frame(16 * ++n);
  assert.ok(n < 400, '재생 중 변조 구간에 들어서며 파문이 난다');
  assert.equal(packet.classList.contains('hit'), true);
  assert.equal(R.classList.contains('arrive'), true, '패킷이 닿은 R 상자가 흡수한다');
  assert.equal(ripple.getAttribute('cx'), packet.getAttribute('cx'));
  // 호흡(.working)은 캔버스(flow.ts · report fcRings)가 프레임마다 붙이므로 엔진 픽스처에서는 보지 않는다.
  assert.equal(packet.classList.contains('docked'), true);
  // 정지하면 호흡·흡수 클래스가 걷힌다. 파문은 CSS 가 스스로 끝낸다.
  f.root.emit('click', f.play);
  assert.equal(f.root.querySelectorAll('.fcnode.working, .fcnode.arrive').length, 0);
  // 다시 처음부터 재생해도 파문은 색이 바뀌는 순간에만 다시 난다 (변조 구간 안에서는 반복되지 않는다).
  f.playback.seek(legs[2].t0 + 1); ripple.classList.remove('go'); f.root.emit('click', f.play);
  f.frame(16); f.frame(32); assert.equal(ripple.classList.contains('go'), false); f.root.emit('click', f.play);
});

test('packet paths round their corners with the same radius the drawn edges use', () => {
  const f = fixture();
  const sq = [[0, 0], [100, 0], [100, 100]];
  const pts = f.api.filletPolyline(sq, 14);
  assert.equal(JSON.stringify(pts[0]), '[0,0]'); assert.equal(JSON.stringify(pts[pts.length - 1]), '[100,100]');
  assert.ok(pts.length > 3 && !pts.some(p => p[0] === 100 && p[1] === 0), '직각 꼭짓점 자체는 지나지 않는다');
  assert.equal(JSON.stringify(f.api.filletPolyline([[0, 0], [10, 10]])), '[[0,0],[10,10]]');
  assert.ok(f.ctx.legs[0].pts.length > 3, '이동 구간의 꺾은선이 둥글려졌다');
});

test('live reduced-motion changes finish playback and prevent another animation', () => {
  const f = fixture(); f.playback.seek(30); f.playback.toggle();
  f.reduce(true); f.frame(16);
  assert.equal(f.time(), 600); assert.equal(f.frames.size, 0); assert.equal(f.trail.style.opacity, '0');
  f.playback.seek(30); f.playback.toggle(); assert.equal(f.time(), 600); assert.equal(f.frames.size, 0);
});

test('playback does not continue on a hidden view', () => {
  const f = fixture(); f.playback.toggle(); f.root.hidden = true; f.frame(16);
  assert.equal(f.frames.size, 0); assert.equal(f.play.getAttribute('aria-pressed'), 'false');
});

test('comet trail follows a corner with a transparent tail behind the packet', () => {
  const f = fixture();
  const points = f.api.trailPoints(75, [{t0: 0, t1: 100, pts: [[0, 0], [10, 0], [10, 10]], work: false}], 12);
  assert.equal(JSON.stringify(points), JSON.stringify([[10, 7.5], [10, 0], [5.5, 0]]));
  f.playback.seek(30);
  assert.ok(Number(f.gradient.getAttribute('x1')) < Number(f.gradient.getAttribute('x2')));
  assert.equal(f.gradient.style.color, 'var(--accent)'); assert.equal(f.trail.style.opacity, '1');
  f.playback.seek(0); assert.equal(f.trail.style.opacity, '0');
  f.playback.seek(314); assert.equal(f.trail.style.opacity, '0');
});

test('slider and hover announce before-send and after-receive consistently', () => {
  const f = fixture();
  f.playback.seek(0); assert.match(f.box.getAttribute('aria-valuetext'), /전송 전/);
  f.root.emit('pointermove', f.box, {clientX: 100}); assert.match(f.tip.textContent, /전송 전/);
  f.playback.seek(600); assert.match(f.box.getAttribute('aria-valuetext'), /응답 수신 후/);
  f.root.emit('pointermove', f.box, {clientX: 500}); assert.match(f.tip.textContent, /응답 수신 후/);
});

test('standalone report JavaScript compiles after the shared interaction changes', () => {
  assert.doesNotThrow(() => new vm.Script(reportScript));
});

test('standalone report pauses evidence flow and releases its scrubber capture', () => {
  const f = fixture(); f.root.listeners.clear(); f.frames.clear();
  const region = (start, end) => {
    const first = reportScript.indexOf(start), last = reportScript.indexOf(end, first);
    assert.ok(first >= 0 && last > first);
    return reportScript.slice(first, last);
  };
  const aliases = {'#playBtn': f.play, '#resetBtn': f.reset, '#stepBackBtn': f.back, '#stepFwdBtn': f.next,
    '#speedBtn': f.speed, '#itxScrubTip': f.tip, '#itxTimebox': f.box, '#itxTrail': f.trail,
    '#itxTrailGradient': f.gradient, '#tLabel': f.root.querySelector('[data-tlabel]'),
    '#itxPacket': f.root.querySelector('#test-packet'), '#itxEvU': f.lines[0], '#itxEvR': f.lines[1], '#itxEvM': f.lines[2]};
  let serial = 0;
  const context = vm.createContext({document: f.root, $: selector => aliases[selector] ?? null,
    window: {matchMedia: () => ({matches: false, addEventListener() {}})},
    requestAnimationFrame: callback => { f.frames.set(++serial, callback); return serial; },
    cancelAnimationFrame: id => f.frames.delete(id),
    packetPos: f.api.packetPos, trailPoints: f.api.trailPoints, trailLength: f.api.trailLength,
    CV: f.api.CV, input: f.ctx});
  vm.runInContext(region('// ---------- 재생 엔진', '// ---------- 홉 지도')
    + region('function pulseNode(', '// ---------- 1b 스윔레인'), context);
  vm.runInContext('PB = {...input, eq:{}, t:100, fired:new Set(), evFired:new Set(), primed:false, fill:""}; togglePlay();', context);
  f.frame(16); assert.equal(f.lines[0].classList.contains('flowing'), true);
  vm.runInContext('togglePlay();', context);
  assert.equal(f.frames.size, 0); assert.equal(f.lines[0].classList.contains('flowing'), false);
  f.root.emit('pointerdown', f.box, {clientX: 100});
  assert.equal(f.time(), 0); assert.equal(f.tip.hidden, false);
  assert.ok(parseFloat(f.tip.style.left) >= f.tip.offsetWidth / 2);
  f.root.emit('pointermove', f.box, {clientX: 500}); assert.equal(f.time(), 600);
  f.root.emit('lostpointercapture', f.box);
  assert.equal(f.tip.hidden, true); assert.equal(f.box.captures.size, 0);
});
