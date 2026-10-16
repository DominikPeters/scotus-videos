// DOM construction and formatting helpers shared by all views.

/** h('p.note', {onclick}, 'text', child) — tag with optional .class suffixes. */
export function h(spec, props, ...children) {
  if (props === null || typeof props !== 'object' || props instanceof Node || Array.isArray(props)) {
    children.unshift(props);
    props = {};
  }
  const [tag, ...classes] = spec.split('.');
  const el = document.createElement(tag || 'div');
  if (classes.length) el.className = classes.join(' ');
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else if (key === 'class') el.className += (el.className ? ' ' : '') + value;
    else if (key === 'dataset') Object.assign(el.dataset, value);
    else if (key in el && !['list', 'form', 'type'].includes(key)) el[key] = value;
    else el.setAttribute(key, value === true ? '' : value);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const child of children) {
    // 0 is skipped too, so `list.length && h(...)` renders nothing for an empty list.
    if (child === null || child === undefined || child === false || child === '' || child === 0) continue;
    if (Array.isArray(child)) append(el, child);
    else el.append(child instanceof Node ? child : String(child));
  }
}

export function link(label, url, className = '') {
  let brand = '';
  try {
    const host = new URL(url).hostname;
    brand = Object.entries({youtube:'youtube.com',github:'github.com',spotify:'spotify.com',tiktok:'tiktok.com',instagram:'instagram.com',openai:'openai.com'})
      .find(([, domain]) => host === domain || host.endsWith('.' + domain))?.[0] || (host === 'youtu.be' ? 'youtube' : '');
  } catch { /* Relative links have no platform mark. */ }
  return h('a', {href: url, target: '_blank', rel: 'noopener', class: className || undefined}, brandIcon(brand), label);
}

export const safeUrl = url => /^https:\/\//.test(url || '') ? url : null;

export function plural(count, one, many = one + 's') {
  return `${count} ${count === 1 ? one : many}`;
}

export function textFromHtml(html) {
  return new DOMParser().parseFromString(html || '', 'text/html').body.textContent.trim();
}

const thisYear = new Date().getFullYear();

/** '2026-10-14' → 'Oct 14' (or 'Oct 14, 2025' for other years). */
export function shortDate(day) {
  if (!day) return '';
  const date = new Date(day + 'T12:00:00');
  return date.toLocaleDateString(undefined, {month: 'short', day: 'numeric', ...(date.getFullYear() !== thisYear && {year: 'numeric'})});
}

export function longDate(day) {
  if (!day) return '';
  return new Date(day + 'T12:00:00').toLocaleDateString(undefined, {month: 'long', day: 'numeric', year: 'numeric'});
}

export function dateTime(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  return date.toLocaleString(undefined, {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', ...(date.getFullYear() !== thisYear && {year: 'numeric'})});
}

export function ago(iso) {
  const seconds = (Date.now() - Date.parse(iso)) / 1000;
  if (!Number.isFinite(seconds)) return '';
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return dateTime(iso);
}

export function duration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '';
  seconds = Math.round(seconds);
  if (seconds < 60) return `${seconds} s`;
  const hours = Math.floor(seconds / 3600), minutes = Math.round(seconds % 3600 / 60);
  return hours ? `${hours} h ${minutes} min` : `${minutes} min`;
}

export function clock(seconds) {
  const s = Math.floor(seconds), hours = Math.floor(s / 3600), minutes = Math.floor(s % 3600 / 60), rest = String(s % 60).padStart(2, '0');
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`;
}

export function brandIcon(name) {
  if (name === 'codex') name = 'openai';
  if (!['youtube','spotify','github','tiktok','instagram','openai'].includes(name)) return null;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 16 16');svg.setAttribute('class', 'brand-icon');svg.setAttribute('aria-hidden', 'true');svg.setAttribute('focusable', 'false');
  const use = document.createElementNS(svg.namespaceURI, 'use');use.setAttribute('href', 'brand-icons.svg#'+name);svg.append(use);return svg;
}

export function brandLabel(label) {
  if (typeof label !== 'string') return label;
  const name = label.match(/\b(YouTube|Spotify|GitHub|TikTok|Instagram|Codex|OpenAI)\b/i)?.[1].toLowerCase();
  return name ? [brandIcon(name), label] : label;
}
