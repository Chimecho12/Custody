const motionPreference = typeof window === 'undefined' ? null : window.matchMedia('(prefers-reduced-motion: reduce)');
export let reducedMotion = motionPreference?.matches ?? false;
motionPreference?.addEventListener('change', e => { reducedMotion = e.matches; });
