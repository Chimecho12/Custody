export const esc = (s: unknown): string =>
  String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c] as string));
export const cls = (r: string | undefined | null) => r === 'pass' ? 'pass' : r === 'fail' ? 'fail' : 'na';
export const st = (s: string | undefined | null) => s === 'passed' ? 'pass' : s === 'failed' ? 'fail' : 'warn';
// 해시·커밋은 앞 12자만 보이고, 누르면 전체 값을 클립보드로 복사한다 (Rekor 의 항목 해시 취급과 같은 방식).
export const short = (h: unknown) => h
  ? `<span class="hashchip" data-copy="${esc(h)}" role="button" tabindex="0" title="클릭하면 전체 값을 복사합니다">${esc(String(h).slice(0, 12))}…</span>`
  : '<span class="absent">없음</span>';
export const absent = (v: unknown) => (v === null || v === undefined) ? '<span class="absent">null</span>' : esc(v);
export const CV = (name: string) => `var(--${name})`;
