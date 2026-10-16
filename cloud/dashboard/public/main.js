// App shell: sign-in, routing, polling and the two-pane layout on wide screens.
import {h} from './dom.js';
import {api, passkey, setCsrf} from './api.js';
import {groups} from './model.js';
import {onRefresh, toast} from './ui.js';
import {renderList} from './view-list.js';
import {renderCase} from './view-case.js';
import {enterSettings, renderSettings} from './view-settings.js';
import * as push from './push.js';

const $ = id => document.getElementById(id);
let session = null, state = null, stale = false, lastRoute = '';
const scrollPositions = new Map();
const wide = matchMedia('(min-width: 900px)');

// ---------------------------------------------------------------- routing

/** '#/', '#/case/<id>', '#/settings'; older notification links use #review= and #recovery=. */
function route() {
  const hash = location.hash;
  if (hash.startsWith('#/case/')) return {name: 'case', id: decodeURIComponent(hash.slice(7))};
  if (hash === '#/settings') return {name: 'settings'};
  return {name: 'list'};
}

function translateLegacyHash() {
  const params = new URLSearchParams(location.hash.slice(1));
  let target = null;
  if (params.has('review')) target = Object.values(state.jobs || {}).find(j => j.review?.id === params.get('review'))?.id;
  if (params.has('recovery')) target = state.recoveries?.[params.get('recovery')]?.job;
  if (target) return history.replaceState(null, '', '#/case/' + encodeURIComponent(target));
  if (params.has('connected')) {
    toast(`${({youtube: 'YouTube', github: 'GitHub'})[params.get('connected')] || 'Account'} connected.`);
    return history.replaceState(null, '', '#/settings');
  }
  if (params.get('connection') === 'failed') {
    toast('The connection was not completed. Try again from Settings.', 'error');
    return history.replaceState(null, '', '#/settings');
  }
  if (params.has('review') || params.has('recovery')) history.replaceState(null, '', '#/');
}

// ---------------------------------------------------------------- rendering

function topBar(r) {
  const back = h('a.back', {href: '#/'}, h('span', {'aria-hidden': 'true'}, '‹ '), 'Recordings');
  return [
    h('div.bar-start', r.name === 'list' || wide.matches ? h('a.app-name', {href: '#/'}, 'Scotus videos') : back),
    h('div.bar-end', r.name !== 'settings' ? h('a', {href: '#/settings'}, 'Settings') : wide.matches && h('a', {href: '#/'}, 'Done')),
  ];
}

function render(force = false) {
  if (!state) return;
  const r = route(), key = r.name + ':' + (r.id || '');
  const focused = document.activeElement;
  // Do not rebuild a form under the cursor; finish when the field loses focus.
  if (!force && key === lastRoute && focused?.matches?.('input, textarea, select') && $('app').contains(focused)) { stale = true; return; }
  stale = false;
  document.body.dataset.route = r.name;
  $('topbar').replaceChildren(...topBar(r));
  if (wide.matches || r.name === 'list') $('list').replaceChildren(...renderList(state, r.id).filter(Boolean));
  if (r.name === 'case') $('detail').replaceChildren(...renderCase(state, r.id).filter(Boolean));
  else if (r.name === 'settings') $('detail').replaceChildren(...renderSettings(state).filter(Boolean));
  else $('detail').replaceChildren(h('p.calm.placeholder', 'Choose a recording.'));
  if (key !== lastRoute) {
    if (!wide.matches) window.scrollTo(0, r.name === 'list' ? scrollPositions.get('list') || 0 : 0);
    else $('detail').scrollTop = 0;
    if (r.name === 'case') clearNotifications(r.id);
    lastRoute = key;
  }
  const count = state.push?.badge ?? groups(state).action.length;
  document.title = count ? `(${count}) Scotus videos` : 'Scotus videos';
  if ('setAppBadge' in navigator) (count ? navigator.setAppBadge(count) : navigator.clearAppBadge()).catch(() => {});
}

async function clearNotifications(job) {
  if (!('serviceWorker' in navigator)) return;
  const registration = await navigator.serviceWorker.getRegistration();
  for (const n of await registration?.getNotifications() || []) if (n.data?.job === job) n.close();
}

function showSignIn() {
  document.body.dataset.route = 'signin';
  $('topbar').replaceChildren(h('div.bar-start', h('span.app-name', 'Scotus videos')));
  const enrolling = session?.enrollment_allowed, initialized = session?.initialized;
  const buttonEl = h('button.primary', {type: 'button'}, enrolling ? 'Create a passkey' : 'Sign in with passkey');
  buttonEl.addEventListener('click', async () => {
    buttonEl.disabled = true; buttonEl.setAttribute('aria-busy', 'true');
    try { await passkey(enrolling); await start(); } catch (error) {
      toast(error.name === 'NotAllowedError' ? 'Passkey request cancelled or timed out.' : error.message, 'error');
    } finally { buttonEl.disabled = false; buttonEl.removeAttribute('aria-busy'); }
  });
  $('signin').replaceChildren(
    h('h1', enrolling ? 'Create a passkey' : 'Sign in'),
    h('p', enrolling ? 'Register a passkey to access this dashboard.' : initialized ? 'Use your passkey to open the dashboard.' : 'Open your one-time setup link to register the first passkey.'),
    (enrolling || initialized) && buttonEl);
}

// ---------------------------------------------------------------- state

/** force: re-render even under the cursor (after the owner's own action). */
let requested = 0, applied = 0;
async function refresh(force = false) {
  const mine = ++requested;
  try {
    const value = await api('state', {revision: state?._revision});
    if (mine < applied) return;  // A newer response already arrived; never step back.
    applied = mine;
    if (!value._unchanged) { state = value; render(force); } else if (force) render(true);
  } catch (error) {
    if (error.status === 401) { session = await api('session', {}, true); setCsrf(session.csrf); state = null; showSignIn(); return; }
    throw error;
  }
}
onRefresh(() => refresh(true));

async function start() {
  session = await api('session', {}, true);
  setCsrf(session.csrf);
  const token = new URLSearchParams(location.hash.slice(1)).get('setup');
  if (token) {
    history.replaceState(null, '', location.pathname);
    await api('bootstrap', {token});
    session.enrollment_allowed = true;
  }
  if (!session.signed_in) { showSignIn(); return; }
  await refresh();
  translateLegacyHash();
  if (route().name === 'settings') enterSettings(state);
  render();
  push.sync(state);
}

window.addEventListener('hashchange', async () => {
  if (lastRoute.startsWith('list:') && !wide.matches) scrollPositions.set('list', window.scrollY);
  if (!state) return;
  // Links from older notifications name a review or repair the loaded state may not have yet.
  if (!location.hash.startsWith('#/') && location.hash.length > 1) await refresh().catch(() => {});
  translateLegacyHash();
  if (route().name === 'settings') enterSettings(state);
  render();
  refresh().catch(() => {});
});
document.addEventListener('rerender', () => render());
document.addEventListener('focusout', () => setTimeout(() => { if (stale) render(); }, 0));
wide.addEventListener('change', () => { lastRoute = ''; render(); });
document.addEventListener('visibilitychange', () => { if (!document.hidden && state) refresh().catch(() => {}); });
setInterval(() => { if (!document.hidden && state) refresh().catch(() => {}); }, 15000);

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js').catch(() => {});
  // A tapped notification for an open app arrives as a message instead of a new window.
  navigator.serviceWorker.addEventListener('message', event => {
    if (event.data?.type !== 'open' || typeof event.data.hash !== 'string') return;
    location.hash = event.data.hash;
    if (state) refresh().catch(() => {});
  });
}

start().catch(error => { $('signin').replaceChildren(h('p.problem', error.message)); document.body.dataset.route = 'signin'; });
