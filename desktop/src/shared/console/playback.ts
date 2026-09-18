import { CV } from './format';
import { reducedMotion } from './preferences';
import { packetPos, packetLabel, trailLength, trailPoints, type Leg, type NodeKey, type Span } from './timeline';

// ---------- 재생 엔진 ----------
export interface PlayContext {
  legs: Leg[]; tEnd: number; span: Span;
  reqFail: boolean; respFail: boolean;
  consumedAt: number | null; verdictAt: number | null; harmExposed: boolean; detectable: boolean;
}
const SPEEDS = [0.5, 1, 2];
export class Playback {
  private t = 0; private playing = false; private raf = 0; private last: number | null = null; private ctx: PlayContext | null = null;
  private speed = 1; private fired = new Set<number>(); private fill = '';
  private scrub: {box: HTMLElement; pointerId: number} | null = null;
  private prev: {x: number; y: number} | null = null;
  private evFired = new Set<string>(); private primed = false;
  constructor(private root: HTMLElement, private key: string) {
    root.addEventListener('click', e => {
      const b = (e.target as HTMLElement).closest('button');
      if (!b || !root.contains(b)) return;
      if (b.hasAttribute('data-play')) this.toggle();
      else if (b.hasAttribute('data-reset')) { this.stop(); this.seek(0); }
      else if (b.hasAttribute('data-step')) { this.stop(); this.step(+b.getAttribute('data-step')!); }
      else if (b.hasAttribute('data-speed')) { this.speed = SPEEDS[(SPEEDS.indexOf(this.speed) + 1) % SPEEDS.length]; this.button(); }
    });
    // 시점 타임라인 스크러버: 누른 자리로 바로 이동하고 드래그로 따라간다.
    root.addEventListener('pointerdown', e => {
      const box = (e.target as HTMLElement).closest<HTMLElement>('[data-scrub]');
      if (!box || !this.ctx || e.button !== 0 || !e.isPrimary || this.scrub) return;
      e.preventDefault(); this.stop(); this.scrub = {box, pointerId: e.pointerId};
      box.setPointerCapture(e.pointerId); box.focus();
      this.seekAt(box, e.clientX); this.tip(box, e.clientX);
    });
    // 커서가 타임라인 위에 있으면 그 자리의 시점·홉 상태를 툴팁으로 보인다. 드래그 중에는 재생 헤드가 그 자리다.
    root.addEventListener('pointermove', e => {
      if (this.scrub) {
        if (e.pointerId === this.scrub.pointerId) { this.seekAt(this.scrub.box, e.clientX); this.tip(this.scrub.box, e.clientX); }
        return;
      }
      if (!e.isPrimary) return;
      const box = (e.target as HTMLElement).closest<HTMLElement>('[data-scrub]');
      if (box) this.tip(box, e.clientX); else this.tip(null);
    });
    root.addEventListener('pointerleave', () => { if (!this.scrub) this.tip(null); });
    const end = (e: PointerEvent) => { if (this.scrub?.pointerId === e.pointerId) this.endScrub(); };
    root.addEventListener('pointerup', e => {
      if (this.scrub?.pointerId === e.pointerId) { this.seekAt(this.scrub.box, e.clientX); this.endScrub(); }
    });
    root.addEventListener('pointercancel', end);
    root.addEventListener('lostpointercapture', end);
    // 키보드: 스크러버나 재생 컨트롤에 초점이 있을 때만 받는다. 입력란의 방향키를 빼앗지 않는다.
    root.addEventListener('keydown', e => {
      const target = e.target as HTMLElement;
      if (e.defaultPrevented || e.isComposing || e.altKey || e.ctrlKey || e.metaKey) return;
      if (!target.closest('[data-scrub]') && !target.closest('.playctl')) return;
      if (e.key === ' ' || e.key === 'Spacebar') { if (target.closest('button')) return; e.preventDefault(); if (!e.repeat) this.toggle(); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); this.stop(); this.step(-1); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); this.stop(); this.step(1); }
      else if (e.key === 'Home' || e.key === 'r' || e.key === 'R') { e.preventDefault(); this.stop(); this.seek(0); }
      else if (e.key === 'End' && this.ctx) { e.preventDefault(); this.stop(); this.seek(this.ctx.tEnd); }
    });
  }
  // 선택이 바뀌면 완결된 최종 상태에서 시작한다. 이때는 도달 펄스를 내지 않는다 — 방금 일어난 일이 아니다.
  set(ctx: PlayContext | null) {
    this.endScrub(); this.stop(); this.ctx = ctx; this.t = ctx ? ctx.tEnd : 0; this.fill = '';
    this.fired = new Set(ctx ? ctx.legs.map((_, i) => i) : []);
    this.evFired.clear(); this.primed = false; this.prev = null;
    this.button(); this.update();
  }
  // 캔버스가 노드를 접거나 배치를 바꾸면 같은 시점에서 새 기하로 다시 그린다.
  setLegs(legs: Leg[]) { if (!this.ctx) return; this.ctx.legs = legs; this.fill = ''; this.prev = null; this.update(); }
  stop() {
    this.playing = false; if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0; this.last = null; this.prev = null;
    this.root.querySelectorAll('.flowing, .pulse, .settling').forEach(el => el.classList.remove('flowing', 'pulse', 'settling'));
    this.tip(null); this.button();
  }
  toggle() {
    if (!this.ctx) return;
    if (reducedMotion) { this.stop(); this.seek(this.ctx.tEnd); return; } // 축소 모션: 최종 상태로 즉시 점프
    if (this.playing) { this.stop(); return; }
    if (this.t >= this.ctx.tEnd) this.seek(0);
    this.playing = true; this.last = null; this.button();
    this.raf = requestAnimationFrame(ts => this.step2(ts));
  }
  seek(v: number) {
    if (!this.ctx) return;
    const next = Math.max(0, Math.min(this.ctx.tEnd, v));
    if (next < this.t) for (const i of [...this.fired]) if (this.ctx.legs[i].t1 > next) this.fired.delete(i);
    this.t = next; this.update();
  }
  // 홉 경계(구간 시작·끝)로만 이동한다. 어떤 구간에서 무엇이 바뀌는지 한 걸음씩 확인하는 용도다.
  step(dir: number) {
    if (!this.ctx) return;
    const marks = [...new Set([0, ...this.ctx.legs.map(l => l.t0), ...this.ctx.legs.map(l => l.t1), this.ctx.tEnd])]
      .filter(v => v >= 0 && v <= this.ctx!.tEnd).sort((a, b) => a - b);
    const eps = 0.5;
    const next = dir > 0 ? marks.find(v => v > this.t + eps) : [...marks].reverse().find(v => v < this.t - eps);
    this.seek(next ?? (dir > 0 ? this.ctx.tEnd : 0));
  }
  private seekAt(box: HTMLElement, clientX: number) {
    if (!this.ctx) return;
    const r = box.getBoundingClientRect();
    if (r.width <= 0) return;
    this.seek(this.ctx.span.inv(((clientX - r.left) / r.width) * 100));
  }
  private endScrub() {
    const active = this.scrub; this.scrub = null;
    if (active?.box.hasPointerCapture(active.pointerId)) active.box.releasePointerCapture(active.pointerId);
    this.tip(null);
  }
  // 툴팁은 커서 아래 시점을 말한다: 어느 구간인지, 전송 전인지, 수신 후인지. 판정은 말하지 않는다.
  private tip(box: HTMLElement | null, clientX = 0) {
    if (!box || !this.ctx) { this.root.querySelectorAll<HTMLElement>('[data-scrubtip]').forEach(el => { el.hidden = true; }); return; }
    const el = box.querySelector<HTMLElement>('[data-scrubtip]');
    if (!el) return;
    const r = box.getBoundingClientRect();
    if (r.width <= 0) { el.hidden = true; return; }
    const pct = Math.max(0, Math.min(100, ((clientX - r.left) / r.width) * 100));
    const t = this.scrub ? this.t : this.ctx.span.inv(pct);
    el.textContent = `t = ${Math.round(t)} ms · ${packetLabel(t, this.ctx.legs)}`;
    el.hidden = false;
    const half = el.offsetWidth / 2 + 4;
    const x = (this.scrub ? this.ctx.span(t) : pct) / 100 * r.width;
    el.style.left = Math.max(half, Math.min(r.width - half, x)).toFixed(1) + 'px';
  }
  private step2(ts: number) {
    if (!this.playing || !this.ctx) return;
    if (this.root.hidden || !this.root.isConnected) { this.stop(); return; }
    if (reducedMotion) { this.stop(); this.seek(this.ctx.tEnd); return; }
    const dt = this.last != null ? Math.min(64, ts - this.last) : 16; this.last = ts;
    const base = Math.max(0.05, this.ctx.tEnd / 3200); // 실측 길이와 무관하게 ×1 재생은 약 3초, 구간 비율은 실제 값 그대로
    let nt = this.t + dt * base * this.speed;
    if (nt >= this.ctx.tEnd) { nt = this.ctx.tEnd; this.playing = false; }
    this.seek(nt);
    if (this.playing) this.raf = requestAnimationFrame(t => this.step2(t)); else this.button();
  }
  private button() {
    const b = this.root.querySelector<HTMLButtonElement>('button[data-play]');
    if (b) { b.textContent = this.playing ? '❚❚ 일시정지' : '▶ 재생'; b.setAttribute('aria-pressed', String(this.playing)); }
    const s = this.root.querySelector<HTMLButtonElement>('button[data-speed]');
    if (s) s.textContent = this.speed + '×';
  }
  private pulse(node: NodeKey) {
    // flow.ts 의 HTML 노드가 있으면 그 노드에, 없으면(옛 SVG 지도) halo 사각형에 1회성 펄스를 낸다.
    const el = this.root.querySelector<HTMLElement>(`.flow-node[data-node="${node}"]`) || this.root.querySelector<SVGElement>(`#${this.key}-halo-${node}`);
    if (!el) return;
    el.classList.remove('pulse'); void el.getBoundingClientRect(); el.classList.add('pulse');
  }
  // 패킷 위치·잔상·색, 증거 도달선, 재생 헤드, 피해 막대만 갱신한다. 나머지는 정적이다.
  update() {
    const label = this.root.querySelector<HTMLElement>('[data-tlabel]');
    const c = this.ctx;
    if (!c) { if (label) label.textContent = 't = 0 ms'; return; }
    const t = this.t, lastLeg = c.legs[c.legs.length - 1];
    if (label) label.textContent = `t = ${Math.round(t)} ms · ${packetLabel(t, c.legs)}`; // 원안: t 라벨에 현재 구간
    const pos = packetPos(t, c.legs);
    let fill = 'accent';
    if (t >= lastLeg.t1) fill = 'muted';
    if (c.reqFail && t >= c.legs[1].t0 && t < c.legs[4].t0) fill = 'fail';
    if (c.respFail && t >= c.legs[5].t0) fill = 'fail'; // 원안: 응답 변조는 M→R 구간부터 붉다
    const changed = fill !== this.fill; this.fill = fill;

    const dot = this.root.querySelector<SVGElement>(`#${this.key}-packet`);
    if (dot) {
      dot.setAttribute('cx', pos.x.toFixed(1)); dot.setAttribute('cy', pos.y.toFixed(1));
      if (changed) {
        dot.setAttribute('fill', CV(fill));
        // 글로우는 패킷 색을 따른다. 도착해 멈춘 뒤(muted)에는 빛나지 않는다.
        dot.style.filter = fill === 'muted' ? 'none' : `drop-shadow(0 0 6px ${CV(fill + '-glow')})`;
      }
    }
    // 홉 구간은 추론 구간보다 10배 짧아 한 프레임에 크게 건너뛴다. 재생 중에는 그 간격만큼 꼬리를 늘려
    // 이동이 끊겨 보이지 않게 한다 — 속도를 그대로 드러내는 것이고 판정과는 무관하다. 기본 길이는 20px.
    const jump = this.prev ? Math.hypot(pos.x - this.prev.x, pos.y - this.prev.y) : 0;
    this.prev = {x: pos.x, y: pos.y};
    const base = this.playing ? Math.max(22, Math.min(46, jump * 1.6)) : 22; // 원안 값
    const inTransit = !reducedMotion && t > c.legs[0].t0 && t < lastLeg.t1;
    const full = inTransit ? trailLength(t, c.legs, base) : 0;
    // 실제 SVG 그라데이션을 꼬리→패킷 방향으로 정렬한다. 꺾은선의 좌표는 그대로 유지한다.
    const layer = this.root.querySelector<SVGElement>(`#${this.key}-trail`);
    const gradient = this.root.querySelector<SVGElement>(`#${this.key}-trail-gradient`);
    if (layer && gradient) {
      const pts = full > 0.5 ? trailPoints(t, c.legs, full) : [];
      layer.setAttribute('points', pts.map(p => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' '));
      if (changed) gradient.style.color = CV(fill);
      if (pts.length > 1) {
        const tail = pts[pts.length - 1];
        gradient.setAttribute('x1', String(tail[0])); gradient.setAttribute('y1', String(tail[1]));
        gradient.setAttribute('x2', String(pos.x)); gradient.setAttribute('y2', String(pos.y));
      }
      layer.style.opacity = pts.length > 1 ? '1' : '0';
    }
    const moving = t > c.legs[0].t0 && t < lastLeg.t1;
    const plabel = this.root.querySelector<HTMLElement>('[data-packetlabel]');
    if (plabel) {
      plabel.hidden = !moving;
      if (moving) {
        plabel.textContent = pos.leg.label;
        if (plabel.hasAttribute('data-px')) { // flow 뷰포트 안에서는 그래프 좌표(px)를 그대로 쓴다
          plabel.style.left = pos.x.toFixed(1) + 'px'; plabel.style.top = pos.y.toFixed(1) + 'px';
          plabel.style.transform = pos.y < 100 ? 'translate(-50%,-190%)' : 'translate(-50%,90%)';
        } else {
          plabel.style.left = (pos.x / 820 * 100).toFixed(2) + '%';
          plabel.style.top = (pos.y / 360 * 100).toFixed(2) + '%';
          plabel.style.transform = pos.y < 150 ? 'translate(-50%,-180%)' : 'translate(-50%,80%)';
        }
      }
    }
    // 노드 상태: 패킷이 머무는 노드만 active (X6 식 상태 표시). 미니맵의 점도 같이 옮긴다.
    // 캔버스(flow.ts)에 프레임을 알린다 — 도달 링 감쇠·상태 머신은 그쪽이 그린다. 재생 엔진은 캔버스를 모른다.
    const flow = this.root.querySelector<HTMLElement>(`.flowc[data-flow="${this.key}"]`);
    if (flow && typeof CustomEvent === 'function' && typeof flow.dispatchEvent === 'function') flow.dispatchEvent(new CustomEvent('playbackframe', {bubbles: true, detail: {t, legs: c.legs, playing: this.playing}}));
    if (!reducedMotion) for (let i = 0; i < c.legs.length; i++) {
      const L = c.legs[i];
      if (L.arrive && !this.fired.has(i) && t >= L.t1) { this.fired.add(i); if (this.playing) this.pulse(L.arrive); }
    }
    for (const k of ['U', 'R', 'M']) {
      const line = this.root.querySelector<SVGElement>(`#${this.key}-ev${k}`);
      const row = this.root.querySelector<HTMLElement>(`.evrow[data-ev-key="${k}"]`);
      if (!line) continue;
      const reg = row?.dataset.evReg;
      const missing = !row || row.classList.contains('absent-row');
      const registered = !missing && reg !== undefined && t >= +reg;
      const want = missing ? CV('na') : registered ? CV('accent') : CV('line');
      if (line.getAttribute('stroke') !== want) line.setAttribute('stroke', want);
      // 증거 제출 경로임을 업무 데이터 경로와 구분해 보인다: 재생 중이고 이미 등록된 선만 흐른다.
      // 결손 선은 어떤 경우에도 움직이지 않는다.
      line.classList.toggle('flowing', registered && this.playing && !reducedMotion);
      if (registered && !this.evFired.has(k)) { this.evFired.add(k); if (this.playing && this.primed && !reducedMotion) this.pulse('T'); }
      if (!registered) this.evFired.delete(k);
    }
    // 등록 여부는 클래스만 바꾸고 색 전이는 CSS 가 맡는다 (프레임마다 인라인 스타일을 쓰면 전이가 끊긴다).
    this.root.querySelectorAll<HTMLElement>('.evrow[data-ev-reg]').forEach(row => {
      const reg = +row.dataset.evReg!, arrived = t >= reg;
      if (row.classList.contains('arrived') === arrived) return;
      row.classList.toggle('arrived', arrived);
      // 이미 끝난 사건을 불러올 때(primed 이전)는 안착 애니메이션을 내지 않는다 — 방금 등록된 것이 아니다.
      row.classList.toggle('settling', arrived && this.playing && this.primed && !reducedMotion);
      const state = row.querySelector<HTMLElement>('.evstate')!;
      state.textContent = arrived ? `등록 ≤ ${reg} ms` : '대기';
    });
    this.primed = true;
    const ph = this.root.querySelector<HTMLElement>('[data-playhead]'); if (ph) ph.style.left = c.span(t) + '%';
    const box = this.root.querySelector<HTMLElement>('[data-scrub]');
    if (box) { box.setAttribute('aria-valuemax', String(Math.round(c.tEnd))); box.setAttribute('aria-valuenow', String(Math.round(t))); box.setAttribute('aria-valuetext', `t = ${Math.round(t)} ms · ${packetLabel(t, c.legs)}`); }
    const hb = this.root.querySelector<HTMLElement>('[data-harmbar]');
    if (hb) {
      let w = 0;
      if (c.harmExposed && c.detectable && c.consumedAt != null && c.verdictAt != null) {
        const left = c.span(c.consumedAt), right = c.span(Math.min(t, c.verdictAt));
        w = Math.max(0, right - left);
        hb.style.left = left + '%'; hb.style.width = w + '%';
      } else hb.style.width = '0';
      hb.classList.toggle('empty', w <= 1); // 라벨을 띄울 자리가 없으면 막대만 남긴다
    }
  }
}
