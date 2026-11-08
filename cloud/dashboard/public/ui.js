// Shared view pieces: actions with busy state, toasts, disclosures that survive re-rendering,
// lazily loaded private previews and form drafts.
import {h,brandLabel} from './dom.js';
import {cachedPreview, loadPreview, previewKey} from './api.js';

let refreshState = async () => {};
export const onRefresh = fn => { refreshState = fn; };

/** Unsaved input survives polling re-renders; keys include the revision they refer to. */
export const drafts = new Map();

const openDetails = new Map();
export const isOpen = (id, fallback = false) => openDetails.has(id) ? openDetails.get(id) : fallback;
export const setOpen = (id, open) => openDetails.set(id, open);

export function toast(text, kind = '') {
  const region = document.getElementById('toasts');
  const item = h('div.toast', {class: kind || undefined, role: kind === 'error' ? 'alert' : 'status'}, text);
  item.addEventListener('click', () => item.remove());
  region.append(item);
  setTimeout(() => item.remove(), kind === 'error' ? 9000 : 4000);
}

export async function act(control, task, done = '') {
  if (control?.getAttribute('aria-busy') === 'true') return;
  const wasDisabled = control?.disabled;
  if (control) { control.disabled = true; control.setAttribute('aria-busy', 'true'); }
  try {
    const message = await task();
    await refreshState();
    if (typeof message === 'string' || done) toast(typeof message === 'string' ? message : done);
  } catch (error) {
    toast(error.name === 'NotAllowedError' ? 'Passkey request cancelled or timed out.' : error.message, 'error');
  } finally {
    if (control?.isConnected) { control.disabled = wasDisabled; control.removeAttribute('aria-busy'); }
  }
}

/** options: primary, danger, confirm (question), done (toast), disabled, title */
export function button(label, task, options = {}) {
  const el = h('button', {
    type: 'button', disabled: options.disabled, title: options.title,
    class: [options.primary && 'primary', options.danger && 'danger', options.small && 'small'].filter(Boolean).join(' ') || undefined,
  }, brandLabel(label));
  el.addEventListener('click', () => {
    if (options.confirm && !window.confirm(options.confirm)) return;
    act(el, task, options.done);
  });
  return el;
}

export function submitForm(form, task, done = '') {
  form.addEventListener('submit', event => {
    event.preventDefault();
    act(event.submitter || form.querySelector('button[type=submit]'), () => task(form), done);
  });
  return form;
}

/** A <details> whose open state is remembered across re-renders. */
export function disclosure(id, summary, ...children) {
  let fallback = false;
  if (typeof children[0] === 'boolean') fallback = children.shift();
  const el = h('details', {id, open: isOpen(id, fallback)}, h('summary', brandLabel(summary)), h('div.disclosure-body', children));
  el.querySelector('summary').addEventListener('click', () => setOpen(id, !el.open));
  // Save explicit user intent; initial toggle events from replacement nodes must not overwrite it.
  return el;
}

/** Bind a field to drafts so polling re-renders keep what was typed. */
export function draft(key, field, initial = '') {
  const prop = field.type === 'checkbox' ? 'checked' : 'value';
  field[prop] = drafts.has(key) ? drafts.get(key) : initial;
  field.addEventListener(field.tagName === 'SELECT' || field.type === 'checkbox' ? 'change' : 'input', () => drafts.set(key, field[prop]));
  return field;
}

export const block = (title, ...children) => h('section.block', title && h('h2', brandLabel(title)), ...children);

const previewObservers = new Map();
function observePreview(img) {
  if (!img.isConnected) return;
  if (!('IntersectionObserver' in window)) { img.load(); return; }
  // Desktop uses a separately scrolling detail pane. A viewport root's margin
  // cannot see past that pane's clipping rectangle, so it starts cards too late.
  const pane = img.closest('#detail');
  const root = pane && ['auto', 'scroll'].includes(getComputedStyle(pane).overflowY) ? pane : null;
  if (!previewObservers.has(root)) {
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) { observer.unobserve(entry.target); entry.target.load(); }
    }, {root, rootMargin: '1600px'});
    previewObservers.set(root, observer);
  }
  previewObservers.get(root).observe(img);
}

/** A private preview image; loads when it scrolls near the viewport. */
export function preview(request, uri, alt, className = '') {
  const img = h('img', {alt, class: className || undefined, decoding: 'async'});
  if (!uri) { img.classList.add('missing'); return img; }
  const key = previewKey(request, uri);
  const cached = cachedPreview(key);
  if (cached) { img.src = cached; return img; }
  img.classList.add('loading');
  img.load = () => loadPreview(key, request)
    .then(url => { img.src = url; img.classList.remove('loading'); })
    .catch(() => { img.classList.remove('loading'); img.classList.add('missing'); img.alt = 'Preview unavailable'; });
  queueMicrotask(() => observePreview(img));
  return img;
}
