import type { Data } from '../../shared/types';
// 제3자 검증 화면: replay_audit 결과를 다이어그램(좌)과 그 근거 JSON(우)으로 나란히 보인다.
// 다이어그램의 모든 요소는 JSON 경로(data-ref)를 가리키고, JSON 의 모든 줄은 경로(data-path)를 갖는다.
// 그래프를 누르면 JSON 이 그 자리로 스크롤·강조되고, JSON 줄에 커서를 올리면 그래프의 대응 요소가 펄스한다.
// 색은 판정에만 쓴다: 헤드 일치·앵커 일치·판정 일치는 pass/fail, 연동 강조는 accent 뿐이다.
// 그림은 감사 결과에 있는 값만 그린다. 잎의 내용·서명자는 결과에 없으므로 그리지 않는다 — 없는 것을 있는 척하지 않는다.
import { esc, short, st, reducedMotion, copyText } from '../../shared/console';

const HEX64 = /^[0-9a-f]{64}$/i;
const STATUS_KO: Record<string, string> = {passed: '통과', failed: '실패', insufficient_evidence: '증거 부족'};
const fmtTime = (ms: unknown) => typeof ms === 'number' ? new Date(ms).toLocaleString('ko-KR') : '—';
const pct = (n: number, total: number) => total > 0 ? (n / total * 100).toFixed(2) + '%' : '0%';
const status = (v: Data | null | undefined) => v ? `<b class="${st(v.verification_status)}">${esc(STATUS_KO[v.verification_status] || v.verification_status)}</b>` : '<span class="absent">판정 없음</span>';
// 다이어그램 요소: 버튼 안에 해시 복사 칩(role=button)을 둘 수 없어 div 에 역할을 준다.
const ref = (path: string, cls: string, inner: string, title = '') =>
  `<div class="ref ${cls}" data-ref="${esc(path)}" role="button" tabindex="0"${title ? ` title="${esc(title)}"` : ''}>${inner}</div>`;

export function renderAudit(root: HTMLElement, a: Data) {
  root.innerHTML = `${summaryHtml(a)}
    <div class="audit-split">
      <div class="audit-canvas">
        <h3>1. 머클 트리 헤드 · 체크포인트 앵커</h3>${bridgeHtml(a)}
        <h3>2. 요청별 판정 대조 — T 가 등록한 판정 vs 감사자의 독립 재계산</h3>${comparatorHtml(a)}
        ${problemsHtml(a)}
      </div>
      <div class="audit-json">
        <div class="json-toolbar">
          <input type="search" class="json-search" placeholder="키·값·경로 검색 (예: recomputed_root, E10, failed)" aria-label="JSON 검색">
          <button type="button" class="quiet" data-json-only-bad title="불일치·결손 경로만 남긴다">불일치 항목만 보기</button>
          <button type="button" class="quiet" data-json-expand title="모두 펼치기">펼치기</button>
          <button type="button" class="quiet" data-json-collapse title="모두 접기">접기</button>
          <button type="button" class="quiet" data-json-copy title="전체 JSON 을 클립보드로">전체 복사</button>
        </div>
        <div class="json-tree" data-json-root>${jsonNode(a, '', null, true)}</div>
      </div>
    </div>`;
  wire(root, a);
}

// ---------- 요약 카드 4장 (Console v3) ----------
// 트리 헤드 서명 · 앵커 일치 · 전수 검사 · 목격자 독립성. 값은 replay_audit 결과에 있는 것만 쓴다.
export function auditCardsHtml(a: Data): string {
  const head: Data = a.current_checkpoint || {};
  const anchors: Data[] = a.anchors || [];
  const mism: Data[] = a.verdict_mismatches || [];
  const headOk = !!a.tree_recomputed_matches_head && !!a.head_signature_valid;
  const anchorTone = !anchors.length ? 'na' : anchors.every(x => x.ok) ? 'pass' : 'fail';
  const cards: {k: string; v: string; n: string; tone: string}[] = [
    {k: '트리 헤드 서명', v: headOk ? '검증 통과' : a.head_signature_valid ? '루트 불일치' : '서명 무효',
     n: `kid ${esc(head.ts_kid || '—')} · tree_size ${head.tree_size ?? '—'}`, tone: headOk ? 'pass' : 'fail'},
    {k: '앵커 일치', v: anchorTone === 'na' ? '첫 체크포인트' : anchorTone === 'pass' ? '일치' : '불일치 — 재작성 감지',
     n: anchorTone === 'na' ? '다음 감사부터 이 시점과 비교합니다' : '게시 방식은 파일 기반 모사입니다', tone: anchorTone},
    {k: '전수 검사', v: mism.length ? `불일치 ${mism.length}건` : '전부 일치',
     n: `판정 ${a.verdict_count ?? 0}건 · 요청 ${a.subs_checked ?? 0}건${(a.compared_without || []).length ? ` · 비교 제외 ${a.compared_without.join(',')}` : ''}`, tone: mism.length ? 'fail' : 'pass'},
    {k: '목격자 독립성', v: '관측 불가', n: esc(a.witness_scope || '별도 운영 목격자 없음 — 분기 탐지 성립 안 함'), tone: 'na'},
  ];
  const glyph = (t: string) => t === 'pass' ? '✓' : t === 'fail' ? '✗' : '–';
  return cards.map(c => `<div class="v3-stat ${c.tone}"><div class="k">${c.k}</div><div class="v ${c.tone}"><span class="g">${glyph(c.tone)}</span><span>${c.v}</span></div><div class="n">${c.n}</div></div>`).join('');
}

// ---------- 요약 ----------
function summaryHtml(a: Data): string {
  const ok = !!a.ok;
  const label = ok ? (a.private_scope === 'partial' ? '공개 검사 일치 · 비공개 일부 미검증' : '모든 과거 판정 감사 일치') : '불일치 또는 미완료 증거 발견';
  const stats: [string, string, string][] = [
    ['T 신원·정책', a.pinned_identity ? '고정 기준 확인' : '미확인', 'pinned_identity'],
    ['과거 판정 전수 검사', `${a.verdict_count ?? 0}건 · 요청 ${a.subs_checked ?? 0}건`, 'verdict_count'],
    ['불일치 요청', `${(a.verdict_mismatches || []).length}건`, 'verdict_mismatches'],
  ];
  return `<div class="audit-summary">
    <span class="badge ${ok ? 'green' : 'red'}">${esc(label)}</span>
    <span class="small muted">검사기 ${esc(a.auditor_checker_version || '—')} · 범위 ${esc(a.audit_scope || '—')} · ${esc(a.witness_scope || '')}</span>
    <div class="stat-row">${stats.map(([k, v, p]) => ref(p, 'stat', `<small>${esc(k)}</small><strong>${esc(v)}</strong>`)).join('')}</div>
    <p class="field-help">${a.previous_checkpoint ? '이전에 사용자 PC에 보관한 체크포인트와 비교했습니다.' : '첫 체크포인트입니다. 다음 감사부터 이전 이력과 비교합니다.'} 왼쪽 요소를 누르면 오른쪽 JSON 의 근거 위치로 이동하고, JSON 줄에 커서를 올리면 왼쪽의 대응 요소가 표시됩니다.</p>
  </div>`;
}

// ---------- 1. 헤드 대조 · 잎 리본 · 앵커 핀 ----------
function bridgeHtml(a: Data): string {
  const head: Data = a.current_checkpoint || {};
  const n: number = head.tree_size ?? 0;
  const treeOk = !!a.tree_recomputed_matches_head, sigOk = !!a.head_signature_valid;
  const anchors: Data[] = a.anchors || [];
  // '고정 구간' 은 일관성 증명이 실제로 성립한 앵커까지만이다. 실패한 앵커(기록 재작성)의 구간을 고정된 것처럼 그리지 않는다.
  const locked = Math.max(0, ...anchors.filter(x => x.ok).map(x => x.tree_size as number));
  const verdicts: Data[] = a.verdicts_checked || [];

  const heads = `<div class="bridge-heads">
    ${ref('current_checkpoint.root_hash', 'node', `<div class="k">T 서명 헤드 · ${esc(head.log_id || '로그')}</div><div class="v">${short(head.root_hash)}</div><div class="s">tree_size ${n} · ${esc(fmtTime(head.time))}</div>`, 'T 가 서명해 제시한 현재 트리 헤드')}
    <div class="bridge-link ${treeOk && sigOk ? 'pass' : 'fail'}"><span class="wire"></span><span class="tag">${treeOk ? '≡ 루트 일치' : '≠ 루트 불일치'} · ${sigOk ? '서명 유효' : '서명 무효'}</span></div>
    ${ref('tree_recomputed_matches_head', 'node', `<div class="k">감사자 재계산</div><div class="v ${treeOk ? 'pass' : 'fail'}">${treeOk ? '✓ 잎에서 다시 계산한 루트가 헤드와 같다' : '✗ 다시 계산한 루트가 헤드와 다르다'}</div><div class="s">${sigOk ? '헤드 서명은 고정한 T 키로 검증됨' : '헤드 서명 검증 실패'}</div>`, '감사자가 로그 잎을 모두 다시 해시해 얻은 루트')}
  </div>`;

  // 잎 리본: 결과에 있는 값(트리 크기·앵커 크기·판정 잎 위치)만 그린다.
  const ticks = verdicts.map((v, i) => typeof v.log_index === 'number'
    ? `<div class="tick ${v.match ? 'pass' : 'fail'} ref" data-ref="verdicts_checked.${i}" role="button" tabindex="0" style="left:${pct(v.log_index + .5, n)}" title="잎 #${v.log_index} · T 판정 (${v.match ? '재계산과 일치' : '재계산과 불일치'})"></div>` : '').join('');
  const pins = anchors.map((x, i) => `<div class="pin ${x.ok ? 'pass' : 'fail'} ref" data-ref="anchors.${i}" role="button" tabindex="0" style="left:${pct(x.tree_size, n)}" title="앵커 tree_size ${x.tree_size} · ${esc(x.reason)}"><span>◆</span></div>`).join('');
  const cells = n > 0 && n <= 96 ? `<div class="leafcells" style="--n:${n}">${Array.from({length: n}, (_, k) => {
    const vi = verdicts.findIndex(v => v.log_index === k);
    const kind = k === 0 ? ' policy' : vi >= 0 ? (verdicts[vi].match ? ' verdict pass' : ' verdict fail') : '';
    const attrs = vi >= 0 ? ` data-ref="verdicts_checked.${vi}" role="button" tabindex="0"` : '';
    return `<div class="leaf${k < locked ? ' locked' : ' appended'}${kind}${vi >= 0 ? ' ref' : ''}"${attrs} title="잎 #${k}${k === 0 ? ' · 정책 진술' : ''}${vi >= 0 ? ' · T 판정' : ''}"></div>`;
  }).join('')}</div>` : '';
  const ribbon = n > 0 ? `<div class="ribbon">
    <div class="ribbon-bar">
      ${locked > 0 ? `<div class="seg locked" style="left:0;width:${pct(locked, n)}" title="앵커로 고정된 구간 · 잎 0~${locked - 1}"></div>` : ''}
      <div class="seg appended" style="left:${pct(locked, n)};width:${pct(n - locked, n)}" title="앵커 이후 추가된 잎 · ${locked}~${n - 1}"></div>
      <div class="tick policy" style="left:${pct(.5, n)}" title="잎 #0 · 정책 진술"></div>
      ${ticks}${pins}
    </div>
    ${cells}
    <div class="ribbon-scale"><span>잎 0 (정책)</span>${locked > 0 ? `<span class="lock">▮ 고정 구간 0~${locked - 1} — 앵커 시점 이전 기록은 RFC 9162 일관성 증명으로 변경 없음 확인</span>` : ''}<span>잎 ${n - 1}</span></div>
    <div class="legend-row"><span><i class="sw locked"></i> 앵커로 고정된 잎</span><span><i class="sw appended"></i> 앵커 이후 추가된 잎</span><span><i class="sw tickswatch"></i> T 판정 잎 (색은 재계산과의 일치)</span><span><i class="sw pinswatch"></i> ◆ 체크포인트 앵커</span></div>
  </div>` : '<p class="small absent">트리 헤드 정보 없음</p>';

  const anchorList = anchors.length
    ? anchors.map((x, i) => ref(`anchors.${i}`, `anchor ${x.ok ? 'pass' : 'fail'}`,
        `<span class="pinglyph">◆</span><span class="mono">tree_size ${x.tree_size}</span> · 앵커 루트 ${short(x.anchored_root)} → 재계산 ${short(x.recomputed_root)}
         <span class="small">· 루트 ${x.root_matches ? '<span class="pass">일치</span>' : '<span class="fail">불일치</span>'} · 헤드까지 일관성 ${x.consistent_with_head ? '<span class="pass">성립</span>' : '<span class="fail">불성립</span>'}</span>
         <b class="${x.ok ? 'pass' : 'fail'}">${esc(x.reason)}</b><span class="small muted"> · 앵커 시각 ${esc(fmtTime(x.anchored_at))}</span>`)).join('')
    : `<div class="anchor none"><span class="pinglyph">◆</span>비교할 앵커 없음 — 첫 체크포인트. 이번 헤드를 사용자 PC 에 보관하고 다음 감사부터 이 시점과 비교한다.</div>`;
  return `<div class="bridge">${heads}${ribbon}<div class="anchors">${anchorList}</div></div>`;
}

// ---------- 2. 판정 대조 ----------
function comparatorHtml(a: Data): string {
  const verdicts: Data[] = a.verdicts_checked || [];
  if (!verdicts.length) return '<p class="small absent">재계산할 요청 판정이 없다.</p>';
  const mismatches: Data[] = a.verdict_mismatches || [];
  const rows = verdicts.map((v, i) => {
    const j = mismatches.findIndex(m => m.sub === v.sub);
    const r: Data = v.recomputed || {}, t: Data | null = v.t_verdict;
    const head = ref(`verdicts_checked.${i}`, `vhead ${v.match ? 'ok' : 'bad'}`,
      `<span class="mono">${short(v.sub)}</span>
       <span class="vt">T 등록 판정 ${status(t)}</span><span class="veq ${v.match ? 'pass' : 'fail'}">${v.match ? '≡' : '≠'}</span><span class="vt">감사자 재계산 ${status(r)}</span>
       <span class="small muted">판정 ${v.t_verdict_count ?? 0}건 · 로그 #${v.log_index ?? '—'} · 완전성 ${esc(r.completeness || '—')}${v.evidence_after_verdict ? ` · 판정 뒤 증거 ${v.evidence_after_verdict}건 추가` : ''}${(v.compared_without || []).length ? ` · 비교 제외 ${v.compared_without.map(esc).join(',')}` : ''}</span>`,
      v.match ? '일치 — 눌러서 JSON 근거 보기' : '불일치 — 눌러서 JSON 근거 보기');
    return `<div class="vrow ${v.match ? 'ok' : 'bad'}">${head}${v.match ? '' : diffHtml(v, j)}</div>`;
  }).join('');
  return `<div class="verdicts">${rows}</div>`;
}
function diffHtml(v: Data, j: number): string {
  const r: Data = v.recomputed || {}, t: Data | null = v.t_verdict;
  const lines: string[] = [];
  if (!t) lines.push(`<div class="drow"><span class="dk">T 판정</span><span class="fail">${esc(v.note || 'T 가 이 요청에 대한 인증되는 판정을 등록하지 않음')}</span></div>`);
  else {
    const field = (k: string, name: string, f: (x: any) => string) => { if (JSON.stringify(t[k]) !== JSON.stringify(r[k])) lines.push(`<div class="drow"><span class="dk">${name}</span><span>T <b>${f(t[k])}</b> → 감사자 <b class="fail">${f(r[k])}</b></span></div>`); };
    field('verification_status', '판정', x => esc(STATUS_KO[x] || x));
    field('completeness', '완전성', x => esc(x));
    field('codes', '불일치 코드', x => (x || []).length ? (x as string[]).map(esc).join(', ') : '없음');
    const eqs = Object.keys({...(t.equations || {}), ...(r.equations || {})}).filter(k => (t.equations || {})[k] !== (r.equations || {})[k]);
    if (eqs.length) lines.push(`<div class="drow"><span class="dk">등식</span><span>${eqs.map(k => `${esc(k)}: T <b>${esc((t.equations || {})[k] ?? '—')}</b> → 감사자 <b class="fail">${esc((r.equations || {})[k] ?? '—')}</b>`).join(' · ')}</span></div>`);
    for (const k of ['policy_hash', 'checker_version', 'trust_keys_version']) if (t[k] !== r[k]) lines.push(`<div class="drow"><span class="dk">${esc(k)}</span><span>T ${short(t[k])} → 감사자 ${short(r[k])}</span></div>`);
  }
  const hist = (v.historical_verdicts || []).length > 1 ? `<div class="small muted">과거 판정 ${v.historical_verdicts.length}건 중 불일치 ${v.historical_verdicts.filter((h: Data) => !h.match).length}건 — 나중 판정이 맞아도 과거 오판은 그대로 남는다.</div>` : '';
  return `<div class="vdiff">${lines.join('') || '<div class="drow"><span class="dk">차이</span><span class="muted">서명 있는 필드 밖의 차이 — JSON 을 확인</span></div>'}${hist}
    ${j >= 0 ? ref(`verdict_mismatches.${j}`, 'link', '↳ verdict_mismatches[' + j + '] 근거로 이동') : ''}</div>`;
}

// ---------- 정책·서명 문제 ----------
function problemsHtml(a: Data): string {
  const out: string[] = [];
  if ((a.policy_problems || []).length) out.push(`<h3>정책 진술 문제</h3><ul class="tight small">${a.policy_problems.map((p: string, i: number) => `<li>${ref(`policy_problems.${i}`, 'link fail', esc(p))}</li>`).join('')}</ul>`);
  if ((a.unauthenticated_verdicts || []).length) out.push(`<h3>인증되지 않는 판정 진술</h3><div class="verdicts">${a.unauthenticated_verdicts.map((u: Data, i: number) => ref(`unauthenticated_verdicts.${i}`, 'vhead bad', `<span class="mono">${short(u.sub)}</span> #${u.log_index} <b>${esc(u.iss)}</b> <span class="fail">${esc(u.problem)}</span>`)).join('')}</div>`);
  if ((a.receipt_errors || []).length) out.push(`<h3>등록 영수증 문제</h3><ul class="tight small">${a.receipt_errors.map((p: unknown, i: number) => `<li>${ref(`receipt_errors.${i}`, 'link fail', esc(typeof p === 'string' ? p : JSON.stringify(p)))}</li>`).join('')}</ul>`);
  if (a.note) out.push(`<p class="small muted" style="margin-top:12px">${esc(a.note)}</p>`);
  return out.join('');
}

// ---------- 매핑된 JSON ----------
const COLLAPSED = /(^|\.)(historical_verdicts|equations|evidence|signature)$/;
function jsonNode(v: unknown, path: string, key: string | null, last: boolean): string {
  const comma = last ? '' : ',';
  const k = key === null ? '' : `<span class="jk">"${esc(key)}"</span>: `;
  if (v === null || typeof v !== 'object') {
    let val: string;
    if (typeof v === 'string') val = HEX64.test(v) ? `"${short(v)}"` : `"${esc(v)}"`;
    else val = esc(String(v));
    const type = v === null ? 'null' : typeof v;
    return `<div class="jl" data-path="${esc(path)}">${k}<span class="jv ${type}">${val}</span>${comma}</div>`;
  }
  const isArr = Array.isArray(v);
  const entries = isArr ? (v as unknown[]).map((x, i) => [String(i), x] as [string, unknown]) : Object.entries(v as Data);
  const open = isArr ? '[' : '{', close = isArr ? ']' : '}';
  if (!entries.length) return `<div class="jl" data-path="${esc(path)}">${k}<span class="jb">${open}${close}</span>${comma}</div>`;
  const collapsed = COLLAPSED.test(path) ? ' collapsed' : '';
  const children = entries.map(([ck, cv], i) => jsonNode(cv, path ? `${path}.${ck}` : ck, isArr ? null : ck, i === entries.length - 1)).join('');
  return `<div class="jn${collapsed}" data-path="${esc(path)}">
    <div class="jl jh" data-path="${esc(path)}"><span class="jt" aria-hidden="true"></span>${k}<span class="jb">${open}</span><span class="jsum">${entries.length}개 ${isArr ? '항목' : '키'}</span></div>
    <div class="jc">${children}</div>
    <div class="jl je"><span class="jb">${close}</span>${comma}</div>
  </div>`;
}

// ---------- 연동 ----------
function wire(root: HTMLElement, a: Data) {
  const canvas = root.querySelector<HTMLElement>('.audit-canvas')!, pane = root.querySelector<HTMLElement>('.audit-json')!, tree = root.querySelector<HTMLElement>('.json-tree')!;
  let glowTimer = 0;

  // 그래프 → JSON: 근거 위치로 스크롤하고 2초간 강조한다. 접힌 조상은 편다.
  const focusJson = (path: string) => {
    const line = tree.querySelector<HTMLElement>(`.jl[data-path="${CSS.escape(path)}"]`);
    if (!line) return;
    for (let p = line.parentElement; p && p !== tree; p = p.parentElement) if (p.classList.contains('jn')) p.classList.remove('collapsed');
    tree.querySelectorAll('.glow,.sel').forEach(n => n.classList.remove('glow', 'sel'));
    const block = line.classList.contains('jh') ? line.parentElement! : line;
    block.classList.add('sel', 'glow'); void block.offsetWidth;
    window.clearTimeout(glowTimer); glowTimer = window.setTimeout(() => block.classList.remove('glow'), 2000);
    pane.scrollTo({top: Math.max(0, line.offsetTop - pane.clientHeight / 2 + 40), behavior: reducedMotion ? 'auto' : 'smooth'});
    canvas.querySelectorAll('.ref.sel').forEach(n => n.classList.remove('sel'));
    canvas.querySelectorAll<HTMLElement>(`[data-ref="${CSS.escape(path)}"]`).forEach(n => n.classList.add('sel'));
  };
  canvas.addEventListener('click', e => {
    const target = e.target as HTMLElement;
    if (target.closest('[data-copy]')) return; // 해시 칩은 복사가 우선
    const r = target.closest<HTMLElement>('[data-ref]');
    if (r) focusJson(r.dataset.ref!);
  });
  canvas.addEventListener('keydown', e => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const r = (e.target as HTMLElement).closest<HTMLElement>('[data-ref]');
    if (!r || (e.target as HTMLElement).closest('[data-copy]')) return;
    e.preventDefault(); focusJson(r.dataset.ref!);
  });

  // JSON → 그래프: 커서 아래 줄의 경로를 가장 가까운 상위 요소까지 거슬러 찾아 펄스한다.
  let linked: HTMLElement[] = [];
  const unlink = () => { linked.forEach(n => n.classList.remove('linked')); linked = []; };
  tree.addEventListener('mouseover', e => {
    const line = (e.target as HTMLElement).closest<HTMLElement>('.jl[data-path]');
    if (!line) return;
    const parts = (line.dataset.path || '').split('.');
    let hits: HTMLElement[] = [];
    for (let i = parts.length; i > 0 && !hits.length; i--) hits = [...canvas.querySelectorAll<HTMLElement>(`[data-ref="${CSS.escape(parts.slice(0, i).join('.'))}"]`)];
    if (hits.length === 1 && hits[0] === linked[0]) return;
    unlink(); linked = hits;
    hits.forEach(n => { n.classList.remove('pulse'); void n.offsetWidth; n.classList.add('linked', 'pulse'); });
  });
  tree.addEventListener('mouseleave', unlink);
  tree.addEventListener('click', e => {
    const target = e.target as HTMLElement;
    if (target.closest('[data-copy]')) return;
    const head = target.closest<HTMLElement>('.jh');
    if (head) head.parentElement!.classList.toggle('collapsed');
  });

  // 검색: 경로·키·값에 포함되면 줄을 표시하고 조상을 편다.
  const search = root.querySelector<HTMLInputElement>('.json-search')!;
  search.addEventListener('input', () => {
    const q = search.value.trim().toLowerCase();
    tree.querySelectorAll('.hit').forEach(n => n.classList.remove('hit'));
    if (!q) return;
    let first: HTMLElement | null = null;
    tree.querySelectorAll<HTMLElement>('.jl[data-path]').forEach(line => {
      if (!(line.dataset.path || '').toLowerCase().includes(q) && !(line.textContent || '').toLowerCase().includes(q)) return;
      line.classList.add('hit'); first ??= line;
      for (let p = line.parentElement; p && p !== tree; p = p.parentElement) if (p.classList.contains('jn')) p.classList.remove('collapsed');
    });
    if (first) pane.scrollTo({top: Math.max(0, (first as HTMLElement).offsetTop - 40), behavior: reducedMotion ? 'auto' : 'smooth'});
  });
  // 불일치만 보기: 결과에서 「나쁜」 경로(불일치·무효·문제)를 모으고, 그 경로의 조상과 자손만 남긴다.
  // 불일치가 없는 감사에서는 빈 화면 대신 안내를 낸다 — 비어 있음이 곧 결론이다.
  const badPrefixes = (): string[] => {
    const out: string[] = [];
    (a.verdicts_checked || []).forEach((v: Data, i: number) => { if (!v.match) out.push(`verdicts_checked.${i}`); });
    (a.anchors || []).forEach((x: Data, i: number) => { if (!x.ok) out.push(`anchors.${i}`); });
    (a.verdict_mismatches || []).forEach((_: Data, i: number) => out.push(`verdict_mismatches.${i}`));
    (a.policy_problems || []).forEach((_: unknown, i: number) => out.push(`policy_problems.${i}`));
    (a.unauthenticated_verdicts || []).forEach((_: unknown, i: number) => out.push(`unauthenticated_verdicts.${i}`));
    (a.receipt_errors || []).forEach((_: unknown, i: number) => out.push(`receipt_errors.${i}`));
    if (!a.tree_recomputed_matches_head) out.push('tree_recomputed_matches_head');
    if (!a.head_signature_valid) out.push('head_signature_valid');
    if (a.ok === false) out.push('ok');
    return out;
  };
  const onlyBad = root.querySelector<HTMLButtonElement>('[data-json-only-bad]')!;
  let onlyBadOn = false, emptyNote: HTMLElement | null = null;
  onlyBad.addEventListener('click', () => {
    onlyBadOn = !onlyBadOn;
    onlyBad.classList.toggle('on', onlyBadOn);
    onlyBad.textContent = onlyBadOn ? '전체 보기' : '불일치 항목만 보기';
    tree.classList.toggle('only-bad', onlyBadOn);
    tree.querySelectorAll('.bad').forEach(n => n.classList.remove('bad'));
    emptyNote?.remove(); emptyNote = null;
    if (!onlyBadOn) return;
    const bad = badPrefixes();
    const keep = (path: string) => bad.some(b => b === path || b.startsWith(path + '.') || path.startsWith(b + '.'));
    let shown = 0;
    tree.querySelectorAll<HTMLElement>('[data-path]').forEach(n => { const p = n.dataset.path || ''; if (p && keep(p)) { n.classList.add('bad'); if (n.classList.contains('jl')) shown++; } });
    tree.querySelectorAll('.jn.bad.collapsed').forEach(n => n.classList.remove('collapsed'));
    if (!shown) { emptyNote = document.createElement('div'); emptyNote.className = 'empty'; emptyNote.textContent = '불일치 항목이 없습니다. 「전체 보기」로 문서 전체를 볼 수 있습니다.'; tree.prepend(emptyNote); }
  });
  root.querySelector('[data-json-expand]')!.addEventListener('click', () => tree.querySelectorAll('.jn.collapsed').forEach(n => n.classList.remove('collapsed')));
  root.querySelector('[data-json-collapse]')!.addEventListener('click', () => tree.querySelectorAll<HTMLElement>('.jn').forEach(n => { if (n.dataset.path) n.classList.add('collapsed'); }));
  const copy = root.querySelector<HTMLButtonElement>('[data-json-copy]')!;
  copy.addEventListener('click', async () => {
    const ok = await copyText(JSON.stringify(a, null, 2));
    copy.textContent = ok ? '복사됨' : '복사 실패';
    window.setTimeout(() => { copy.textContent = '전체 복사'; }, 1500);
  });
}
