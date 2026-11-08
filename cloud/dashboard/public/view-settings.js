// Settings: automatic work, notifications, connected accounts, passkeys and manual queueing.
import {h, link, dateTime, brandIcon} from './dom.js';
import {api, passkey} from './api.js';
import {block, button, disclosure, draft, drafts, setOpen, submitForm, toast} from './ui.js';
import * as push from './push.js';

const rerender = () => document.dispatchEvent(new CustomEvent('rerender'));
const conn = {data: null, error: '', loading: false, guide: null, loginId: '', poll: null};
let pushState = null, pushChecking = false;

export function enterSettings(state) {
  loadConnections();
  pushState = null;
}

async function loadConnections() {
  if (conn.loading) return;
  conn.loading = true;
  try { conn.data = await api('secret_status'); conn.error = ''; } catch (error) { conn.error = error.message; }
  conn.loading = false;
  rerender();
  connectionStatus().catch(() => {});
}

export function renderSettings(state) {
  return [
    h('header.case-head', h('h1', 'Settings')),
    workBlock(state),
    statisticsBlock(state),
    notificationsBlock(state),
    connectionsBlock(),
    budgetBlock(state),
    queueBlock(),
    accessBlock(),
    activityBlock(state),
  ];
}

function workBlock(state) {
  return block('Automatic work',
    h('p', state.paused
      ? 'Paused. New and queued recordings wait until you start them individually or resume.'
      : 'On. New arguments are discovered and processed automatically; you are notified when something needs you.'),
    h('div.actions',
      button(state.paused ? 'Resume automatic work' : 'Pause automatic work',
        () => api('command', {command: state.paused ? 'resume' : 'pause'})),
      button('Check for work now', async () => (await api('dispatch')).message || 'Work checked.')));
}

function notificationsBlock(state) {
  const devices = state.push?.devices || [];
  if (!pushState && !pushChecking) {
    pushChecking = true;
    push.status(state).then(value => { pushState = value; }).catch(() => { pushState = {available: false, reason: 'check_failed'}; }).finally(() => { pushChecking = false; rerender(); });
  }
  const s = pushState;
  let body;
  if (!s) body = h('p.note', 'Checking this device…');
  else if (!s.available && s.reason === 'not_configured') body = h('p', 'Web Push is not configured on the server yet.');
  else if (!s.available && s.reason === 'install') body = [
    h('p', 'On iPhone, notifications work only from the Home Screen app.'),
    h('ol.steps', h('li', 'Tap the Share button in Safari.'), h('li', 'Choose Add to Home Screen.'), h('li', 'Open Scotus videos from the Home Screen and return here.'))];
  else if (!s.available) body = h('p', 'This browser does not support Web Push.');
  else if (s.permission === 'denied') body = h('p', 'Notifications are blocked for this app. Allow them in the system settings, then return here.');
  else body = [
    h('p', s.enabled ? 'On for this device.' : 'Off for this device.'),
    h('div.actions',
      s.enabled
        ? button('Turn off on this device', async () => { await push.disable(); pushState = null; }, {done: 'Notifications turned off.'})
        : button('Turn on notifications', async () => { await push.enable(state); pushState = null; }, {primary: true, done: 'Notifications are on.'}),
      s.enabled && button('Send a test', async () => { const result = await api('notification_test'); if (!result.delivered) throw Error('Push delivery failed. Try again.'); return 'Test delivered to the push service.'; }))];
  return block('Notifications',
    body,
    devices.length && disclosure('push-devices', `Devices (${devices.length})`,
      h('ul.plain', devices.map(d => h('li.device',
        h('div.device-info', h('strong', d.label || 'Device', d.id === s?.id ? ' (this device)' : ''),
          h('span.note', `Added ${dateTime(d.created_at)}`),
          d.last_sent_at && h('span.note', `Last notification ${dateTime(d.last_sent_at)}`)),
        d.id !== s?.id && button('Remove', () => api('push_unsubscribe', {id: d.id}), {small: true}))))));
}

// ---------------------------------------------------------------- connections

const NAMES = {youtube: 'YouTube', codex: 'Codex', github: 'GitHub', spotify: 'Spotify', instagram: 'Instagram'};

function connectionsBlock() {
  const data = conn.data;
  const rows = data ? Object.entries(data.credentials).map(([name, s]) => h('li.connection',
    h('span', h('strong', brandIcon(name), NAMES[name] || name), h('span.note', s.configured ? `Saved ${dateTime(s.updated_at)}` : s.app_created ? 'App created; installation needed' : 'Not connected')),
    button(name === 'github' && s.configured ? 'Check' : s.configured ? 'Reconnect' : 'Connect', () => connect(name), {small: true}))) : [];
  return block('Connections',
    conn.error ? h('p.problem', conn.error) : !data ? h('p.note', 'Checking connections…')
      : h('p', data.workers_enabled ? 'Cloud workers are enabled.' : 'Cloud connected. Video workers are not enabled.'),
    rows.length && h('ul.plain', rows),
    conn.guide && h('div.guide', {'aria-live': 'polite'}, h('h3', conn.guide.title), h('p', conn.guide.text), conn.guide.body?.()),
    importForm());
}

function guide(title, text, body = null, provider = '') {
  conn.guide = {title, text, body, provider};
  rerender();
}

async function connect(provider) {
  if (provider === 'instagram' && !conn.data?.instagram_client_configured) {
    guide('Connect Instagram', 'Enter the Instagram app ID and secret from Meta’s “API setup with Instagram login” page.', () => {
      const form = h('form',
        h('label', 'Instagram app ID', h('input', {name: 'client_id', required: true, inputmode: 'numeric', autocomplete: 'off'})),
        h('label', 'Instagram app secret', h('input', {name: 'client_secret', type: 'password', required: true, autocomplete: 'off'})),
        h('div.actions', h('button.primary', {type: 'submit'}, 'Save and connect')));
      submitForm(form, async () => {
        await api('instagram_client_replace', {value: {client_id: form.elements.client_id.value, client_secret: form.elements.client_secret.value}});
        form.reset();
        const result = await api('connect_start', {provider});
        location.assign(result.url);
      });
      return form;
    }, 'instagram');
    return;
  }
  if (provider === 'spotify') {
    guide('Reconnect Spotify', 'Paste the sp_dc and sp_key cookies from your signed-in Spotify session. The cloud exchanges them for a renewable token and discards the cookies.', () => {
      const form = h('form',
        h('label', 'sp_dc', draft('spotify:sp_dc', h('input', {name: 'sp_dc', type: 'password', autocomplete: 'off', required: true}))),
        h('label', 'sp_key', draft('spotify:sp_key', h('input', {name: 'sp_key', type: 'password', autocomplete: 'off', required: true}))),
        h('div.actions', h('button.primary', {type: 'submit'}, 'Save Spotify sign-in')));
      return submitForm(form, async () => {
        await api('secret_replace', {name: 'spotify', value: {sp_dc: form.elements.sp_dc.value, sp_key: form.elements.sp_key.value}});
        drafts.delete('spotify:sp_dc'); drafts.delete('spotify:sp_key');
        await api('spotify_probe');
        conn.guide = null; await loadConnections();
        return 'Spotify connected.';
      });
    }, 'spotify');
    return;
  }
  if (provider === 'youtube' && !conn.data?.youtube_client_configured) {
    drafts.set('import:name', 'youtube_client');
    setOpen('credential-import', true); rerender();
    toast('Import a Google Web application client with redirect URI ' + new URL('oauth-callback.php?provider=youtube', location.href).href);
    return;
  }
  if (provider === 'codex') {
    if (!conn.data?.codex_login_enabled) throw Error('The cloud sign-in helper is not deployed yet.');
    const result = await api('connect_start', {provider});
    conn.loginId = result.id;
    guide('Sign in to Codex', 'Waiting for Cloud Run to start the sign-in helper.', null, 'codex');
    startPoll(); await connectionStatus();
    return;
  }
  if (provider === 'github') {
    guide('Connect GitHub', 'Create a private GitHub app with access to DominikPeters/scotus-videos. It gets Contents read and write permission; the image publisher uses a token scoped to that repository.', () =>
      button('Continue on GitHub', async () => {
        const result = await api('connect_start', {provider});
        if (result.form_url) {
          const form = h('form', {method: 'POST', action: result.form_url}, h('input', {type: 'hidden', name: 'manifest', value: JSON.stringify(result.manifest)}));
          document.body.append(form); form.submit();
        } else if (result.install_url) {
          guide('Install the GitHub app', 'Select the repositories to connect, including DominikPeters/scotus-videos, then return here.', () => h('div.actions',
            link('Open GitHub installation', result.install_url, 'button-link'),
            button('Check installation', async () => {
              await api('github_install'); await loadConnections();
              guide('GitHub connected', 'The image publisher can now use short-lived tokens for this repository.');
            })));
        } else location.assign(result.url);
      }, {primary: true}), 'github');
    return;
  }
  const result = await api('connect_start', {provider});
  location.assign(result.url);
}

function startPoll() {
  if (!conn.poll) conn.poll = setInterval(() => connectionStatus().catch(() => {}), 3000);
}

function stopPoll() { clearInterval(conn.poll); conn.poll = null; }

async function connectionStatus() {
  const login = await api('connect_status');
  const cancel = () => button('Cancel sign-in', async () => { await api('connect_cancel'); await connectionStatus(); });
  if (!login) {
    if (conn.loginId) { stopPoll(); conn.loginId = ''; guide('Codex sign-in ended', 'There is no active sign-in request. Choose Connect to start again.'); }
    return;
  }
  const wasActive = conn.loginId === login.id;
  if (login.status === 'starting') {
    conn.loginId = login.id;
    const elapsed = Math.max(0, Math.floor((Date.now() - Date.parse(login.created_at)) / 1000));
    guide('Sign in to Codex', `Waiting for Cloud Run to start the sign-in helper; this can take a couple of minutes. Waiting ${Math.floor(elapsed / 60)}m ${elapsed % 60}s.`, () => h('div.actions', cancel()), 'codex');
    startPoll(); return;
  }
  if (login.status === 'pending') {
    conn.loginId = login.id;
    guide('Sign in to Codex', 'Open the OpenAI sign-in page and enter this one-time code. The login is saved for the cloud worker when you finish.', () => [
      h('code.device-code', login.user_code),
      h('div.actions', link('Open OpenAI sign-in', login.verification_url, 'button-link'), cancel()),
      h('p.note', 'If device login is unavailable, enable it in your ChatGPT security settings.')], 'codex');
    startPoll(); return;
  }
  stopPoll(); conn.loginId = '';
  if (login.status === 'complete') {
    if (conn.guide?.provider === 'codex') { conn.guide = null; rerender(); }
    if (wasActive) { toast('Codex connected.'); await loadConnections(); }
  } else if (['failed', 'expired'].includes(login.status) && wasActive) {
    guide('Codex sign-in ended', 'Sign in again to retry, or import a separate cloud auth.json file below.', null, 'codex');
  } else if (login.status === 'cancelled' && conn.guide?.provider === 'codex') { conn.guide = null; rerender(); }
}

function importForm() {
  const name = draft('import:name', h('select', {name: 'name'},
    h('option', {value: 'youtube'}, 'YouTube'), h('option', {value: 'codex'}, 'Codex'),
    h('option', {value: 'spotify'}, 'Spotify'), h('option', {value: 'youtube_client'}, 'YouTube browser client')), 'youtube');
  const form = h('form',
    h('label', 'Service', name),
    h('label', 'Credential file', h('input', {name: 'file', type: 'file', accept: '.json,application/json', required: true})),
    h('p.note', 'Choose a fresh credentials.json or auth.json. Saved credentials are never sent back to this page.'),
    h('div.actions', h('button', {type: 'submit'}, 'Replace credential')));
  submitForm(form, async () => {
    const file = form.elements.file.files[0], service = name.value;
    if (file.size > (service === 'youtube_client' ? 65536 : 131072)) throw Error('Credential file is too large.');
    const value = JSON.parse(await file.text());
    if (service === 'youtube_client') {
      const uri = new URL('oauth-callback.php?provider=youtube', location.href).href;
      if (!value.web?.redirect_uris?.includes(uri)) throw Error(`Use a Web application client with redirect URI ${uri}`);
      await api('youtube_client_replace', {value});
    } else await api('secret_replace', {name: service, value});
    form.reset(); await loadConnections();
    return 'Credential saved.';
  });
  return disclosure('credential-import', 'Import a credential file', form);
}

// ---------------------------------------------------------------- the rest

function budgetBlock(state) {
  const budget = state.repair_budget;
  const limit = Number(budget?.daily_limit_usd ?? 1);
  const days = Object.entries(budget?.days || {}).sort(([a], [b]) => b.localeCompare(a)).slice(0, 3);
  return block('Repair budget',
    h('p', `Codex repairs may reserve up to $${limit.toFixed(2)} per day, using conservative runtime estimates.`),
    days.length && h('dl.pairs', days.map(([day, usd]) => [h('dt', day), h('dd', `$${Number(usd).toFixed(2)} reserved`)])));
}

function queueBlock() {
  const field = (label, name, attrs = {}) => h('label', label, draft('queue:' + name, h('input', {name, ...attrs})));
  const form = h('form',
    h('div.fields',
      field('Docket', 'docket', {required: true, placeholder: '25-332', pattern: '[0-9]{2}(-[0-9]+|[A-Z][0-9]+)'}),
      field('Argument date', 'argument_date', {type: 'date', required: true})),
    field('Case name', 'case_name', {required: true, maxLength: 300}),
    field('Video title', 'title', {required: true, maxLength: 100, placeholder: 'Oral Argument on …: …'}),
    field('Official transcript link', 'pdf_url', {type: 'url', required: true}),
    field('Official audio link', 'audio_url', {type: 'url', required: true}),
    h('div.actions', h('button', {type: 'submit'}, 'Add recording')));
  submitForm(form, async () => {
    const job = await api('enqueue', Object.fromEntries(new FormData(form)));
    for (const key of [...drafts.keys()]) if (key.startsWith('queue:')) drafts.delete(key);
    location.hash = '#/case/' + encodeURIComponent(job.id);
    return 'Recording added.';
  });
  return block('Add a recording',
    h('p.note', 'Arguments on the Court’s calendar are found automatically. Use this for anything the discovery misses.'),
    disclosure('queue-form', 'Recording details', form));
}

function accessBlock() {
  return block('Sign-in',
    h('div.actions',
      button('Add another passkey', () => passkey(true), {done: 'Passkey added.'}),
      button('Sign out', async () => { await api('logout'); location.reload(); })));
}

function activityBlock(state) {
  const events = (state.events || []).slice().reverse().slice(0, 60);
  return disclosure('activity-all', `Recent activity (${events.length})`,
    h('ol.log', events.map(e => h('li',
      h('span.note', dateTime(e.at) + (e.job && state.jobs?.[e.job] ? ' · ' + state.jobs[e.job].case_name : '')),
      h('p', e.message)))));
}


function statisticsBlock(state) {
  const stats = state.statistics;
  if (!stats) return null;
  return block('Statistics',
    h('p', stats.message || stats.status || 'Waiting for first update'),
    h('p.note', `${stats.count || 0} cases · ${stats.pending || 0} updates pending` + (stats.published_at ? ` · published ${dateTime(stats.published_at)}` : '')),
    button('Check statistics now', () => api('command', {command: 'stats_check'}), {done: 'Statistics check queued.'}),
    Object.entries(stats.questions || {}).map(([key, question]) => {
      const answer = h('textarea', {rows: 3, placeholder: 'Answer or guidance for Codex'});
      return h('div', h('h3', key), h('p', question), answer,
        button('Send answer', () => api('command', {command: 'stats_answer', case: key, answer: answer.value}), {done: 'Answer queued for Codex.'}));
    }),
    Object.entries(stats.technical_errors || {}).map(([key, error]) =>
      h('div', h('h3', key),
        h('p', error.status === 'retry_pending' ? 'Automatic retry queued' : 'Statistics update needs repair'),
        h('p.note', error.notes))),
    disclosure('statistics-log', 'Update log', (stats.log || []).slice().reverse().map(item => h('p', h('span.note', dateTime(item.at) + ' · '), item.message))));
}
