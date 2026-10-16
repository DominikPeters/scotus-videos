// Home screen: every recording, grouped by what it needs.
import {h, dateTime, plural} from './dom.js';
import {groups, upcoming, caseMeta} from './model.js';
import {api} from './api.js';
import {button, isOpen, setOpen} from './ui.js';

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

function list(title, items, selected, limit = Infinity) {
  if (!items.length) return null;
  const id = 'list-all-' + title;
  const shown = isOpen(id) ? items : items.slice(0, limit);
  const more = items.length - shown.length;
  return h('section.group',
    h('h2', title),
    h('div.rows', shown.map(item => row(item, item.job.id === selected))),
    more > 0 && h('button.link', {type: 'button', onclick: event => { setOpen(id, true); event.target.dispatchEvent(new CustomEvent('rerender', {bubbles: true})); }},
      `Show ${plural(more, 'more recording')}`));
}

export function renderList(state, selected) {
  const g = groups(state), watches = upcoming(state);
  const out = [];
  if (state.paused) {
    out.push(h('div.notice',
      h('p', 'Automatic work is paused. Queued recordings start only when you start them.'),
      button('Resume automatic work', () => api('command', {command: 'resume'}), {done: 'Automatic work resumed.'})));
  }
  out.push(list('In progress', g.active, selected));
  out.push(list('Needs you', g.action, selected));
  out.push(list('Waiting to start', g.waiting, selected));
  if (watches.length) {
    out.push(h('section.group', h('h2', 'Expected'),
      h('div.rows', watches.map(w => h('div.row.static',
        h('span.row-title', w.case_name),
        h('span.row-meta', `${w.docket} · watching for audio and transcript`),
        h('span.row-status', w.last_checked_at ? `Last checked ${dateTime(w.last_checked_at)}; checks until ${new Date(w.ends_at).toLocaleTimeString(undefined, {hour: 'numeric', minute: '2-digit'})}` : `Checks start ${dateTime(w.starts_at)}`))))));
  }
  if (state.statistics && (state.statistics.status !== 'idle' || Object.keys(state.statistics.questions || {}).length)) {
    const stats = state.statistics;
    out.push(h('section.group', h('h2', 'Statistics'), h('a.row', {href: '#/settings'},
      h('span.row-title', stats.message || 'Statistics update ' + stats.status),
      h('span.row-meta', `${stats.count || 0} cases · ${stats.pending || 0} updates pending`),
      Object.keys(stats.questions || {}).length && h('span.row-todo', 'Codex needs your input'))));
  }
  out.push(list('Done', g.done, selected, 6));
  if (!Object.keys(state.jobs || {}).length) out.push(h('p.calm', 'No recordings yet. New arguments are discovered automatically, or add one in Settings.'));
  return out;
}
