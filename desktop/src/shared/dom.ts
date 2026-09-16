export const get = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
export function el(tag: string, className = '', text?: string): HTMLElement {
  const item = document.createElement(tag);
  item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}
export function notice(message: string, error = false) {
  const target = get('notice');
  target.hidden = false; target.classList.toggle('error', error);
  get('notice-text').textContent = message;
}
export function fail(error: unknown) { notice(String(error instanceof Error ? error.message : error), true); }
export function badge(text: string, tone = '') { return el('span', 'badge ' + tone, text); }
export function color(state: string) { return state === 'accept' ? 'green' : ['quarantine', 'reject', 'reject_timeout', 'error'].includes(state) ? 'red' : 'amber'; }
export function pretty(value: unknown) { const pre = el('pre'); pre.textContent = JSON.stringify(value, null, 2); return pre; }
export function details(label: string, value: unknown) { const item = el('details'); item.append(el('summary', '', label), pretty(value)); return item; }
export function button(text: string, action: () => void, className = 'v3-btn') {
  const b = el('button', className, text) as HTMLButtonElement; b.type = 'button'; b.onclick = action; return b;
}

export const setHint = (view: string, text: string) => { const h = document.querySelector<HTMLElement>(`[data-hint="${view}"]`); if (h) h.textContent = text; };

export const input = (id: string) => get<HTMLInputElement>(id).value.trim();
export const lines = (id: string) => input(id).split(/\r?\n/).map(s => s.trim()).filter(Boolean);
