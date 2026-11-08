// Home screen: every recording, grouped by what it needs.
import {h, dateTime, plural} from './dom.js';
import {groups, upcoming, caseMeta} from './model.js';
import {api} from './api.js';
import {button} from './ui.js';

function row(item, selected) {
  const {job, group, todo, line} = item;
  return h('a.row', {href: '#/case/' + encodeURIComponent(job.id), dataset: {status: job.status}, 'aria-current': selected ? 'page' : undefined},
    h('span.row-title', job.case_name),
    h('span.row-meta', caseMeta(job)),
    group === 'action'
      ? h('span.row-todo', todo.map(text => h('span', text)))
      : line && h('span.row-status', line),
    group === 'active' && h('span.bar', h('span', {style: `width:${Math.round(item.progress * 100)}%`})));
}

// How many rows each group shows; "Show more" raises it by the group's step.
const shownCounts = new Map();

function list(title, items, selected, limit = Infinity, step = Infinity) {
  if (!items.length) return null;
  const shown = items.slice(0, query ? Infinity : shownCounts.get(title) ?? limit);
  const more = items.length - shown.length;
  return h('section.group',
    h('h2', title, items.length > 3 && h('span.group-count', String(items.length))),
    h('div.rows', shown.map(item => row(item, item.job.id === selected))),
    more > 0 && h('button.link.more', {type: 'button', onclick: event => {
      shownCounts.set(title, shown.length + step);
      event.target.dispatchEvent(new CustomEvent('rerender', {bubbles: true}));
    }}, `Show ${plural(Math.min(more, step), 'more recording')}`));
}

// Search appears once the list is long; it filters every group by case name, docket or title.
let query = '';
const SEARCH_FROM = 12;
const matches = item => [item.job.case_name, item.job.docket, item.job.title].some(text => (text || '').toLowerCase().includes(query));

function groupsContent(state, selected) {
  const all = groups(state), g = Object.fromEntries(Object.entries(all).map(([key, items]) => [key, query ? items.filter(matches) : items]));
  const watches = query ? [] : upcoming(state);
  const out = [
    list('Needs you', g.action, selected),
    list('In progress', g.active, selected),
    list('Ready to publish', g.publish, selected, 3, Infinity),
    list('Waiting to start', g.waiting, selected),
  ];
  if (watches.length) {
    out.push(h('section.group', h('h2', 'Expected'),
      h('div.rows', watches.map(w => h('div.row.static',
        h('span.row-title', w.case_name),
        h('span.row-meta', `${w.docket} · watching for audio and transcript`),
        h('span.row-status', w.last_checked_at ? `Last checked ${dateTime(w.last_checked_at)}; checks until ${new Date(w.ends_at).toLocaleTimeString(undefined, {hour: 'numeric', minute: '2-digit'})}` : `Checks start ${dateTime(w.starts_at)}`))))));
  }
  if (!query && state.statistics && (state.statistics.status !== 'idle' || Object.keys(state.statistics.questions || {}).length || Object.keys(state.statistics.technical_errors || {}).length)) {
    const stats = state.statistics;
    out.push(h('section.group', h('h2', 'Statistics'), h('a.row', {href: '#/settings'},
      h('span.row-title', stats.message || 'Statistics update ' + stats.status),
      h('span.row-meta', `${stats.count || 0} cases · ${stats.pending || 0} updates pending`),
      Object.keys(stats.questions || {}).length ? h('span.row-todo', 'Codex needs your input') :
        Object.keys(stats.technical_errors || {}).length && h('span.row-todo', Object.values(stats.technical_errors).some(e => e.status === 'failed') ? 'Update needs repair' : 'Automatic retry queued'))));
  }
  out.push(list('Done', g.done, selected, 6, 20));
  if (query && !Object.values(g).some(items => items.length)) out.push(h('p.calm', 'No recordings match.'));
  return out.filter(Boolean);
}

export function renderList(state, selected) {
  const out = [];
  if (state.paused) {
    out.push(h('div.notice',
      h('p', 'Automatic work is paused. Queued recordings start only when you start them.'),
      button('Resume automatic work', () => api('command', {command: 'resume'}), {done: 'Automatic work resumed.'})));
  }
  const content = h('div', groupsContent(state, selected));
  if (Object.keys(state.jobs || {}).length >= SEARCH_FROM || query) {
    const search = h('input.search', {type: 'search', value: query, placeholder: 'Search recordings', 'aria-label': 'Search recordings', autocomplete: 'off', enterKeyHint: 'search'});
    // Only the results change while typing, so the field keeps focus.
    search.addEventListener('input', () => { query = search.value.trim().toLowerCase(); content.replaceChildren(...groupsContent(state, selected)); });
    out.push(search);
  }
  out.push(content);
  if (!Object.keys(state.jobs || {}).length) out.push(h('p.calm', 'No recordings yet. New arguments are discovered automatically, or add one in Settings.'));
  return out;
}
