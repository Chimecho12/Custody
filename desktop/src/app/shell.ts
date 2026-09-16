import { get } from '../shared/dom';
import { installConsoleInteractions } from '../shared/console';

export function initializeShell() {
  get('notice').title = '클릭하면 닫힙니다';
  get('notice').onclick = () => { get('notice').hidden = true; };
  // 등식 ↔ 표 연동 하이라이트와 해시 복사는 문서 전역에서 한 번만 건다.
  installConsoleInteractions();
  // ---------- 화면 설명(ⓘ): 모든 화면이 같은 방식으로 연다 ----------
  for (const b of document.querySelectorAll<HTMLButtonElement>('[data-guide]')) b.onclick = () => {
    const text = document.querySelector<HTMLElement>(`[data-guide-text="${b.dataset.guide}"]`);
    if (!text) return;
    text.hidden = !text.hidden;
    b.setAttribute('aria-expanded', String(!text.hidden));
    b.classList.toggle('on', !text.hidden);
  };

  // ---------- 테마: 시스템 → 밝게 → 어둡게 ----------
  const THEME_LABEL: Record<string, string> = {auto: '◐ 시스템', light: '○ 밝게', dark: '● 어둡게'};
  function applyTheme(theme: string) {
    if (theme === 'auto') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = theme;
    get('theme').textContent = THEME_LABEL[theme] || THEME_LABEL.auto;
    try { localStorage.setItem('itx-theme', theme); } catch { /* 저장 불가 환경에서는 세션 동안만 유지 */ }
  }
  get('theme').onclick = () => {
    const order = ['auto', 'light', 'dark'];
    const current = document.documentElement.dataset.theme || 'auto';
    applyTheme(order[(order.indexOf(current) + 1) % order.length]);
  };
  try { applyTheme(localStorage.getItem('itx-theme') || 'auto'); } catch { applyTheme('auto'); }

}
