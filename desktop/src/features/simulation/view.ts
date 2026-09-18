import type { Data } from '../../shared/types';
// 참조 시나리오 화면: 보고서(itx/report/html.py)의 7개 섹션을 앱 안에서 그대로 재현한다.
// 매트릭스는 simulation_matrix 한 번으로, 사건 상세는 선택할 때마다 simulation 한 건으로 받는다.
import { esc, cls, st, short, absent, CV, pills, hopMapHtml, eqLabels, eqEdges, legendRowHtml, playControlsHtml, computeLegs, makeSpan, Playback, PlayContext, timeBoxHtml, Mark, evidenceRowsHtml, codesHtml, checkChipsHtml, gateColor, equationTableHtml, stripGridHtml, MODEL_LATENCY_MS, reducedMotion,  } from '../../shared/console';
import { FlowData, flowCanvasHtml, flowLegs, mountFlow, footHtml, eqFromEquations, actionTone } from '../../shared/flow';

type Call = (operation: string, args?: Data) => Promise<any>;
interface Matrix { generated_with: Data; scenarios: Data[]; rows: Data[]; q1_matrix: Data[]; summary: Data; t_contribution?: Data[]; t_contribution_summary?: Data }
const MODES = ['observe', 'protect', 'strict'];
const COOPS = ['U', 'U+M', 'U+R', 'U+R+M'];

// 1c 재작성 재생: 셀 값은 S14 실행의 실제 재작성 전·후 잎 해시·접두 루트다 (보고서 report.js 와 같은 규칙).
// 항목 하나가 바뀌면 그 잎과 그 뒤의 모든 접두 루트가 차례로 바뀌고 마지막에 앵커 비교가 불일치로 넘어간다.
export function rewriteTableHtml(rw: Data): string {
  const cell = (b: string, a: string) => `<td class="mono rw-cell" data-before="${esc(b)}" data-after="${esc(a)}">${short(b)}</td>`;
  const rows = rw.before.map((b: Data, i: number) => { const x = rw.after[i];
    return `<tr class="rw-row${i === rw.tampered_index ? ' tampered' : ''}"><td class="muted">${i}</td><td>${esc(b.content_type.replace('application/vnd.itx.', '').replace('+json', ''))}</td>${cell(b.leaf_hash, x.leaf_hash)}${cell(b.prefix_root, x.prefix_root)}</tr>`; }).join('');
  const lastB = rw.before[rw.before.length - 1], lastA = rw.after[rw.after.length - 1];
  return `<div data-rw>
    <div class="tabrow" style="margin:10px 0 6px;gap:8px;flex-wrap:wrap"><button type="button" class="itx-btn itx-btn-accent" data-rw-play>▶ 재작성 재생</button><button type="button" class="itx-btn" data-rw-reset>앵커 시점으로 되돌리기</button>
      <span class="small muted">항목 #${rw.tampered_index} 교체 → 그 뒤 접두 루트가 차례로 바뀜 → 앵커 비교 불일치. 모든 값은 이 실행의 실제 전·후 값이다.</span></div>
    <div class="tablewrap"><table style="font-size:12px"><thead><tr><th>#</th><th>유형</th><th>잎 해시</th><th>접두 루트 root(0..#)</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="tablewrap" style="margin-top:8px"><table><thead><tr><th>앵커 크기</th><th>앵커에 고정된 루트</th><th>현재 재계산 루트</th><th>판정</th></tr></thead><tbody>
      <tr><td class="mono">${rw.anchor.tree_size}</td><td class="mono">${short(rw.anchor.root_hash)}</td>${cell(lastB.prefix_root, lastA.prefix_root)}<td class="rw-verdict" data-rw-verdict data-before="일치" data-after="앵커된 체크포인트와 다른 과거를 제시함 (기록 재작성)">일치</td></tr></tbody></table></div></div>`;
}
const rwTimers = new WeakMap<HTMLElement, number[]>();
export function ledgerRewritePlay(root: HTMLElement, toAfter: boolean) {
  const cells = [...root.querySelectorAll<HTMLElement>('.rw-cell')], verdict = root.querySelector<HTMLElement>('[data-rw-verdict]')!;
  const set = (c: HTMLElement, after: boolean) => { const changed = after && c.dataset.after !== c.dataset.before;
    c.classList.toggle('changed', changed); c.innerHTML = short(after ? c.dataset.after! : c.dataset.before!) + (changed ? `<span class="old">${short(c.dataset.before!)}</span>` : ''); };
  (rwTimers.get(root) || []).forEach(t => clearTimeout(t)); const timers: number[] = []; rwTimers.set(root, timers);
  if (!toAfter) { cells.forEach(c => set(c, false)); verdict.textContent = verdict.dataset.before!; verdict.classList.remove('bad'); return; }
  const changing = cells.filter(c => c.dataset.after !== c.dataset.before);
  cells.filter(c => c.dataset.after === c.dataset.before).forEach(c => set(c, false));
  const step = reducedMotion ? 0 : 260;
  changing.forEach((c, i) => timers.push(window.setTimeout(() => set(c, true), i * step)));
  timers.push(window.setTimeout(() => { verdict.textContent = verdict.dataset.after!; verdict.classList.add('bad'); }, changing.length * step));
}

const KIND_LABEL: Record<string, string> = {
  contract_signed: '계약 서명', request_sent: '요청 전송', received: '요청 수신', pre_exec_check: '실행 전 검사',
  refused: '거부', inferred: '추론 완료', receipt_issued: '영수증 발행', relay_statement_issued: '중계 진술 발행',
  modified_request: '요청 변조', transformed_request: '요청 변환', rerouted: '재라우팅', stripped_binding: '결합 정보 제거',
  modified_response: '응답 변조', collusion_forged_receipt: '공모 영수증 위조', dropped_request: '요청 드롭',
  replayed_previous_response: '이전 응답 재사용', statement_omitted: '진술 미발행', stripped_inline_receipt: '영수증 제거',
  response_received: '응답 수신', error_received: '오류 수신', gate_local_checks: '로컬 검사',
  response_consumed: '업무 사용', manifest_issued: '매니페스트 발행', verdict_requested: 'T 판정 조회',
  verdict_unavailable: 'T 응답 없음', verdict_deadline: '기한 도달', service_down: 'T 정지', service_up: 'T 복구',
  checkpoint_anchored: '앵커 고정', log_tampered: '기록 재작성', gate_decision: '게이트 결정', verdict_issued: 'T 판정',
};

const ANIM_NOTES = [
  {title: '요청의 이동과 진술 발행', spec: '사건 상세 재생 · 실제 홉 지연 비례', impl: true,
   body: 'U→R→M→R→U 를 점 하나가 지난다. 구간 경계는 임의 데모 수치가 아니라 이 시도의 실제 sent_at/received_at 과 시뮬레이션 지연 상수(홉 20ms·중개 처리 5ms·서명 2ms)에서 역산한 것이다. 이동 구간은 정지에서 출발해 정지로 끝나므로 가감속을 주고, 노드를 드나드는 수직 구간을 넣어 꺾은선 위를 실제로 타고 돈다.'},
  {title: '진행 방향 잔상', spec: '사건 상세 재생 · 20px 꼬리 + 글로우', impl: true,
   body: '점 뒤로 지나온 경로를 20px 만큼 되짚고, 꼬리 끝에서 패킷 앞단으로 불투명도가 증가하는 SVG 그라데이션을 적용한다. 패킷은 반경 6px 에 같은 색의 6px 글로우를 두르고, 꼬리는 경로의 꺾임과 구간 경계를 그대로 따라가며 노드에 도착해 머무는 동안에는 길이가 0 으로 줄어든다. 홉 구간은 추론 구간보다 10배 짧아 한 프레임에 크게 건너뛰므로 재생 중에는 그 간격만큼(최대 40px) 꼬리를 늘린다.'},
  {title: '노드 도달 펄스', spec: '사건 상세 재생 · 1회성 fade', impl: true,
   body: '패킷이 U/R/M 상자에 닿는 순간 그 상자 바깥에만 4px 링이 300ms 동안 잦아든다 (흐름 색 accent-glow). 반복·점멸하지 않고 잔상도 남기지 않는다. 뒤로 이동하면 다시 낼 수 있게 초기화되고, 선택을 바꿔 최종 상태로 들어올 때는 내지 않는다 — 방금 일어난 일이 아니기 때문이다.'},
  {title: '변조의 순간', spec: '사건 상세 재생 · 색 전이만', impl: true,
   body: '요청 변조(E4 실패)는 R→M 구간에서, 응답 변조(E10 실패)는 M→R 구간부터 점과 꼬리의 색이 파랑에서 빨강으로 바뀐다. 폭발·흔들림 없이 색과 라벨만 바꾼다. 실제로 실패한 등식에서 색을 가져오므로 시나리오마다 자동으로 맞다.'},
  {title: '증거 등록의 도달', spec: '증거 패널 · 200~320ms 페이드', impl: true,
   body: '재생 시점이 각 진술의 등록 시각(상한)을 지나면 그 행과 T 로 가는 점선이 대기색에서 흐름 색(accent)으로 넘어간다. 등록 완료는 무결성 검증 통과를 뜻하지 않는다. 프레임마다 인라인 색을 쓰지 않고 상태 클래스만 바꿔 전이가 끊기지 않게 했다. 결손 행은 전이 대상에서 제외한다.'},
  {title: '탐지와 소비의 간격', spec: '시점 타임라인 + 스윔레인(1b) 하단', impl: true,
   body: '소비 지점에서 T 판정 등록 지점까지 붉은 막대가 실제 시간 비율대로 자란다. 막대가 길수록 나쁜 것이 아니라 "무엇이 그 사이에 실행되었는가" 를 묻게 만드는 장치다.'},
  {title: '임의 시점 탐색', spec: '시점 타임라인 · 스크러버', impl: true,
   body: '타임라인을 누르거나 끌면 그 시점으로 바로 간다 (OpenTelemetry 추적 뷰의 시간 축 탐색과 같은 조작). |◀ ▶| 는 홉 경계 단위로 한 걸음씩 옮기고, 속도는 ×0.5/×1/×2 로 바꾼다. 초점이 타임라인이나 재생 컨트롤에 있을 때 Space 는 재생·정지, ←/→ 는 홉 이동, Home/End 는 처음·끝이다.'},
  {title: '증거가 늘며 바뀌는 판정', spec: '5절 (1d) · 탭 전환', impl: true,
   body: '협조 집합 탭을 U → U+M/U+R → U+R+M 으로 늘리면 같은 사건의 배지·사다리가 실제 Q1 매트릭스 값으로 바뀐다. 탭을 누를 때만 바뀌고 나머지는 정지한다 — 별도 애니메이션은 넣지 않았다.'},
  {title: '해시 체인과 외부 앵커', spec: '원장형(1c) · S14 재작성 재생', impl: true,
   body: 'S14 에서 「재작성 재생」을 누르면 교체된 항목의 잎 해시가 먼저 바뀌고, 그 뒤의 접두 루트 root(0..#) 가 260ms 간격으로 차례로 바뀌며, 마지막에 앵커 비교 행이 불일치로 넘어간다. 셀의 값은 시뮬레이션이 재작성 직전·직후에 실제로 계산한 잎 해시와 접두 루트이고 바뀐 셀에는 이전 값이 취소선으로 남는다 — 연출용 수치는 없다. 교체 이전 항목은 움직이지 않으며, 다른 시나리오에서는 S14 로 이동하는 링크만 둔다.'},
  {title: '모드 전환', spec: '사건 상세 · 탭 전환', impl: true,
   body: 'observe/protect/strict 를 바꾸면 경로와 증거는 그대로 있고 시간선의 결정·소비 표시와 게이트 패널만 바뀐다. 크로스페이드는 넣지 않았고 즉시 갱신된다 — 같은 사건에서 정책만 달라졌음을 보이는 데는 애니메이션이 굳이 필요하지 않았다.'},
];

export class ReportView {
  private matrix: Matrix | null = null;
  private runs = new Map<string, Data>();
  private cur = {sid: 'S01', mode: 'protect', attempt: 0};
  private curU = {sid: 'S03', coop: 'U'};
  private loading = false;
  private play: Playback;
  private selection = 0;

  constructor(private root: HTMLElement, private call: Call, private fail: (e: unknown) => void) {
    this.play = new Playback(root, 'rpt');
    this.$('rpt-run').onclick = () => { this.load(true).catch(fail); };
    root.addEventListener('click', e => {
      const rw = (e.target as HTMLElement).closest<HTMLElement>('[data-rw-play],[data-rw-reset]');
      if (rw) { ledgerRewritePlay(rw.closest<HTMLElement>('[data-rw]')!, rw.hasAttribute('data-rw-play')); return; }
      const btn = (e.target as HTMLElement).closest<HTMLElement>('button[data-jump]');
      if (!btn) return;
      this.cur = {sid: btn.dataset.jump!, mode: this.cur.mode, attempt: 0};
      this.onSelectionChanged();
      this.$('rpt-controls').scrollIntoView({block: 'start', behavior: reducedMotion ? 'auto' : 'smooth'});
    });
    this.renderNotes();
  }
  private $<T extends HTMLElement = HTMLElement>(id: string) { return this.root.querySelector<T>('#' + id)!; }

  async show() { if (!this.matrix && !this.loading) await this.load(false); }

  async load(force: boolean) {
    if (this.loading) return;
    if (force) this.runs.clear();
    this.loading = true;
    const status = this.$('rpt-status'); status.hidden = false;
    status.innerHTML = `<div class="busybar"></div><span class="itx-empty-mark">⊞</span><span class="itx-empty-title">17개 시나리오 × 3개 정책을 실행하는 중</span><span class="itx-empty-note">결정적 모형 모델과 시뮬레이션 시계로 51회 실행과 Q1 매트릭스 20회를 계산합니다.</span>`;
    const button = this.$<HTMLButtonElement>('rpt-run'); button.disabled = true;
    try {
      this.matrix = await this.call('simulation_matrix');
      status.hidden = true;
      this.$('rpt-body').hidden = false;
      this.renderBadges(); this.renderCards(); this.renderSummary(); this.renderMatrix(); this.renderQ1(); this.renderContribution(); this.renderUncertainty();
      await this.onSelectionChanged();
    } catch (e) {
      status.innerHTML = `<span class="itx-empty-mark">✗</span><span class="itx-empty-title">참조 시나리오를 실행하지 못했습니다</span><span class="itx-empty-note">${esc(e instanceof Error ? e.message : e)}</span>`;
      this.fail(e);
    } finally { this.loading = false; button.disabled = false; }
  }
  private async run(sid: string, mode: string): Promise<Data> {
    const key = sid + '|' + mode;
    let r = this.runs.get(key);
    if (!r) { r = await this.call('simulation', {scenario: sid, mode}); this.runs.set(key, r!); }
    return r!;
  }
  private row(sid: string, mode: string) { return this.matrix!.rows.find(r => r.scenario_id === sid && r.mode === mode)!; }

  /** 바깥(시나리오 카드)에서 사건을 고른다. 매트릭스 행·탭 선택과 같은 경로를 탄다. */
  select(sid: string) {
    this.cur = {sid, mode: this.cur.mode, attempt: 0};
    this.onSelectionChanged().catch(this.fail);
    this.$('rpt-controls').scrollIntoView({block: 'start', behavior: reducedMotion ? 'auto' : 'smooth'});
  }
  private refCat = '전체';
  // 시나리오 카드 (Console v3): 분류 필터와 17장. 기대 결과는 protect 실행의 T 최종 판정에서 온다 — 상수가 아니다.
  private renderCards() {
    const M = this.matrix!;
    const cats = ['전체', ...Array.from(new Set(M.scenarios.map(sc => String(sc.category || '기타'))))];
    if (!cats.includes(this.refCat)) this.refCat = '전체';
    pills(this.$('rpt-cats'), cats.map(c => ({v: c, label: c})), v => v === this.refCat, v => { this.refCat = v; this.renderCards(); });
    const items = M.scenarios.filter(sc => this.refCat === '전체' || String(sc.category || '기타') === this.refCat);
    this.$('rpt-count').textContent = `${items.length} / ${M.scenarios.length} 건 · mock_result`;
    this.$('rpt-cards').innerHTML = items.map(sc => {
      const r = this.row(sc.id, 'protect');
      const tone = r.verification_status === 'passed' ? 'pass' : r.verification_status === 'failed' ? 'fail' : 'na';
      const glyph = tone === 'pass' ? '✓' : tone === 'fail' ? '✗' : '–';
      const expected = tone === 'pass' ? '통과' : tone === 'fail' ? '실패' : esc(r.verification_status || '판정 없음');
      const gt = sc.ground_truth || {};
      const note = gt.attack_present ? (gt.detectable_by_evidence ? '공격 있음 · 증거로 탐지' : '공격 있음 · 증거로 탐지 불가') : '공격 없음';
      return `<div class="itx-scen${sc.id === this.cur.sid ? ' on' : ''}" data-scen-card="${esc(sc.id)}">
        <div class="h"><b>${esc(sc.id)}</b><span class="itx-chip">${esc(String(sc.category || '기타'))}</span><span class="itx-chip exp" data-tone="${tone}">${glyph} ${expected}</span></div>
        <div class="ti">${esc(sc.title)}</div>
        <div class="bd">${note} · 완전성 ${esc(r.completeness || '—')} · 게이트 ${esc(r.gate_action || '—')}${(r.codes || []).length ? ' · ' + (r.codes as string[]).map(esc).join(', ') : ''}</div>
        <div class="ft"><button type="button" class="itx-btn itx-btn--outline" data-jump="${esc(sc.id)}">이 사건 재생</button><span class="mono-meta muted">3개 정책으로 실행됨</span></div>
      </div>`;
    }).join('');
  }

  private renderBadges() {
    const g = this.matrix!.generated_with;
    this.$('rpt-badges').innerHTML = [`itx ${g.itx_version}`, `검사기 ${g.checker_version}`, `seed ${g.seed}`, `서명 ${g.crypto_backend}`, `claim ${g.claim_status}`, 'deployment evaluation', 'assurance ≤ air-local'].map(x => `<span>${esc(x)}</span>`).join('');
  }
  private renderSummary() {
    const S = this.matrix!.summary; const modes = Object.keys(S);
    const row = (label: string, f: (s: Data) => string) => `<tr><th>${label}</th>${modes.map(m => `<td>${f(S[m])}</td>`).join('')}</tr>`;
    const frac = (o: Data) => o.den ? `${o.num}/${o.den}${o.rate != null ? ` <span class="muted">(${(o.rate * 100).toFixed(0)}%)</span>` : ''}` : '<span class="absent">분모 0</span>';
    this.$('rpt-summary').innerHTML = `<table><thead><tr><th>지표</th>${modes.map(m => `<th>${esc(m)}</th>`).join('')}</tr></thead><tbody>
      ${row('시도 수 / 공격 시도', s => `${s.attempts} / ${s.attack_attempts}`)}
      ${row('탐지 (T 최종 판정 failed, 관측 가능한 공격 중)', s => frac(s.detection) + ` <span class="muted small">제외 ${s.detection.excluded_undetectable}</span>`)}
      ${row('사용 전 방어 (공격 응답이 업무에 소비되지 않음)', s => frac(s.defense_before_use))}
      ${row('피해 노출 (공격 응답이 업무에 사용됨)', s => `${s.harm_exposed.num}/${s.harm_exposed.den}`)}
      ${row('오차단 (정상인데 격리·거부)', s => frac(s.false_block) + ` <span class="muted small">무응답 제외 ${s.false_block.excluded_no_response}</span>`)}
      ${row('안전 완료 (정상 요청이 검증 후 수용)', s => frac(s.safe_completion_legit))}
      ${row('증거 완전 (합의 증거 모두 등록)', s => `${s.evidence_complete.num}/${s.evidence_complete.den}`)}
      ${row('결정 대기 ms (평균 / 최대)', s => `${s.decision_wait_ms.mean ?? '-'} / ${s.decision_wait_ms.max ?? '-'}`)}
      ${row('왕복 지연 ms (평균 / 최대)', s => `${s.rtt_ms.mean ?? '-'} / ${s.rtt_ms.max ?? '-'}`)}
      </tbody></table>`;
  }
  private renderMatrix() {
    const M = this.matrix!;
    const rows = M.scenarios.map(sc => {
      const rp = this.row(sc.id, 'protect');
      const gates = MODES.map(m => { const r = this.row(sc.id, m); const act = r.gate_action; const atk = r.attack_present;
        const k = act === 'no_response' ? 'na' : (act === 'accept' || act === 'accept_unverified') ? (atk ? 'fail' : 'pass') : (atk ? 'pass' : 'fail');
        return `<td class="${k}">${esc(act)}</td>`; }).join('');
      return `<tr class="clickable" tabindex="0" data-sid="${esc(sc.id)}"><td><b>${esc(sc.id)}</b></td><td>${esc(sc.title)}<div class="small muted">${esc(sc.category)} · 공격 ${sc.ground_truth.attack_present ? '있음' : '없음'}${sc.ground_truth.detectable_by_evidence ? '' : ' · <b>증거로 탐지 불가</b>'}</div></td>
        <td class="${st(rp.verification_status)}">${esc(rp.verification_status)}</td><td>${esc(rp.completeness)}</td><td class="small">${rp.codes.length ? rp.codes.map(esc).join('<br>') : '<span class="absent">없음</span>'}</td>${gates}
        <td class="${rp.audit_ok ? 'pass' : 'fail'}">${rp.audit_ok ? '일치' : '불일치'}${rp.verdict_mismatches ? ` <span class="small">(판정 ${rp.verdict_mismatches})</span>` : ''}</td><td class="${rp.anchors_ok ? 'pass' : 'fail'}">${rp.anchors_ok ? '일치' : '재작성 감지'}</td></tr>`;
    }).join('');
    const target = this.$('rpt-matrix');
    target.innerHTML = `<table><thead><tr><th>ID</th><th>시나리오</th><th>최종 판정 (protect 실행)</th><th>완전성</th><th>불일치 코드</th><th>게이트 observe</th><th>게이트 protect</th><th>게이트 strict</th><th>독립 감사</th><th>앵커</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="small muted">게이트 칸의 색은 '공격이 있으면 막았는가, 없으면 통과시켰는가' 기준이다. observe 모드는 설계상 모두 통과시키므로 공격 시나리오에서 빨갛다 — 그것이 관찰 모드의 비용이다. 무응답은 회색이다.</p>`;
    const pick = (sid: string) => { this.cur = {sid, mode: this.cur.mode, attempt: 0}; this.onSelectionChanged(); };
    target.querySelectorAll<HTMLTableRowElement>('tr.clickable').forEach(tr => {
      tr.addEventListener('click', () => pick(tr.dataset.sid!));
      tr.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(tr.dataset.sid!); } });
    });
  }

  private async onSelectionChanged() {
    const M = this.matrix!;
    const ticket = ++this.selection;
    this.$('rpt-matrix').querySelectorAll<HTMLTableRowElement>('tr[data-sid]').forEach(tr => tr.classList.toggle('sel', tr.dataset.sid === this.cur.sid));
    pills(this.$('rpt-scenario-tabs'), M.scenarios.map(sc => ({v: sc.id, label: sc.id, title: sc.title})), v => v === this.cur.sid, v => { this.cur = {sid: v, mode: this.cur.mode, attempt: 0}; this.onSelectionChanged(); });
    this.root.querySelectorAll<HTMLElement>('[data-scen-card]').forEach(card => card.classList.toggle('on', card.dataset.scenCard === this.cur.sid));
    pills(this.$('rpt-mode-tabs'), MODES.map(m => ({v: m, label: m})), v => v === this.cur.mode, v => { this.cur.mode = v; this.onSelectionChanged(); });
    this.play.stop();
    const attempts = this.row(this.cur.sid, this.cur.mode).attempts;
    const attemptRow = this.$('rpt-attempt-row');
    attemptRow.hidden = attempts <= 1;
    let r: Data;
    try { r = await this.run(this.cur.sid, this.cur.mode); } catch (e) { this.fail(e); return; }
    if (ticket !== this.selection) return;
    if (attempts > 1) pills(this.$('rpt-attempt-tabs'), r.attempts.map((a: Data, i: number) => ({v: String(i), label: a.attempt_id})), v => +v === this.cur.attempt, v => { this.cur.attempt = +v; this.onSelectionChanged(); });
    this.renderDetail(r);
  }

  // ---------- 사건 상세: 홉 지도 · 시점 · 증거 · 결론 · 집행 · 비교 · 등식 · 원장 · 감사 · 스윔레인 · 시간선 ----------
  private renderDetail(r: Data) {
    // 이전 렌더에서 캔버스 하단에 도킹한 재생 컨트롤을 원래 자리(정책 모드 줄)로 되돌린다 — innerHTML 교체로 사라지지 않게.
    { const pc = this.root.querySelector<HTMLElement>('.playctl'); const home = this.$('rpt-mode-tabs')?.parentElement;
      if (pc && home && pc.closest('#rpt-detail')) home.appendChild(pc); }
    const a = r.attempts[Math.min(this.cur.attempt, r.attempts.length - 1)];
    const sc = r.scenario, fv = a.final_verdict, eq = fv.equations, g = a.gate;
    const c = a.contract.payload, o = a.observation ? a.observation.payload : null,
          rl = a.inline_relay ? a.inline_relay.payload : null, m = a.inline_receipt ? a.inline_receipt.payload : null;
    const gt = a.ground_truth_view || {};
    const findReg = (ct: string) => (a.registered || []).find((x: Data) => x.content_type === ct);
    const regContract = findReg('application/vnd.itx.contract+json'), regRelay = findReg('application/vnd.itx.relay+json'),
          regReceipt = findReg('application/vnd.itx.receipt+json'), regObs = findReg('application/vnd.itx.observation+json');
    const verdictEv = r.timeline.find((e: Data) => e.kind === 'verdict_issued' && e.sub === a.sub);
    const verdictAt: number | null = verdictEv ? verdictEv.t : null;
    const consumedAt: number | null = g.consumed_at;
    const detectable: boolean = a.ground_truth.detectable_by_evidence, attack: boolean = a.ground_truth.attack_present;
    const harmExposed: boolean = a.metrics.harm_exposed;

    const modelId = (m && m.model_id) || (rl && rl.upstream_model) || c.requested_model;
    const legs = flowLegs(a.sent_at, a.received_at, MODEL_LATENCY_MS[modelId] ?? 200);
    const breakpoint = Math.max(60, Math.round(a.received_at * 1.4 / 10) * 10);
    const tEnd = Math.max(breakpoint + 40, a.sent_at, a.received_at, g.decided_at, consumedAt || 0, verdictAt || 0) * 1.08;
    const span = makeSpan(breakpoint, tEnd);
    const ctx: PlayContext = {legs, tEnd, span, reqFail: (eq.E4 || {}).result === 'fail', respFail: (eq.E10 || {}).result === 'fail', consumedAt, verdictAt, harmExposed, detectable};

    // 원안의 마크: 전송 · M 서명 · 수신 · 사용 · T 판정(또는 판정 없음). 시각은 실제 값.
    const marks: Mark[] = [
      {label: '전송', at: `${Math.round(a.sent_at)} ms`, pos: span(a.sent_at), color: 'muted'},
      {label: 'M 서명', at: `${Math.round(legs[4].t1)} ms`, pos: span(legs[4].t1), color: 'muted'},
      {label: '수신', at: `${Math.round(a.received_at)} ms`, pos: span(a.received_at), color: 'accent'},
    ];
    if (consumedAt != null) marks.push({label: '사용', at: `${Math.round(consumedAt)} ms`, pos: span(consumedAt), color: 'fail'});
    marks.push(verdictAt != null ? {label: 'T 판정', at: `${Math.round(verdictAt)} ms`, pos: span(verdictAt), color: 'pass'}
                                 : {label: '판정 없음', at: '기한 초과', pos: span(tEnd), color: 'na'});
    const harmNote = (attack && !detectable)
      ? '탐지 불가로 분류된 사건이다. 탐지율 분모에서 제외하고 그 수를 따로 적는다 — 통과 배지로 표시하지 않는다.'
      : consumedAt === null
        ? "업무 사용 없음. 이 사건에서 방어는 '경로를 차단했다' 가 아니라 '변조된 응답이 도구 실행에 쓰이기 전에 U 가 거부했다' 로 기록된다."
        : harmExposed && verdictAt != null
          ? `소비 ${consumedAt} ms · T 판정 등록 ${verdictAt} ms. 그 사이 ${Math.max(0, verdictAt - consumedAt)} ms 동안 피해가 노출되었다. 탐지는 성공, 이 피해의 방어는 실패다.`
          : `정상 요청이 기한 내 완료되었다. 대기 비용 ${g.decided_at - g.received_at} ms.`;

    // 원안의 증거 3행 (등록 시각은 실제 원장 값).
    const evidence = evidenceRowsHtml([
      {key: 'U', name: 'U 요청 진술', detail: 'contract · nonce · 허용 모델 집합', reg: regContract ? regContract.registered_at : null},
      {key: 'R', name: 'R 중계 진술', detail: '전달 해시 · 변환 선언', reg: regRelay ? regRelay.registered_at : null},
      {key: 'M', name: 'M 응답 영수증', detail: '응답 커밋 · 시도 ID · 서명', reg: regReceipt ? regReceipt.registered_at : null},
    ]);
    void regObs;
    const flow: FlowData = {key: 'rpt', eq: eqFromEquations(eq), regs: {U: regContract ? regContract.registered_at : null, R: regRelay ? regRelay.registered_at : null, M: regReceipt ? regReceipt.registered_at : null},
      sent: a.sent_at, received: a.received_at, latency: MODEL_LATENCY_MS[modelId] ?? 200,
      sm: {mode: g.mode, gateAction: g.action, decidedAt: g.decided_at, consumedAt, verdictAt},
      info: {id: sc.id, title: sc.title, verdict: fv.verification_status, verdictTone: st(fv.verification_status), action: g.action, actionTone: actionTone(g.action), note: `${fv.completeness} · ${fv.established_assurance}`},
      foot: footHtml(timeBoxHtml(marks), evidence)};

    const eqr = (id: string) => (eq[id] || {}).result;
    const isFail = (id: string) => eqr(id) === 'fail';
    const bad = {
      req: {R: isFail('E2') || isFail('E4'), M: isFail('E3') || isFail('E4')},
      model: {R: isFail('E8'), M: isFail('E8') || isFail('E9')},
      tr: {R: isFail('E4')}, nonce: {R: isFail('E5'), M: isFail('E5')},
      resp: {R: isFail('E6') || isFail('E7') || isFail('E10'), M: isFail('E6'), U: isFail('E7') || isFail('E10')},
      att: {R: isFail('E11'), M: isFail('E11'), U: isFail('E11')},
    };
    const cell = (html: string | null, isBad: boolean, isGap: boolean) => isGap ? `<span style="color:${CV('na')};font-style:italic">결손</span>`
      : (html == null ? '<span class="absent">없음</span>' : isBad ? `<span style="color:${CV('fail')};font-weight:600;background:${CV('fail-soft')};padding:1px 4px;border-radius:3px">${html}</span>` : html);
    const cmp = `<div class="tablewrap"><table><thead><tr><th></th><th>U 승인 계약</th><th>R 선언 (동봉)</th><th>M 관측 (동봉 영수증)</th><th>U 실제 수신</th></tr></thead><tbody>
      <tr><th>요청 커밋</th><td class="mono">${short(c.req_commit)}</td><td class="mono">${cell(rl ? `in ${short(rl.in_commit)}<br>out ${short(rl.out_commit)}` : null, bad.req.R, !rl)}</td><td class="mono">${cell(m ? short(m.request_commit) : null, bad.req.M, !m)}</td><td class="muted small">—</td></tr>
      <tr><th>모델</th><td>${esc(c.requested_model)} <span class="small muted">허용 ${esc(c.allowed_models.join(', '))} · 폴백 ${esc(c.fallback_policy)}</span></td><td>${cell(rl ? esc(rl.upstream_model) + ' <span class="small muted">(' + esc(rl.policy_decision) + ')</span>' : null, bad.model.R, !rl)}</td><td>${cell(m ? esc(m.model_id) + ' <span class="small muted">' + esc(m.decision) + '</span>' : null, bad.model.M, !m)}</td><td class="muted small">—</td></tr>
      <tr><th>변환</th><td>${esc(c.allowed_request_transforms.join(', '))}</td><td>${cell(rl ? esc(rl.request_transform_id) : null, bad.tr.R, !rl)}</td><td class="muted small">—</td><td class="muted small">—</td></tr>
      <tr><th>nonce</th><td class="mono">${short(c.nonce)}</td><td class="mono">${cell(rl ? short(rl.nonce_forwarded) : null, bad.nonce.R, !rl)}</td><td class="mono">${cell(m ? short(m.eat_nonce) : null, bad.nonce.M, !m)}</td><td class="muted small">—</td></tr>
      <tr><th>응답 커밋</th><td class="muted small">—</td><td class="mono">${cell(rl ? `in ${short(rl.resp_in_commit)}<br>out ${short(rl.resp_out_commit)}` : null, bad.resp.R, !rl)}</td><td class="mono">${cell(m ? short(m.response_commit) : null, bad.resp.M, !m)}</td><td class="mono">${cell(o ? short(o.resp_commit) : null, bad.resp.U, !o)}</td></tr>
      <tr><th>시도</th><td>${esc(c.attempt_id)}</td><td>${cell(rl ? esc(rl.attempt_id) : null, bad.att.R, !rl)}</td><td>${cell(m ? esc(m.attempt_id) : null, bad.att.M, !m)}</td><td>${cell(o ? esc(o.attempt_id) : null, bad.att.U, !o)}</td></tr>
      </tbody></table></div>
      <div class="small muted" style="margin-top:7px">커밋은 <span class="mono">commit(x) = H(salt ‖ H(canonical(x)))</span> 의 앞 12자다. 솔트는 로그에 올리지 않으므로 공개 원장만으로는 사전 대입이 불가능하다. 빨간 셀은 실패한 등식이 가리키는 값이며 두 칸이 다르다는 사실 자체가 가해자 확정은 아니다.</div>`;

    const regs = (a.registered || []).map((x: Data) => `<tr><td>${x.index}</td><td class="small">${esc(x.content_type.replace('application/vnd.itx.', '').replace('+json', ''))}</td><td class="small">${esc(x.iss.replace('urn:itx:party:', ''))}</td><td>≤ ${x.registered_at} ms</td><td class="mono">${short(x.statement_hash)}</td></tr>`).join('') || '<tr><td colspan="5" class="absent">등록된 진술 없음</td></tr>';
    const facts = `<div class="tablewrap"><table class="small"><tbody>
      <tr><th>U 가 보낸 요청</th><td>${absent(gt.request_sent && gt.request_sent.input)}</td></tr>
      <tr><th>M 이 받은 요청</th><td>${gt.request_at_model ? esc(JSON.stringify(gt.request_at_model)) : '<span class="absent">null (전달되지 않음)</span>'}</td></tr>
      <tr><th>M 이 낸 응답</th><td>${absent(gt.response_from_model && gt.response_from_model.output)}</td></tr>
      <tr><th>U 가 받은 응답</th><td>${absent(gt.response_at_user && gt.response_at_user.output)}${gt.replayed_from ? ` <span class="warn">(${esc(gt.replayed_from)} 의 응답 재사용)</span>` : ''}${a.response_body && a.response_body.tool_call ? ` <span class="fail">도구 호출 지시 포함: ${esc(JSON.stringify(a.response_body.tool_call))}</span>` : ''}</td></tr>
      </tbody></table></div>`;
    const tl = r.timeline.filter((e: Data) => !e.sub || e.sub === a.sub || e.kind.startsWith('service') || e.actor === 'T' || e.actor === 'auditor' || e.actor === 'sim').map((e: Data) => {
      const mark = e.kind === 'response_consumed' ? 'mark' : e.kind === 'gate_decision' ? 'decide' : '';
      return `<tr><td class="muted">${e.seq}</td><td>${e.t}</td><td><b>${esc(e.actor)}</b></td><td class="${mark}">${esc(e.kind)}</td><td class="small mono">${esc(JSON.stringify(e.detail)).slice(0, 220)}</td></tr>`; }).join('');
    const au = r.audit, ts = r.ts;
    const anchors = au.anchors.map((x: Data) => `<tr><td>${x.tree_size}</td><td class="mono">${short(x.anchored_root)}</td><td class="mono">${short(x.recomputed_root)}</td><td class="${x.ok ? 'pass' : 'fail'}">${esc(x.reason)}</td></tr>`).join('') || '<tr><td colspan="4" class="absent">앵커 없음</td></tr>';
    const mism = au.verdict_mismatches.map((x: Data) => `<li><span class="mono">${short(x.sub)}</span> T: <b>${esc(x.t_verdict ? x.t_verdict.verification_status : '없음')}</b> [${esc((x.t_verdict ? x.t_verdict.codes : []).join(', '))}] → 재계산: <b>${esc(x.recomputed.verification_status)}</b> [${esc(x.recomputed.codes.join(', '))}]</li>`).join('');
    const unauth = (au.unauthenticated_verdicts || []).map((x: Data) => `<li><span class="mono">${short(x.sub)}</span> #${x.log_index} <b>${esc(x.iss)}</b>: ${esc(x.problem)}</li>`).join('');
    const drops = Object.entries(ts.queue_drops || {}).map(([k, v]: [string, any]) => `${k}: ${v.length}`).join(' · ');

    this.$('rpt-detail').innerHTML = `
    <div class="card">
      <div class="card-head">
        <div><div class="card-title">요청 <span class="mono" style="color:${CV('muted')};font-size:14px">${esc(a.sub)}</span> · ${esc(sc.title)}</div>
        <div class="small muted" style="margin-top:3px">${esc(sc.description)}</div></div>
        <div class="badges"><span>mock_result</span><span>evaluation</span></div>
      </div>
      <p class="small" style="margin:10px 0 0"><b>시뮬레이터 사실:</b> 공격 ${attack ? `있음 (${esc(a.ground_truth.attack_kind)})` : '없음'} · 증거로 탐지 ${detectable ? '가능' : '<b class="warn">불가 (설계상 한계)</b>'} ${a.ground_truth.note ? '· ' + esc(a.ground_truth.note) : ''}</p>
    </div>
    <div class="card"><h3>경로 — 업무 데이터 경로(실선)와 T 의 증거·통제 경로(점선)</h3>
      ${flowCanvasHtml(flow)}
      <p class="small muted" style="margin-top:10px">${harmNote}</p>
      <div style="margin-top:14px">${stripGridHtml([
        {k: '정책 해시', v: short(fv.policy_hash)}, {k: '검사기', v: esc(fv.checker_version)}, {k: '신뢰 키 집합', v: esc(fv.trust_keys_version)},
        {k: '독립 재실행', v: au.ok ? '일치' : '불일치', color: au.ok ? 'pass' : 'fail'}])}</div>
      <div class="small muted" style="margin-top:7px">판정은 이 네 값에 고정된다. 감사자는 로그 내보내기와 앵커만으로 같은 판정을 재계산할 수 있어야 하며, 재계산이 T 와 다르면 그 사실이 위 칸에 남는다.</div>
    </div>
    <div class="grid">
      <div class="card"><h3>결론 — 사실·모순·부족을 섞지 않는다</h3>
        <p style="margin:0 0 6px"><span class="mono" style="font-weight:700;font-size:14px;color:${CV(st(fv.verification_status))}">${esc(fv.verification_status)}</span>
          <span class="small muted" style="margin-left:10px">완전성 <b style="color:${fv.completeness === 'complete' ? CV('muted') : CV('na')}">${esc(fv.completeness)}</b></span>
          <span class="small muted" style="margin-left:10px">협조 ${esc(fv.cooperation_set)}</span>
          <span class="small muted" style="margin-left:10px">보증 <b>${esc(fv.established_assurance)}</b></span></p>
        ${codesHtml(fv.discrepancies)}
        <ul class="tight small muted">${(fv.notes || []).map((n: string) => `<li>${esc(n)}</li>`).join('')}</ul></div>
      <div class="card"><h3>집행 — 사용자 게이트 (${esc(g.mode)})</h3>
        <div class="mono" style="font-weight:700;font-size:13px;color:${CV(gateColor(g.action))}">${esc(g.action)}</div>
        <div class="small" style="margin-top:3px">${g.reasons.map(esc).join(' · ')}</div>
        ${checkChipsHtml(g.local_checks)}
        <div class="small muted" style="margin-top:8px">수신 ${g.received_at} ms → 결정 ${g.decided_at} ms (대기 ${g.waited_ms} ms) · 업무 사용 ${g.consumed_at === null ? '<span class="absent">없음</span>' : g.consumed_at + ' ms'} ${g.consumed_before_decision ? '<b class="fail">— 결정 전에 소비됨</b>' : ''}</div>
        ${a.live_verdict ? `<div class="small muted" style="margin-top:4px">strict 모드에서 참조한 T 판정: ${esc(a.live_verdict.verification_status)} (${esc(a.live_verdict.completeness)})</div>` : ''}
        ${a.error ? `<div class="fail small" style="margin-top:4px">오류: ${esc(a.error)}</div>` : ''}</div>
    </div>
    <div class="card"><h3>비교 — U 승인 계약 · R 선언 · M 관측 · U 실제 수신</h3>${cmp}</div>
    <div class="card"><h3>시뮬레이터가 아는 사실 (증거가 아님)</h3>${facts}</div>
    <div class="grid">
      <div class="card"><h3>등식 (pass / fail / not_evaluable)</h3>${equationTableHtml(eq)}</div>
      <div class="card"><h3>등록된 진술 원장</h3><div class="tablewrap"><table><thead><tr><th>#</th><th>유형</th><th>발행</th><th>등록 시각 (상한)</th><th>진술 해시</th></tr></thead><tbody>${regs}</tbody></table></div>
        <p class="small muted">판정이 참조한 진술 ${fv.evidence_refs.length}건 · 서명 무효 ${fv.invalid_signature_refs.length}건 · 발행 권한 없음 ${(fv.unauthorized_issuer_refs || []).length}건</p></div>
    </div>
    <div class="card"><h3>T 자기 검증과 독립 감사</h3>
      <p class="small">트리 크기 ${ts.tree_size} · 루트 <span class="mono">${short(ts.root_hash)}</span> · 등록 ${ts.submissions} / 거부 ${ts.refusals} · 큐 드롭 ${drops || '없음'} · T 정지 ${ts.down_during_run ? '있음' : '없음'} · 추가 지연 ${ts.extra_delay_ms} ms ${ts.tampered_index !== null ? `· <b class="fail">운영자가 항목 #${ts.tampered_index} 를 교체 (모사)</b>` : ''}</p>
      <p>독립 재실행: <b class="${au.ok ? 'pass' : 'fail'}">${au.ok ? 'T 판정·트리·앵커 모두 일치' : '불일치 발견'}</b> · 트리 재계산 ${au.tree_recomputed_matches_head ? '<span class="pass">일치</span>' : '<span class="fail">불일치</span>'} · 헤드 서명 ${au.head_signature_valid ? '<span class="pass">유효</span>' : '<span class="fail">무효</span>'} · 검사한 요청 ${au.subs_checked}</p>
      ${mism ? `<ul class="tight small">${mism}</ul>` : ''}
      ${unauth ? `<p class="small fail">인증되지 않는 판정 진술 (서명·발행자 확인 실패)</p><ul class="tight small">${unauth}</ul>` : ''}
      <div class="tablewrap"><table><thead><tr><th>앵커 크기</th><th>앵커 루트</th><th>현재 재계산 루트</th><th>판정</th></tr></thead><tbody>${anchors}</tbody></table></div>
      <p class="small muted">${esc(au.note)}</p></div>
    ${this.swimlaneCard(r, a, consumedAt, verdictAt, harmExposed, detectable, attack, g)}
    ${this.ledgerCard(r, a)}
    <div class="card"><h3>시간선 (시뮬레이션 ms). 붉은 행 = 업무 사용, 녹색 행 = 게이트 결정</h3><div class="scroll"><table class="tl"><thead><tr><th>#</th><th>t</th><th>주체</th><th>사건</th><th>세부</th></tr></thead><tbody>${tl}</tbody></table></div></div>`;
    // 캔버스(줌·팬·미니맵·상태 머신)를 붙이고, 원안대로 재생 컨트롤을 캔버스 하단 패널에 도킹한다 (정적 DOM 을 옮겨 리스너를 유지).
    mountFlow(this.$('rpt-detail'), flow, this.play);
    { const pc = this.root.querySelector<HTMLElement>('.playctl'), dock = this.$('rpt-detail').querySelector<HTMLElement>('[data-fc-dock]'); if (pc && dock) dock.appendChild(pc); }
    this.play.set(ctx);
  }

  // 1b 스윔레인: 실제 타임라인을 U/R/M/T 레인으로 피벗한다. 배관용 이벤트(증거 등록 등)는 뺀다.
  private swimlaneCard(r: Data, a: Data, consumedAt: number | null, verdictAt: number | null, harmExposed: boolean, detectable: boolean, attack: boolean, g: Data): string {
    const rows = r.timeline.filter((e: Data) => ['U', 'R', 'M', 'T'].includes(e.actor) && (e.sub === a.sub || (e.sub === null && e.actor === 'T')) && KIND_LABEL[e.kind] !== undefined);
    const lanes = rows.map((e: Data) => {
      let label = KIND_LABEL[e.kind] || e.kind, c = '';
      if (e.kind === 'gate_decision') label = `게이트 ${e.detail.action}`;
      if (e.kind === 'verdict_issued') label = attack && !detectable ? '판정 (탐지 불가)' : `T 판정 ${e.detail.status}`;
      if (e.kind === 'modified_response' || e.kind === 'modified_request') c = 'fail';
      if (e.kind === 'response_consumed' && harmExposed) c = 'fail';
      if (e.kind === 'gate_decision' && (g.action === 'accept' || g.action === 'accept_unverified') && attack) c = 'fail';
      if (e.kind === 'gate_decision' && ['quarantine', 'reject', 'reject_timeout'].includes(g.action)) c = 'pass';
      return {seq: e.seq, t: e.t, actor: e.actor, label, c};
    });
    const cell = (row: Data, actor: string) => row.actor === actor ? `<span class="${row.c}">${esc(row.label)}</span>` : '<span class="muted">·</span>';
    const body = lanes.map((row: Data) => `<tr><td class="muted">${row.seq}</td><td class="mono">${row.t}</td><td>${cell(row, 'U')}</td><td>${cell(row, 'R')}</td><td>${cell(row, 'M')}</td><td>${cell(row, 'T')}</td></tr>`).join('');
    const gapVisible = consumedAt !== null && attack && harmExposed && verdictAt != null;
    const tEndLocal = Math.max(consumedAt || 0, verdictAt || 0, 1) * 1.1;
    const gapPct = gapVisible ? Math.min(88, ((verdictAt! - consumedAt!) / tEndLocal) * 100 + 6) : 0;
    const gapNote = !detectable && attack
      ? `이 사건은 증거 구조로 탐지할 수 없다 (${esc(a.ground_truth.attack_kind)}). 간격 자체가 정의되지 않는다.`
      : consumedAt === null ? '결정 전 소비 없음 — 간격이 0 이다. 이것이 protect·strict 가 사는 이유다.'
        : gapVisible ? `observe 모드라면 응답은 ${consumedAt} ms 에 소비되고 T 판정은 ${verdictAt} ms 에 등록된다. 이 화면의 목적은 그 간격을 숨기지 않는 것이다.`
          : '정상 사건. 소비와 판정 사이의 위험 간격 없음.';
    return `<div class="card"><h3>스윔레인 — 수집기 시퀀스 정렬</h3>
      <p class="small muted" style="margin:0 0 8px">정렬 기준은 각 당사자의 시계가 아니라 수집기가 등록한 순서(seq)다. t 는 시뮬레이션 시계이며 등록 시각은 상한으로 별도 표시된다.</p>
      <div class="tablewrap"><table style="font-size:12px"><thead><tr><th>seq</th><th>t ms</th><th>U</th><th>R</th><th>M</th><th style="color:${CV('accent')}">T</th></tr></thead><tbody>${body}</tbody></table></div>
      <h3>탐지 ≠ 방어</h3>
      <div class="gapbox"><div class="gapaxis"></div>${gapVisible ? `<div class="gapfill" style="left:4%;width:${gapPct}%"></div>` : ''}
        <div class="gaplabel-l">${consumedAt === null ? '소비 없음' : '소비 ' + consumedAt + ' ms'}</div>
        <div class="gaplabel-r">${(!detectable && attack) ? '탐지 불가' : verdictAt != null ? '탐지 ' + verdictAt + ' ms' : '—'}</div></div>
      <p class="small" style="margin-top:4px">${gapNote}</p></div>`;
  }

  // 1c 원장형: 이 사건에 등록된 진술 + 외부 앵커. 값을 바꾸는 시연 버튼은 두지 않는다.
  private ledgerCard(r: Data, a: Data): string {
    const rows = (a.registered || []).map((x: Data) => `<tr><td class="muted">${x.index}</td><td>${esc(x.content_type.replace('application/vnd.itx.', '').replace('+json', ''))}</td><td class="mono">${esc(x.iss.replace('urn:itx:party:', ''))}</td><td class="mono">≤ ${x.registered_at}</td><td class="mono">${short(x.statement_hash)}</td></tr>`).join('') || '<tr><td colspan="5" class="absent">등록된 진술 없음</td></tr>';
    const ts = r.ts, av = ts.anchors && ts.anchors[0];
    const anchorRow = av ? `<tr><td class="mono">${av.tree_size}</td><td class="mono">${short(av.anchored_root)}</td><td class="mono">${short(av.recomputed_root)}</td><td class="${av.ok ? 'pass' : 'fail'}">${esc(av.reason)}</td></tr>` : '<tr><td colspan="4" class="absent">앵커 없음</td></tr>';
    const showTamperDemo = r.run.scenario_id !== 'S14';
    return `<div class="card"><h3>원장형 — 추가 전용 로그와 외부 앵커</h3>
      <p class="small muted" style="margin:0 0 8px">블록체인의 자리는 여기 하나다 — T 가 나중에 다른 과거를 제시하지 못하게 하는 외부 체크포인트. 이 표는 실제 등록 원장이며 임의로 값을 바꾸는 시연 버튼은 두지 않는다.</p>
      <div class="tablewrap"><table style="font-size:12px"><thead><tr><th>#</th><th>진술 유형</th><th>발행</th><th>≤ 등록</th><th>해시</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="tablewrap" style="margin-top:10px"><table><thead><tr><th>앵커 크기</th><th>앵커에 고정된 루트</th><th>현재 재계산 루트</th><th>판정</th></tr></thead><tbody>${anchorRow}</tbody></table></div>
      ${showTamperDemo
        ? `<p class="small" style="margin-top:8px">운영자가 과거 항목을 실제로 교체하면 어떻게 되는지는 <button type="button" class="ledgerlink" data-jump="S14">S14 — T 의 기록 재작성</button> 시나리오에서 그대로 볼 수 있다. 트리는 다시 계산돼 스스로는 깨지지 않지만, 앵커된 루트와 달라지고 일관성 증명이 실패한다.</p>`
        : `<p class="small fail" style="margin-top:8px">이 시나리오는 앵커 이후 항목 #${ts.tampered_index} 을 교체한 사건이다. 위 판정 칸이 '재작성 감지' 로 바뀐 것을 확인한다 — 트리 자체는 재계산돼 깨지지 않았지만 외부에 고정한 루트와 달라졌다.</p>${ts.ledger_rewrite ? rewriteTableHtml(ts.ledger_rewrite) : ''}`}
    </div>`;
  }

  private renderQ1() {
    const rows = this.matrix!.q1_matrix; const sids = [...new Set(rows.map(r => r.scenario_id))];
    const cell = (r: Data | undefined) => r ? `<div class="${st(r.verification_status)}">${esc(r.verification_status)}</div><div class="small">${r.codes.length ? r.codes.map(esc).join('<br>') : '<span class="absent">코드 없음</span>'}</div><div class="small muted">완전성 ${esc(r.completeness)} · 게이트 ${esc(r.gate_action)}</div>` : '-';
    this.$('rpt-q1').innerHTML = `<table><thead><tr><th>위반 시나리오</th>${COOPS.map(c => `<th>${c}</th>`).join('')}</tr></thead><tbody>${sids.map(s => { const t = rows.find(r => r.scenario_id === s)!.title; return `<tr><td><b>${esc(s)}</b><div class="small">${esc(t)}</div></td>${COOPS.map(c => `<td>${cell(rows.find(r => r.scenario_id === s && r.cooperation === c))}</td>`).join('')}</tr>`; }).join('')}</tbody></table>`;
  }

  // 4b T 기여: 같은 사건을 T 없이(U 로컬만) · U+T protect · U+T strict 로 나란히. 없는 값(T 부재)은 없음으로 그린다.
  private renderContribution() {
    const el = this.$('rpt-tcontrib'); if (!el) return;
    const rows: Data[] = this.matrix!.t_contribution || [], sum = this.matrix!.t_contribution_summary;
    if (!rows.length || !sum) { el.innerHTML = '<p class="small absent">이 결과에는 T 기여 실험이 없다.</p>'; return; }
    const ADD: Record<string, string> = {pre_execution_refusal: '실행 전 거부 (M 이 T 에서 계약 조회)', signed_detection_record: '서명·등록된 탐지 기록', audit_finding: '감사 발견 (T 오판·재작성·누락)', complete_evidence: '증거 완전성 complete', strict_block: 'strict 추가 차단'};
    const gate = (c: Data) => `<span class="mono ${['quarantine', 'reject', 'reject_timeout'].includes(c.gate_action) ? 'fail' : c.gate_action === 'no_response' ? 'na' : c.gate_action === 'accept' ? 'pass' : 'warn'}">${esc(c.gate_action)}</span>`;
    const yn = (v: unknown) => v === null || v === undefined ? '<span class="absent">없음</span>' : v ? '<span class="pass">✓</span>' : '<span class="na">–</span>';
    const cell = (c: Data, t: boolean) => `${gate(c)}<div class="small">사용 전 차단 ${yn(c.blocked_before_use)} · 실행 전 거부 ${yn(c.model_refused_before_execution)}</div>${t ? `<div class="small muted">탐지 기록 ${yn(c.detected_by_verdict)} · 완전성 ${esc(c.completeness)} · 감사 발견 ${yn(c.audit_finding)}</div>` : '<div class="small muted">판정·감사 없음 (T 부재)</div>'}`;
    el.innerHTML = `<p class="small">공격 ${sum.attack_attempts}건 중 사용 전 차단: 로컬만 <b>${sum.attacks_blocked_local_only}</b> · U+T protect <b>${sum.attacks_blocked_with_t_protect}</b> (방어 동일 ${sum.defense_same_without_t}/${sum.scenarios}). T 가 더한 것 — 실행 전 거부 ${sum.pre_execution_refusal.join(', ') || '없음'} · 서명된 탐지 기록 ${sum.signed_detection_record.length}건 · 감사 발견 ${sum.audit_finding.join(', ') || '없음'} · strict 추가 차단 ${sum.strict_block.join(', ') || '없음'}.</p>
      <table><thead><tr><th>사건</th><th>(a) U 로컬만 · T 없음</th><th>(b) U+T protect</th><th>(c) U+T strict</th><th>T 가 더한 것</th></tr></thead><tbody>${rows.map(r => `<tr><td><b>${esc(r.scenario_id)}</b>${r.attack_present ? ' <span class="fail small">공격</span>' : ''}<div class="small">${esc(r.title)}</div></td><td>${cell(r.local_only, false)}</td><td>${cell(r.with_t_protect, true)}</td><td>${cell(r.with_t_strict, true)}</td><td class="small">${r.t_adds.length ? r.t_adds.map((a: string) => esc(ADD[a] || a)).join('<br>') : '<span class="absent">없음</span>'}</td></tr>`).join('')}</tbody></table>`;
  }

  // 1d 판정 불확실성 표현 3종
  private renderUncertainty() {
    const rows = this.matrix!.q1_matrix;
    const sids = [...new Set(rows.map(r => r.scenario_id))];
    if (!sids.includes(this.curU.sid)) this.curU.sid = sids[0];
    pills(this.$('rpt-unc-scenario-tabs'), sids.map(s => ({v: s, label: s})), v => v === this.curU.sid, v => { this.curU.sid = v; this.renderUncertainty(); });
    pills(this.$('rpt-unc-coop-tabs'), COOPS.map(c => ({v: c, label: c})), v => v === this.curU.coop, v => { this.curU.coop = v; this.renderUncertainty(); });
    const full = rows.find(r => r.scenario_id === this.curU.sid && r.cooperation === 'U+R+M')!;
    const row = rows.find(r => r.scenario_id === this.curU.sid && r.cooperation === this.curU.coop)!;
    const establishedCodes: string[] = row.codes, missingCodes: string[] = full.codes.filter((c: string) => !row.codes.includes(c));
    const coopSet = new Set(this.curU.coop.split('+'));
    const statusStyle = row.verification_status === 'insufficient_evidence'
      ? `background:${CV('card')};border:1px dashed ${CV('na')};color:${CV('na')}`
      : `background:${CV('card')};border:1px solid ${CV(st(row.verification_status))};color:${CV(st(row.verification_status))}`;
    const accepted = row.gate_action === 'accept' || row.gate_action === 'accept_unverified';
    const gateStyle = accepted ? `background:${CV('chip')};color:${CV('muted')}` : `background:${CV('card')};border:1px solid ${CV('fail')};color:${CV('fail')}`;
    const meter = ['U', 'R', 'M'].map(p => `<span class="meter-sq" style="background:${coopSet.has(p) ? CV('accent') : CV('card')};${coopSet.has(p) ? '' : 'border:1px dashed ' + CV('na')}"></span>`).join('');
    const missingParties = ['U', 'R', 'M'].filter(p => !coopSet.has(p));
    const ladder = [`<div class="ladder-row"><span class="ladder-tag pass">확립</span><span>U 가 서명한 요청 계약과 수신 진술의 자기 결합 (${esc(this.curU.coop)} 협조 수준에서 항상 확인 가능).</span></div>`];
    if (establishedCodes.length) ladder.push(`<div class="ladder-row"><span class="ladder-tag pass">확립</span><span>이 협조 수준에서 이미 드러난 위반: ${establishedCodes.map(esc).join(', ')}.</span></div>`);
    if (missingCodes.length) ladder.push(`<div class="ladder-row"><span class="ladder-tag na">미확립</span><span>이 협조 수준에서는 감춰짐: ${missingCodes.map(esc).join(', ')}. 필요한 증거: ${missingParties.map(p => p === 'R' ? 'R 중계 진술' : 'M 추론 영수증').join(', ') || '없음'}.</span></div>`);
    ladder.push(`<div class="ladder-row"><span class="ladder-tag ${accepted ? 'na' : 'fail'}">조치</span><span>protect 정책상 게이트 결정: <span class="mono">${esc(row.gate_action)}</span>.</span></div>`);
    this.$('rpt-uncertainty').innerHTML = `<div class="card"><p class="small muted" style="margin:0 0 10px">${esc(row.title)} — 협조 <b>${esc(this.curU.coop)}</b> (전체 U+R+M 결과와 비교)</p>
    <div class="grid">
      <div class="card"><div class="mono" style="font-size:10.5px;color:${CV('na')};margin:0 0 7px">(i) 세 상태 배지 — 가장 보수적</div>
        <div class="badge3"><span style="${statusStyle}">${esc(row.verification_status)}</span><span style="background:${CV('chip')};color:${CV('muted')}">completeness: ${esc(row.completeness)}</span><span style="${gateStyle}">gate: ${esc(row.gate_action)}</span></div>
        <p class="small" style="margin-top:7px">판정과 집행이 서로 다른 축임이 드러난다. 대신 "왜 부족한가" 가 안 보인다.</p></div>
      <div class="card"><div class="mono" style="font-size:10.5px;color:${CV('na')};margin:0 0 7px">(ii) 증거 커버리지 눈금 계량기 — 실측과의 거리</div>
        <div style="display:flex;align-items:center;gap:10px">${meter}<span class="mono small">${esc(this.curU.coop)} 협조${missingParties.length ? ' · ' + missingParties.map(p => p + ' 결손').join(', ') : ''}</span></div>
        <p class="small" style="margin-top:7px">종단 등식(E10)을 세우려면 M 영수증이 필요하다는 사실이 칸 수로 보인다. 다만 "칸이 많을수록 좋다" 로 오독될 위험이 있어 사용자 시험이 필요하다.</p></div>
      <div class="card"><div class="mono" style="font-size:10.5px;color:${CV('na')};margin:0 0 7px">(iii) 확립/미확립 서술 사다리</div>${ladder.join('')}
        <p class="small" style="margin-top:7px">논문·발표에 가장 잘 읽힌다. 운영 콘솔에는 길다.</p></div>
    </div></div>`;
  }

  private renderNotes() {
    this.$('rpt-notes').innerHTML = ANIM_NOTES.map(a => `<div class="animnote"><div class="t">${esc(a.title)} <span class="mono muted" style="font-size:11px">${esc(a.spec)}</span><span class="animstatus ${a.impl ? 'impl' : 'planned'}">${a.impl ? '구현됨' : '미구현'}</span></div><div class="small" style="line-height:1.5">${esc(a.body)}</div></div>`).join('')
      + `<p class="small muted" style="margin:10px 0 0;padding-top:10px;border-top:1px solid var(--line)">공통 규칙: 모션은 인과를 보이는 데만 쓰고 강조에는 쓰지 않는다. 결손·미실행은 절대 움직이지 않는다. <span class="mono">prefers-reduced-motion</span> 에서는 이 앱의 모든 재생이 최종 상태로 즉시 점프한다.</p>`;
  }
}
