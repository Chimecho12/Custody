// Playback behavior in a minimal DOM fixture. This does not claim browser/layout coverage.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const ts = require('../desktop/node_modules/typescript');
const source = ts.transpileModule(readFileSync(path.join(__dirname, '../desktop/src/console.ts'), 'utf8'), {
  compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS},
}).outputText;

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
  vm.runInContext(source, context);
  const api = context.exports;
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
  const root = new Element('section', {}, [box, controls, trail, gradient, ...lines, ...rows,
    new Element('circle', {id: 'test-packet'}), new Element('div', {'data-tlabel': ''})]);
  const playback = new api.Playback(root, 'test');
  const ctx = {legs: api.computeLegs(20, 314), tEnd: 600, span: api.makeSpan(420, 600),
    reqFail: false, respFail: false, consumedAt: null, verdictAt: null, harmExposed: false, detectable: true};
  playback.set(ctx);
  return {api, root, box, tip, play, reset, back, next, speed, trail, gradient, lines, playback, ctx, frames,
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
  f.root.emit('click', f.speed); f.playback.seek(100); f.root.emit('click', f.play);
  f.frame(16); assert.equal(f.time(), 106); // 16 ms × (600/3200) × 2배
  f.root.emit('click', f.reset); assert.equal(f.time(), 0); assert.equal(f.frames.size, 0);
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
  const report = readFileSync(path.join(__dirname, '../itx/report/html.py'), 'utf8');
  const scripts = [...report.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  assert.ok(scripts.length > 0);
  for (const [, code] of scripts) assert.doesNotThrow(() => new vm.Script(code));
});

test('standalone report pauses evidence flow and releases its scrubber capture', () => {
  const f = fixture(); f.root.listeners.clear(); f.frames.clear();
  const report = readFileSync(path.join(__dirname, '../itx/report/html.py'), 'utf8');
  const region = (start, end) => {
    const first = report.indexOf(start), last = report.indexOf(end, first);
    assert.ok(first >= 0 && last > first);
    return report.slice(first, last);
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
