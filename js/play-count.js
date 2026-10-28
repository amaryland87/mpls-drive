// [Mpls] How many people have played, in the top left. The site is static, so the count is kept by Abacus
// (abacus.jasoncameron.dev, a free hit counter). Each browser counts once: its first visit adds one (/hit), later ones
// only read the count (/get). If the counter can't be reached, the pill stays hidden.
const COUNTER = 'https://abacus.jasoncameron.dev';
const KEY = 'sometimesfunctional-mpls-drive/plays';
const COUNTED = 'mpls-drive-counted';

export async function showPlayCount(el) {
  if (!el) return;
  let counted = false;
  try { counted = localStorage.getItem(COUNTED) === '1'; } catch { /* storage blocked: count this visit */ }
  try {
    const r = await fetch(`${COUNTER}/${counted ? 'get' : 'hit'}/${KEY}`, { cache: 'no-store' });
    if (!r.ok) return;
    const { value } = await r.json();
    if (!Number.isFinite(value)) return;
    if (!counted) try { localStorage.setItem(COUNTED, '1'); } catch { /* ignore */ }
    el.querySelector('.play-count-n').textContent = value.toLocaleString();
    el.title = `${value.toLocaleString()} ${value === 1 ? 'person has' : 'people have'} played Mpls Drive`;
    el.hidden = false;
  } catch { /* offline or blocked: leave it hidden */ }
}
