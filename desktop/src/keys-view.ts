// 「키 · 신뢰 기준점」 — 사설키가 이 기계 밖으로 나가는가.
//
// 화면이 지키는 규칙 세 가지.
//  - 판단 기준 열은 보관처가 아니라 **평문 노출 여부** 한 칸이다.
//  - 약한 보관처는 fail 이 아니라 **점선 배지 + 경고**다. 로컬 파일 키는 위반이
//    아니라 운영 위험이고, 그 키로 만든 서명도 암호학적으로는 유효하다.
//  - 키 계보(생성·회전·폐기)는 판정과 다른 시간축이므로 이 화면에만 둔다.
import {Data, esc} from './console';

type Filter = 'all' | 'exposed' | 'overdue';

const TAG_TONE: Record<string, string> = {
  created: 'pass', anchored: 'accent', planned: 'na', overdue: 'warn',
  rotated: 'accent', software: 'warn', self: 'warn', none: 'na',
};
const TAG_LABEL: Record<string, string> = {
  created: '온보드 생성', anchored: '원장 등록', planned: '예정', overdue: '기한 초과',
  rotated: '회전 완료', software: '소프트웨어', self: '자기 서명', none: '없음',
};

export class KeysView {
  private state: {sel: string; filter: Filter} = {sel: 'T', filter: 'all'};
  private data: Data | null = null;

  constructor(private root: HTMLElement,
              private call: <T = Data>(op: string, args?: Data) => Promise<T>,
              private fail: (error: unknown) => void) {}

  async show() {
    try {
      this.data = await this.call<Data>('key_inventory');
      const keys = (this.data?.keys ?? []) as Data[];
      if (!keys.some(k => k.role === this.state.sel)) this.state.sel = String(keys[0]?.role ?? 'T');
      this.render();
    } catch (e) { this.fail(e); }
  }

  private current(): Data | null {
    const keys = (this.data?.keys ?? []) as Data[];
    return keys.find(k => k.role === this.state.sel) ?? keys[0] ?? null;
  }

  private render() {
    if (!this.data) return;
    const cur = this.current();
    this.root.innerHTML = this.headHtml() + this.tableHtml() +
      `<div class="key-grid">${cur ? this.chainHtml(cur) + this.lineageHtml(cur) : ''}</div>` +
      this.anchorsHtml();
    this.wire();
  }

  private headHtml(): string {
    const s = this.data!.summary as Data;
    const cell = (label: string, value: string, tone = '') =>
      `<div class="std-stat"><div class="k">${label}</div><div class="v ${tone}">${value}</div></div>`;
    return `<div class="std-head">
      <div class="std-head-text">
        <div class="eyebrow">ITX · 키 · 신뢰 기준점</div>
        <h1>사설키가 이 기계 밖으로 나가는가</h1>
        <p>${esc(this.data!.note)}</p>
      </div>
      <div class="std-stats">
        ${cell('평문 노출 없음', `${s.sealed}<span class="of">/${s.total}</span>`, 'pass')}
        ${cell('메모리 평문', String(s.exposed), Number(s.exposed) ? 'warn' : 'na')}
        ${cell('회전 기한 초과', String(s.overdue), Number(s.overdue) ? 'warn' : 'na')}
      </div>
    </div>`;
  }

  private tableHtml(): string {
    const filters: [Filter, string][] = [['all', '전체'], ['exposed', '평문 노출'], ['overdue', '기한 초과']];
    const pills = filters.map(([k, label]) =>
      `<button type="button" class="pill${this.state.filter === k ? ' on' : ''}" data-filter="${k}">${label}</button>`).join('');
    const keys = ((this.data!.keys ?? []) as Data[]).filter(k =>
      this.state.filter === 'all' ? true
        : this.state.filter === 'exposed' ? k.exposed : Number(k.overdue_days) > 0);
    const rows = keys.map(k => {
      const over = Number(k.overdue_days) > 0;
      const days = Number(k.rotation_days), max = Number(k.rotation_max) || 90;
      const width = Math.min(100, days / max * 100).toFixed(1);
      const rot = !days ? '기록 없음' : over ? `기한 +${k.overdue_days}일 초과` : `${days} / ${max}일`;
      return `<div class="key-row${k.role === this.state.sel ? ' sel' : ''}" data-role="${esc(k.role)}" tabindex="0">
        <span class="role-badge">${esc(k.role)}</span>
        <span class="id"><b class="mono">${esc(k.kid)}</b><span class="mono na">${esc(k.purpose)}</span></span>
        <span class="store"><span class="store-badge${k.exposed ? ' weak' : ''}">${esc(k.store_label)}</span></span>
        <span class="exposure">
          <b class="mono ${k.exposed ? 'warn' : 'pass'}">${k.exposed ? '메모리 평문' : '평문 노출 없음'}</b>
          <span class="mono na">${esc(k.exposure_note)}</span></span>
        <span class="rot">
          <span class="mono ${over ? 'warn' : days ? 'accent' : 'na'}">${rot}</span>
          <span class="bar"><span style="width:${days ? width : 0}%;background:var(--${over ? 'warn' : 'accent'})"></span></span></span>
        <span class="signs mono na">${k.sign_count || '—'}</span>
      </div>`;
    }).join('');
    return `<section class="card std-card">
      <div class="std-card-head"><b>서명 키 인벤토리</b>
        <span class="small muted">행을 누르면 아래 계보 · 서명 경로가 그 키로 바뀝니다</span>
        <span class="std-tabs">${pills}</span></div>
      <div class="key-table">
        <div class="key-head"><span></span><span>키 식별자</span><span>보관처</span><span>평문 노출</span><span>회전</span><span class="r">서명 건수</span></div>
        ${rows || '<div class="std-absent">이 조건에 맞는 키가 없습니다.</div>'}
      </div>
    </section>`;
  }

  private chainHtml(k: Data): string {
    const chain = ((k.chain ?? []) as Data[]).map((c, i, all) => `
      <div class="key-step">
        <div class="box${c.inside ? ' inside' : ''}">
          <b class="mono">${esc(c.title)}</b>
          <span>${esc(c.sub)}</span>
          <span class="mono na">${esc(c.at)}</span>
        </div>
        ${i < all.length - 1 ? '<span class="arrow mono">→</span>' : ''}
      </div>`).join('');
    const ms = Number(k.round_trip_ms);
    return `<section class="card std-card">
      <div class="std-card-head"><span class="role-badge">${esc(k.role)}</span>
        <b>원격 서명 경로</b><span class="mono na">${esc(k.kid)}</span></div>
      <div class="key-chain">${chain}</div>
      <div class="key-boundary ${k.exposed ? 'weak' : 'strong'}">${esc(k.boundary)}</div>
      <div class="key-latency">
        <div class="std-label">타임라인 반영</div>
        <p class="small">${ms
          ? `원격 서명 왕복 <b class="mono">+${ms} ms</b> 가 타임라인의 「서명」 마커에 합산됩니다. KMS 도입의 실제 대가는 지연이므로 숨기지 않습니다.`
          : '로컬 서명이라 왕복이 없습니다. 이 화면이 보여 주는 것은 지연이 아니라 그 대가입니다.'}</p>
      </div>
    </section>`;
  }

  private lineageHtml(k: Data): string {
    const events = (k.lineage ?? []) as Data[];
    const rows = events.map((e, i) => {
      const tone = TAG_TONE[String(e.kind)] ?? 'na';
      const dashed = ['software', 'self', 'overdue'].includes(String(e.kind));
      return `<div class="key-event">
        <span class="rail"><span class="dot" style="background:var(--${tone});border-color:var(--${tone})"></span>
          ${i < events.length - 1 ? '<span class="line"></span>' : ''}</span>
        <span class="body">
          <span class="h"><b class="${tone === 'warn' ? 'warn' : ''}">${esc(e.title)}</b>
            <span class="mono na">${esc(e.at)}</span>
            <span class="tag${dashed ? ' dashed' : ''}" style="color:var(--${tone});border-color:var(--${tone})">${TAG_LABEL[String(e.kind)] ?? esc(e.kind)}</span></span>
          <span class="t small">${esc(e.body)}</span>
          ${e.meta ? `<span class="mono na small">${esc(e.meta)}</span>` : ''}
        </span>
      </div>`;
    }).join('');
    return `<section class="card std-card">
      <div class="std-card-head"><b>키 계보</b>
        <span class="small muted">생성 · 회전 · 폐기 — 요청 판정과 다른 시간축</span></div>
      <div class="key-lineage">${rows}</div>
    </section>`;
  }

  private anchorsHtml(): string {
    const cards = ((this.data!.anchors ?? []) as Data[]).map(a => `
      <div class="key-anchor ${a.tone === 'present' ? '' : 'absent'}">
        <div class="h"><b>${esc(a.title)}</b>
          <span class="tag${a.tone === 'present' ? '' : ' dashed'}" style="color:var(--${a.tone === 'present' ? 'accent' : 'na'});border-color:var(--${a.tone === 'present' ? 'accent' : 'na'})">${esc(a.tag)}</span></div>
        <p class="small">${esc(a.body)}</p>
        <div class="rows">${((a.rows ?? []) as [string, string][]).map(([key, value]) =>
          `<div><span class="mono na">${esc(key)}</span><span class="mono">${esc(value)}</span></div>`).join('')}</div>
      </div>`).join('');
    return `<section class="card std-card">
      <div class="std-card-head"><b>신뢰 기준점</b>
        <span class="small muted">U 가 무엇을 근거로 상대 키를 믿는가 — 이 목록이 판정 전체의 뿌리입니다</span></div>
      <div class="key-anchors">${cards}</div>
    </section>`;
  }

  private wire() {
    this.root.querySelectorAll<HTMLElement>('[data-role]').forEach(n => {
      const pick = () => { this.state.sel = n.dataset.role!; this.render(); };
      n.onclick = pick;
      n.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } };
    });
    this.root.querySelectorAll<HTMLElement>('[data-filter]').forEach(n => {
      n.onclick = () => { this.state.filter = n.dataset.filter as Filter; this.render(); };
    });
  }
}
