// ---------- 문서 전역 상호작용: 등식 ↔ 표 연동 하이라이트, 해시 복사 ----------
let installed = false;
export function installConsoleInteractions() {
  if (installed) return; installed = true;
  let current: string | null = null;
  const mark = (id: string | null, on: boolean) => {
    if (!id) return;
    document.querySelectorAll(`[data-eq="${CSS.escape(id)}"]`).forEach(n => n.classList.toggle('eq-hi', on));
  };
  // 지도 라벨·등식 표·검사 표·집행 칩은 같은 등식 id 를 쓴다. 어느 쪽을 가리켜도 나머지가 같이 밝아진다.
  const point = (e: Event) => {
    const n = (e.target as HTMLElement | null)?.closest?.<HTMLElement>('[data-eq]') ?? null;
    const id = n ? n.dataset.eq! : null;
    if (id === current) return;
    mark(current, false); current = id; mark(current, true);
  };
  document.addEventListener('mouseover', point);
  document.addEventListener('focusin', point);

  const flash = (n: HTMLElement, message: string) => {
    n.dataset.flash = message; n.classList.add('copied');
    window.setTimeout(() => { n.classList.remove('copied'); delete n.dataset.flash; }, 1200);
  };
  document.addEventListener('click', e => {
    const n = (e.target as HTMLElement).closest<HTMLElement>('[data-copy]');
    if (!n) return;
    e.preventDefault();
    copyText(n.dataset.copy || '').then(ok => flash(n, ok ? '복사됨' : '복사 실패'));
  });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const n = (e.target as HTMLElement).closest<HTMLElement>('[data-copy][tabindex]');
    if (!n) return;
    e.preventDefault(); n.click();
  });
}
export async function copyText(text: string): Promise<boolean> {
  if (!text) return false;
  try { await navigator.clipboard.writeText(text); return true; } catch { /* 권한 없는 환경은 아래로 */ }
  try {
    const ta = document.createElement('textarea');
    ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.append(ta); ta.select();
    const ok = document.execCommand('copy'); ta.remove(); return ok;
  } catch { return false; }
}
