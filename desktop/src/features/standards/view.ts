import type { Data } from '../../shared/types';
// 「표준 적합성」 — 이 증거는 남의 도구로도 검증되는가.
//
// 화면이 지키는 규칙 두 가지.
//  - 적합성은 통과/실패가 아니라 **벡터 개수**로 적는다. 12/12 와 3/5 가 한 화면에
//    있어야 주장 범위가 정확해진다.
//  - 미구현 항목은 지우지 않고 **회색 결손 행**으로 남긴다. 표준 대비 어디까지
//    왔는지가 이 화면의 본문이다.
import { esc } from '../../shared/console';

type State = {doc: string; view: 'hex' | 'diag'; open: Record<string, boolean>; showAbsent: boolean};

const GLYPH: Record<string, string> = {pass: '✓', partial: '!', absent: '–', fail: '✗'};
const TONE: Record<string, string> = {pass: 'pass', partial: 'warn', absent: 'na', fail: 'fail'};
const VERDICT: Record<string, string> = {pass: '통과', partial: '부분', absent: '미실행', fail: '불일치'};

const pct = (n: number, d: number) => d ? +(n / d * 100).toFixed(1) : 0;

export class StandardsView {
  // 기본 문서는 U — 이 기계가 키를 가진 유일한 문서이고, 따라서 COSE 쪽이 실제로 채워진다.
  private state: State = {doc: 'U', view: 'hex', open: {cose: true}, showAbsent: true};
  private data: Data | null = null;
  private sub = '';

  constructor(private root: HTMLElement,
              private call: <T = Data>(op: string, args?: Data) => Promise<T>,
              private fail: (error: unknown) => void) {}

  /** 사건 기록에서 이 화면으로 들어올 때 그 요청의 문서를 보여 준다. */
  async show(sub = this.sub) {
    this.sub = sub;
    try {
      this.data = await this.call('standards', sub ? {sub} : {});
      this.render();
    } catch (e) { this.fail(e); }
  }

  private current(): Data | null {
    const docs = (this.data?.documents ?? []) as Data[];
    return docs.find(d => d.role === this.state.doc) ?? docs[0] ?? null;
  }

  private render() {
    if (!this.data) return;
    const cur = this.current();
    this.root.innerHTML = this.headHtml() + `<div class="std-split">
      ${this.asideHtml()}
      <div class="std-main">${cur ? this.docHtml(cur) + this.toolsHtml() + this.vectorsHtml(cur) + this.exportHtml(cur) : ''}</div>
    </div>`;
    this.wire();
  }

  private headHtml(): string {
    const t = this.data!.totals as Data;
    const cell = (label: string, value: string, tone = '') =>
      `<div class="std-stat"><div class="k">${label}</div><div class="v ${tone}">${value}</div></div>`;
    return `<div class="std-head">
      <div class="std-head-text">
        <div class="v3-meta">검증 · 감사</div>
        <h1>이 증거는 남의 도구로도 검증되는가</h1>
        <p>같은 문서를 자체 JSON 프로파일과 COSE_Sign1 바이너리로 나란히 놓고, 벡터를 실제로 실행해 통과한 수를 셉니다. 미구현 항목은 지우지 않고 결손 행으로 남깁니다.</p>
      </div>
      <div class="std-stats">
        ${cell('통과 벡터', `${t.pass}<span class="of">/${t.total}</span>`)}
        ${cell('부분 적합', String(t.partial), 'warn')}
        ${cell('미실행', String(t.absent), 'na')}
        ${Number(t.fail) ? cell('불일치', String(t.fail), 'fail') : ''}
      </div>
    </div>`;
  }

  private asideHtml(): string {
    const docs = (this.data!.documents ?? []) as Data[];
    const claim = String(this.data!.claim_status ?? 'planned');
    const items = docs.map(d => {
      const c = d.counts as Data;
      const tone = c.fail ? 'fail' : (c.absent || c.partial) ? 'partial' : 'pass';
      return `<button type="button" class="std-doc${d.role === this.state.doc ? ' on' : ''}" data-doc="${esc(d.role)}">
        <span class="row"><span class="role-badge">${esc(d.role)}</span>
          <span class="name">${esc(d.name)}</span>
          <span class="score ${TONE[tone]}">${c.pass}/${d.total}</span></span>
        <span class="sub">${esc(d.subtitle)}</span>
        <span class="meter"><span style="width:${pct(Number(c.pass), Number(d.total))}%;background:var(--${TONE[tone]})"></span></span>
      </button>`;
    }).join('');
    return `<aside class="std-aside">
      <div class="std-label">증거 문서</div>${items}
      <div class="std-claim">
        <div class="std-label">주장 상태</div>
        <p class="mono ${TONE[claim === 'verified_external' ? 'pass' : claim === 'mock_result' ? 'fail' : 'absent']}">${esc(claim)}</p>
        <p>${claim === 'verified_external'
          ? '우리 벡터가 모두 통과했고, 제3자 구현도 같은 바이트를 검증했습니다. 그래도 표준 준수 <b>전체</b>를 주장하지는 않습니다 — 미실행 항목이 남아 있습니다.'
          : claim === 'mock_result'
            ? '제3자 구현이 우리 출력을 거부했습니다. 회귀이므로 먼저 고쳐야 합니다.'
            : '교차 검증 도구가 없어 순환을 벗어나지 못했습니다. 우리 벡터만으로는 표준 준수를 주장할 수 없습니다.'}</p>
      </div>
    </aside>`;
  }

  private docHtml(d: Data): string {
    const tabs = (['hex', 'diag'] as const).map(v =>
      `<button type="button" class="pill${this.state.view === v ? ' on' : ''}" data-view="${v}">${v === 'hex' ? 'CBOR hex' : 'CBOR diagnostic'}</button>`).join('');
    if (!d.available) return `<section class="card std-card"><div class="std-card-head">
        <span class="role-badge">${esc(d.role)}</span><b>${esc(d.name)}</b></div>
      <div class="std-absent">${esc(d.reason)}</div></section>`;

    const right = d.reissuable
      ? `<pre>${esc(this.state.view === 'hex' ? d.cose_hex : d.cose_diagnostic)}</pre>`
      : `<div class="std-absent">${esc(d.reason)}</div>`;
    const rows = ((d.structure ?? []) as Data[]).map((r, i) => `<div class="std-trow">
        <span class="i">${String(i + 1).padStart(2, '0')}</span>
        <span class="k" style="padding-left:${Number(r.indent)}px">${esc(r.key)}</span>
        <span class="v">${esc(r.value)}</span>
        <span class="n ${TONE[String(r.state)]}">${esc(r.note)}</span>
      </div>`).join('');
    return `<section class="card std-card">
      <div class="std-card-head">
        <span class="role-badge">${esc(d.role)}</span><b>${esc(d.name)}</b>
        <span class="mono muted">${esc(d.file)}</span>
        <span class="std-tabs">${tabs}</span>
      </div>
      <div class="std-encodings">
        <div class="std-enc legacy">
          <div class="h"><span>자체 JSON 프로파일</span><span class="muted">${d.json_bytes} B</span></div>
          <pre>${esc(d.json)}</pre>
        </div>
        <div class="std-enc standard${d.reissuable ? '' : ' absent'}">
          <div class="h"><span>COSE_Sign1 · ${this.state.view === 'hex' ? 'CBOR hex' : 'diagnostic'}</span><span class="muted">${d.cose_bytes ? d.cose_bytes + ' B' : '—'}</span></div>
          ${right}
        </div>
      </div>
      ${rows ? `<div class="std-tree"><div class="h">COSE_Sign1 구조</div>${rows}</div>` : ''}
    </section>`;
  }

  private toolsHtml(): string {
    const cross = (this.data!.external ?? {}) as Data;
    const tools = (cross.tools ?? []) as Data[];
    const rows = tools.map(t => {
      const checks = ((t.checks ?? []) as Data[]).map(c => `<div class="std-vec">
        <span class="g ${TONE[String(c.state)]}">${GLYPH[String(c.state)]}</span>
        <span class="label">${esc(c.label)}</span>
        <span class="note mono na">${esc(c.detail ?? '')}</span>
      </div>`).join('');
      return `<div class="std-tool">
        <div class="h"><b class="mono">${esc(t.tool)}</b><span class="mono muted">${esc(t.version)}</span>
          <span class="mono ${TONE[String(t.state)]}">${VERDICT[String(t.state)]}</span></div>
        <div class="small na">${esc(t.note)}</div>
        ${checks ? `<div class="std-checks">${checks}</div>` : ''}
      </div>`;
    }).join('');
    const tone = TONE[String(cross.claim_status) === 'verified_external' ? 'pass'
      : String(cross.claim_status) === 'mock_result' ? 'fail' : 'absent'];
    return `<section class="card std-card">
      <div class="std-card-head"><b>제3자 구현 교차 검증</b>
        <span class="small muted">itx 코드가 아니라 남이 만든 구현이 같은 바이트를 읽는지를 봅니다</span>
        <button type="button" class="itx-btn" id="std-copy">재현 명령 복사</button></div>
      <div class="std-cross ${tone}">${esc(cross.summary)}</div>
      <div class="std-tools">${rows || '<div class="std-absent">교차 검증 도구가 없습니다.</div>'}</div>
      ${cross.note ? `<div class="std-crossnote small na">${esc(cross.note)}</div>` : ''}
    </section>`;
  }

  private vectorsHtml(d: Data): string {
    const groups = ((d.groups ?? []) as Data[]).map(g => {
      const c = g.counts as Data;
      const tone = c.fail ? 'fail' : c.absent === g.total ? 'absent' : (c.absent || c.partial) ? 'partial' : 'pass';
      const open = !!this.state.open[String(g.key)];
      const items = ((g.items ?? []) as Data[])
        .filter(v => this.state.showAbsent || v.state !== 'absent')
        .map(v => `<div class="std-vec">
          <span class="g ${TONE[String(v.state)]}">${GLYPH[String(v.state)]}</span>
          <span class="id mono">${esc(v.id)}</span>
          <span class="label${v.state === 'absent' ? ' muted' : ''}">${esc(v.label)}</span>
          <span class="note mono na">${esc(v.note)}</span>
        </div>`).join('');
      return `<div class="std-group">
        <button type="button" class="std-ghead" data-group="${esc(g.key)}">
          <span class="g ${TONE[tone]}">${GLYPH[tone]}</span>
          <span class="t"><b>${esc(g.title)}</b><span class="mono na">${esc(g.spec)} · 벡터 ${g.total}종</span></span>
          <span class="meter"><span style="width:${pct(Number(c.pass), Number(g.total))}%;background:var(--${TONE[tone]})"></span></span>
          <span class="score mono ${TONE[tone]}">${c.pass}/${g.total}</span>
          <span class="caret mono">${open ? '▾' : '▸'}</span>
        </button>
        ${open ? `<div class="std-vecs">${items}</div>` : ''}
      </div>`;
    }).join('');
    return `<section class="card std-card">
      <div class="std-card-head"><b>적합성 벡터</b>
        <span class="small muted">행을 누르면 개별 벡터가 펼쳐집니다</span>
        <button type="button" class="itx-btn${this.state.showAbsent ? ' on' : ''}" id="std-absent">${this.state.showAbsent ? '미실행 숨기기' : '미실행 표시'}</button></div>
      ${groups}
    </section>`;
  }

  private exportHtml(d: Data): string {
    return `<div class="card std-export">
      <div><b>내보내기</b>
        <div class="small muted">${esc(d.name)} 를 COSE_Sign1 바이너리로 내보냅니다. 검증 명령은 README 로 함께 나갑니다.
        ${d.reissuable ? '' : ' 이 문서는 발행자만 재발행할 수 있어 제외됩니다.'}</div></div>
      <button type="button" class="itx-btn itx-btn-accent" id="std-export">.cose 내보내기</button>
    </div>`;
  }

  private wire() {
    const on = (selector: string, handler: (el: HTMLElement) => void) =>
      this.root.querySelectorAll<HTMLElement>(selector).forEach(n => { n.onclick = () => handler(n); });

    on('[data-doc]', n => { this.state.doc = n.dataset.doc!; this.render(); });
    on('[data-view]', n => { this.state.view = n.dataset.view as 'hex' | 'diag'; this.render(); });
    on('[data-group]', n => {
      const key = n.dataset.group!;
      this.state.open = {...this.state.open, [key]: !this.state.open[key]};
      this.render();
    });
    const absent = this.root.querySelector<HTMLElement>('#std-absent');
    if (absent) absent.onclick = () => { this.state.showAbsent = !this.state.showAbsent; this.render(); };

    const copy = this.root.querySelector<HTMLButtonElement>('#std-copy');
    if (copy) copy.onclick = async () => {
      const text = '$ ' + String(((this.data!.external ?? {}) as Data).reproduce ?? '');
      try { await navigator.clipboard.writeText(text); copy.textContent = '복사됨'; }
      catch { copy.textContent = '복사 실패'; }
      setTimeout(() => { copy.textContent = '재현 명령 복사'; }, 1600);
    };

    const exportBtn = this.root.querySelector<HTMLButtonElement>('#std-export');
    if (exportBtn) exportBtn.onclick = async () => {
      exportBtn.disabled = true;
      try {
        const result = await this.call<Data>('cose_export', this.sub ? {sub: this.sub} : {});
        const written = (result.written as Data[]) ?? [];
        const skipped = (result.skipped as string[]) ?? [];
        exportBtn.textContent = written.length
          ? `${written.length}건 저장${skipped.length ? ` · ${skipped.join('·')} 제외` : ''}`
          : '내보낼 문서 없음';
      } catch (e) { this.fail(e); exportBtn.textContent = '.cose 내보내기'; }
      finally {
        exportBtn.disabled = false;
        setTimeout(() => { exportBtn.textContent = '.cose 내보내기'; }, 2600);
      }
    };
  }
}
