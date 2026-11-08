// One recording: the decisions it needs first, then progress, repairs and background.
import {h, link, safeUrl, plural, textFromHtml, longDate, dateTime, duration, clock} from './dom.js';
import {
  describe, STAGES, stageName, recoveriesFor, phasePassed, pendingQuestions, cardsPending, missingPortraits,
  photoRequestActive, reviewEditable, uploadResult, readyToPublish, publishPending, chunkCounts,
} from './model.js';
import {api, smallImage} from './api.js';
import {clipsBlock} from './view-clips.js';
import {act, block, button, disclosure, draft, drafts, preview, submitForm} from './ui.js';

const ACTIVE = ['queued', 'starting', 'running'];
const fullImages = new Set();
function reviewVersion(review, scope = 'all', person = '') {
  const value = scope === 'photo' ? review.versions?.photos?.[person] : (review.versions?.[scope] ?? review.version);
  return Number.isInteger(value) ? {version: value} : {revision: review.revision};
}

/**
 * Card previews are too small to read on a phone: a tap shows the image across the whole screen.
 * A wide image on an upright phone is turned to use the screen's long side.
 */
function enlargeable(img) {
  img.classList.add('enlargeable');
  img.tabIndex = 0;
  img.setAttribute('role', 'button');
  img.setAttribute('aria-label', 'Enlarge ' + img.alt);
  img.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); img.click(); }
  });
  img.addEventListener('click', () => {
    if (!img.src || img.classList.contains('loading')) return;
    const large = h('img', {src: img.src, alt: img.alt});
    const hint = h('p.lightbox-hint');
    const layout = () => {
      const ratio = img.naturalWidth / img.naturalHeight, upright = innerHeight > innerWidth;
      const turned = upright && ratio > 1.3;
      view.classList.toggle('turned', turned);
      large.style.width = turned ? Math.min(innerHeight - 96, (innerWidth - 16) * ratio) + 'px' : '';
      hint.textContent = turned ? 'Turn your phone to read · tap to close' : 'Tap to close';
    };
    // A native modal makes the rest of the app inert and contains keyboard focus.
    const closeButton = h('button.lightbox-close', {type: 'button', autofocus: true}, 'Close');
    const view = h('dialog.lightbox', {'aria-label': img.alt, onclick: () => view.close()}, closeButton, large, hint);
    view.addEventListener('close', () => {
      view.remove();
      removeEventListener('resize', layout);
      if (img.isConnected) img.focus({preventScroll: true});
    }, {once: true});
    layout();
    addEventListener('resize', layout);
    document.body.append(view);
    view.showModal();
    closeButton.focus({preventScroll: true});
  });
  return img;
}

export function renderCase(state, id) {
  const job = state.jobs?.[id];
  if (!job) return [h('p.calm', 'This recording is not in the list any more.'), h('p', h('a', {href: '#/'}, 'Back to recordings'))];
  const info = describe(job, state), review = job.review;
  const editable = reviewEditable(job);
  const recs = recoveriesFor(state, job);
  const missing = missingPortraits(job);
  return [
    header(job, info),
    job.render_revision && block('Corrected render',
      h('p', job.render_revision.upload_matches_current ? 'The corrected MP4 is uploaded to YouTube.' : job.render_revision.upload_requested_at ? 'Uploading the corrected MP4 as a new unlisted video. The earlier upload is retained.' : job.render_revision.status==='complete' ? 'The corrected MP4 is ready. The existing YouTube video is unchanged.' : 'Rendering a corrected MP4 from the approved material. The existing YouTube video is unchanged.'),
      safeUrl(job.render_revision.existing_youtube_url) && link('View earlier YouTube upload',job.render_revision.existing_youtube_url,'button-link'),
      job.render_revision.status==='complete' && button('Download corrected MP4',async()=>{const result=await api('video_download',{job:job.id});location.assign(result.url);}),
      job.render_revision.status==='complete' && !job.render_revision.upload_matches_current && !job.render_revision.upload_requested_at && button('Upload corrected MP4 to YouTube',()=>api('command',{command:'upload_corrected',job:job.id}),{done:'Corrected upload queued.'})),
    job.research_attention && block('Card research', h('p', job.research_attention.message),
      button(job.research_attention.another_editor_pass ? 'Authorize another Opus pass' : 'Resume saved research',
        () => api('command', {job: job.id, command: 'research_resume', allow_opus_retry: !!job.research_attention.another_editor_pass}), {done: 'Saved research queued.'})),
    ...recs.filter(rec => pendingQuestions(state, rec).length).map(rec => questionBlock(state, rec)),
    review?.cards?.length && cardsPending(job) && (editable || job.annotation_revision_only) && cardsBlock(job),
    review && missing.length && portraitsBlock(job, missing, 'Portraits to approve'),
    stoppedBlock(job, recs, state),
    job.asset_publication?.status === 'failed' && block('Portrait commit failed',
      h('p', 'The approved portraits were not saved to GitHub. The video is unaffected; the commit keeps the portrait library current.'),
      h('div.actions', button('Retry portrait commit', () => api('review', {job: job.id, ...reviewVersion(review), command: 'asset_retry'}),
        {primary: true, done: 'Portrait commit queued.'}))),
    publishBlock(job),
    review && titleBlock(job),
    spotifyBlock(job, state),
    clipsBlock(job),
    progressBlock(job),
    importBlock(job),
    !job.stages.upload.checkpoint && (job.stages.prepare.status === 'failed' || job.stages.align.status === 'failed' || job.maintenance?.status === 'waiting') && block('Official sources',
      h('p', job.maintenance?.status === 'waiting' ? 'Waiting to refresh the official sources.' : 'Check whether the Court has replaced the transcript or recording.'),
      button('Refresh official sources', () => api('refresh_sources', {job: job.id}), {done: 'Source check requested.'})),
    recs.length && repairsBlock(state, recs),
    review ? backgroundBlock(job, editable, missing, activityBlock(state, job)) : activityBlock(state, job),
    manageBlock(job, state),
  ];
}

// ---------------------------------------------------------------- header
function importBlock(job) {
  if (job.stages.align.status !== 'complete' || (job.stages.plan.status !== 'pending' && job.status !== 'complete')) return null;
  const item = job.card_import, key = `import-file:${job.id}`, file = h('input', {type: 'file', accept: '.json,application/json', 'aria-label': 'Card file'});
  file.addEventListener('change', () => { if (file.files?.[0]) drafts.set(key, file.files[0]); });
  return disclosure(`import-${job.id}`, 'Import annotation cards', h('div',
    item && h('p', item.status === 'failed' ? item.error : `${item.card_count} imported cards: ${item.status.replaceAll('_', ' ')}.`),
    item && item.status !== 'complete' && button('Cancel import', () => api('card_import_cancel', {job: job.id}), {done: 'Card import cancelled.'}),
    h('p.note', drafts.get(key)?.name || 'Choose a card JSON file. Production previews will be prepared for your review.'), file,
    button('Prepare imported cards', async () => {
      const selected = file.files?.[0] || drafts.get(key);
      if (!selected) throw new Error('Choose a card file first.');
      if (selected.size > 1572864) throw new Error('Reduce the exhibit image sizes before importing.');
      const result = await api('card_import', {job: job.id, spec: JSON.parse(await selected.text())});
      drafts.delete(key);return result;
    }, {done: 'Card import queued.'})));
}

function header(job, info) {
  const upload = uploadResult(job);
  const seconds = job.stages.prepare.result?.duration_seconds;
  const links = [
    safeUrl(job.pdf_url) && link('Transcript', job.pdf_url),
    safeUrl(job.audio_url) && link('Audio', job.audio_url),
    safeUrl(upload.video_url) && link('YouTube', upload.video_url),
    /^[A-Za-z0-9_-]{11}$/.test(upload.video_id || '') && link('YouTube Studio', `https://studio.youtube.com/video/${upload.video_id}/edit`),
    /^[A-Za-z0-9]{22}$/.test(job.spotify?.episode_id || '') && link('Spotify', `https://open.spotify.com/episode/${job.spotify.episode_id}`),
  ].filter(Boolean);
  return h('header.case-head',
    h('h1', job.case_name),
    h('p.meta', [`No. ${job.docket}`, `argued ${longDate(job.argument_date)}`, seconds && duration(seconds)].filter(Boolean).join(' · ')),
    info.todo.length
      ? h('ul.todo', {dataset: {status: job.status, group: info.group}}, info.todo.map(text => h('li', text)))
      : info.line && h('p.status', {dataset: {status: job.status, group: info.group}}, info.line),
    links.length && h('p.links', links));
}

// ---------------------------------------------------------------- questions

function questionBlock(state, rec) {
  const questions = pendingQuestions(state, rec);
  const answered = Object.values(rec.questions || {}).filter(q => q.status !== 'pending');
  return block(questions.length === 1 ? 'Question from Codex' : 'Questions from Codex',
    h('p.note', `While repairing ${stageName(rec.stage).toLowerCase()} · ${plural(rec.turns, 'repair turn')}`),
    questions.map(question => questionForm(rec, question)),
    answered.length && disclosure(`answered-${rec.id}`, `Earlier questions (${answered.length})`, answered.map(answeredQuestion)),
    logDisclosure(rec),
    h('div.actions', button('Stop this repair', () => api('recovery_command', {recovery: rec.id, command: 'stop'}),
      {confirm: 'Stop this repair? The recording stays stopped until you retry it.', done: 'Repair stopped.'})));
}

function questionForm(rec, question) {
  const key = `answer:${rec.id}:${question.id}`;
  const choice = drafts.get(key + ':choice') || '';
  const options = (question.options || []).map(option => {
    const input = h('input', {type: 'radio', name: key, value: option.id, checked: choice === option.id});
    input.addEventListener('change', () => drafts.set(key + ':choice', option.id));
    const who = option.actor === 'operator' ? 'You act' : option.actor === 'worker' ? 'Codex acts' : '';
    return h('label.option', input, h('span',
      h('span.option-label', option.label),
      option.private_effect && h('span.note', (who ? who + ': ' : '') + option.private_effect)));
  });
  const text = draft(key + ':text', h('textarea', {name: 'text', rows: 3, maxLength: 4000}));
  const form = h('form.question',
    h('p.question-text', question.message),
    options.length && h('fieldset', h('legend.note', 'Choose an answer'), options),
    h('label', options.length ? 'Additional instructions (optional)' : 'Your answer', text),
    h('div.actions', h('button.primary', {type: 'submit', disabled: rec.status !== 'needs_input'}, 'Send answer')));
  return submitForm(form, async () => {
    const value = drafts.get(key + ':choice') || '';
    if (!value && !text.value.trim()) throw Error('Choose an answer or write one.');
    await api('recovery_answer', {recovery: rec.id, question: question.id, revision: rec.input_revision, choice: value, text: text.value});
    drafts.delete(key + ':choice'); drafts.delete(key + ':text');
    return 'Answer sent. Codex will continue.';
  });
}

function answeredQuestion(question) {
  const choice = (question.options || []).find(o => o.id === question.answer?.choice);
  return h('div.answered',
    h('p.question-text', question.message),
    question.status === 'dismissed'
      ? h('p.note', 'No longer needed: ' + (question.reason || 'the phase completed.'))
      : h('p.note', 'Answered: ' + [choice?.label, question.answer?.text].filter(Boolean).join(' — ')));
}

function logDisclosure(rec, open = false) {
  return disclosure(`log-${rec.id}`, `Repair log (${(rec.log || []).length})`, open,
    h('ol.log', (rec.log || []).slice().reverse().map(entry =>
      h('li', h('span.note', `${dateTime(entry.at)} · ${entry.kind}`), h('p', entry.message)))));
}

// ---------------------------------------------------------------- annotation cards

function cardSelections(job) {
  const review = job.review, key = `cards:${job.id}:${review.card_revision}`;
  if (!drafts.has(key)) {
    drafts.set(key, Object.fromEntries(review.cards.map(card => [card.id, job.card_selections?.[card.id] ?? card.recommended])));
  }
  return drafts.get(key);
}

function cardsBlock(job, nested = false) {
  const review = job.review, selections = cardSelections(job), editable = reviewEditable(job) || !!job.annotation_revision_only;
  const pending = cardsPending(job);
  const summary = h('p.note');
  const updateSummary = () => {
    const shown = Object.values(selections).filter(Boolean).length;
    summary.textContent = `${shown} shown, ${review.cards.length - shown} hidden`;
  };
  updateSummary();
  const items = review.cards.map(card => {
    const cue = card.cue || {};
    const show = h('button', {type: 'button', 'aria-pressed': String(!!selections[card.id]), disabled: !editable}, 'Show');
    const hide = h('button', {type: 'button', 'aria-pressed': String(!selections[card.id]), disabled: !editable}, 'Hide');
    const choose = value => () => {
      selections[card.id] = value;
      show.setAttribute('aria-pressed', String(value)); hide.setAttribute('aria-pressed', String(!value));
      updateSummary();
    };
    show.addEventListener('click', choose(true)); hide.addEventListener('click', choose(false));
    return h('article.card-item',
      enlargeable(preview({job: job.id, kind: 'card', candidate: card.id}, card.card_uri, 'Annotation card as rendered', 'card-image')),
      h('p.card-head', [`${clock(card.start)}–${clock(card.end)}`, cue.label || cue.kind, textFromHtml(cue.heading || cue.case?.name || '')].filter(Boolean).join(' · ')),
      h('p.note', `Recommended: ${card.recommended ? 'show' : 'hide'}. ${card.reason || ''}`),
      h('div.segmented', {role: 'group', 'aria-label': 'Show or hide this card'}, show, hide),
      disclosure(`card-sources-${job.id}-${card.id}`, 'Sources and full frame',
        enlargeable(preview({job: job.id, kind: 'card', candidate: card.id, variant: 'frame'}, card.frame_uri, 'Card in the full video frame', 'frame-image')),
        (card.sources || []).map(source => h('div.source',
          safeUrl(source.url) && link(`Source, page ${source.page}`, source.url),
          source.quote && h('blockquote', source.quote)))));
  });
  const approve = h('button.primary', {type: 'button', disabled: !editable}, pending ? 'Approve card selections' : 'Save card selections');
  approve.addEventListener('click', () => act(approve, async () => {
    await api('review', {job: job.id, ...reviewVersion(review, 'cards'), command: 'cards', selections});
    return 'Card selections saved.';
  }));
  const content = [
    job.annotation_revision_only && h('p.note', 'These are revised proposals. Saving selections keeps the existing video; it does not start a new render.'),
    !editable && h('p.note', 'Rendering has started; card selections can no longer change.'),
    items,
    editable && h('div.actions.sticky', summary, approve)];
  return nested ? h('div', content) : block(null, disclosure(`card-review-${job.id}`, pending ? 'Annotation cards to review' : 'Annotation cards', true, ...content));
}

// ---------------------------------------------------------------- portraits

function portraitsBlock(job, people, title) {
  const photos = job.review.photos;
  return block(title, people.map(person => personBlock(job, person, photos[person])));
}

function personBlock(job, person, item, compact = false) {
  const editable = reviewEditable(job);
  const requests = Object.values(job.photo_requests || {}).filter(r => r.person === person).reverse();
  const busy = photoRequestActive(job, person);
  const usable = (item.candidates || []).filter(c => !c.rejected);
  const rejected = (item.candidates || []).filter(c => c.rejected);
  const latest = requests[0];
  const actionName = {different: 'finding a different image', recrop: 'recropping', synthetic: 'making an initials or logo image'};
  return h('div.person', {class: compact ? 'portrait-editor' : undefined},
    !compact && h('h3', item.name),
    !editable && !compact && h('p.note', job.status === 'cancelled' ? 'This recording was cancelled; portraits can no longer change.' : 'Planning has started; portraits can no longer change.'),
    item.identity_evidence && disclosure(`identity-${job.id}-${person}`, 'Advocate details', h('p.note', item.identity_evidence)),
    busy && h('p.status', `Codex is ${actionName[latest.action] || latest.action} (${latest.status}).`),
    requests.filter(r => r.status === 'failed').slice(0, 1).map(r => h('div.problem',
      h('p', 'The last image request failed' + (r.error ? ': ' + r.error : '.')),
      button('Retry image request', () => api('review', {job: job.id, ...reviewVersion(job.review, 'photo', r.person), command: 'photo_retry', request: r.id})))),
    usable.length
      ? h('div.candidates', usable.map(c => candidateTile(job, person, item, c, busy, editable)))
      : !busy && h('p', 'No usable image yet. An image is required before this recording can continue.'),
    rejected.length && disclosure(`rejected-${job.id}-${person}`, `Rejected images (${rejected.length})`,
      h('div.candidates', rejected.map(c => candidateTile(job, person, item, c, true, false)))),
    (item.private_notes || []).length && disclosure(`notes-${job.id}-${person}`, 'Research notes', item.private_notes.map(n => h('p.note', n))),
    editable && requestForm(job, person, usable[0], busy),
    editable && uploadForm(job, person));
}

function candidateTile(job, person, item, candidate, busy, editable) {
  const approved = job.approved_photos?.[person]?.id === candidate.id;
  const waitingForCrop = candidate.kind === 'photo' && candidate.origin !== 'curated_cache' && !candidate.square_asset;
  const fullKey = `${job.id}:${person}:${candidate.id}`, full = fullImages.has(fullKey);
  const request = {job: job.id, kind: 'photo', person, candidate: candidate.id, variant: full ? 'source' : ''};
  const image = preview(request, full ? candidate.source_preview_uri || candidate.preview_uri : candidate.preview_uri, item.name, full ? 'portrait full' : 'portrait');
  const toggle = h('button.link', {type: 'button'}, full ? 'Show crop' : 'Show full image');
  toggle.addEventListener('click', () => {
    if (full) fullImages.delete(fullKey); else fullImages.add(fullKey);
    toggle.dispatchEvent(new CustomEvent('rerender', {bubbles: true}));
  });
  const origin = {curated_cache: 'Saved portrait', research: 'Found by Codex', owner_url: 'Your image URL', upload: 'Your upload'}[candidate.origin] || '';
  return h('figure.candidate', {class: approved ? 'approved' : undefined},
    image,
    h('figcaption',
      h('span.note', [candidate.kind && candidate.kind !== 'photo' ? candidate.kind : '', origin].filter(Boolean).join(' · ') || 'Photo'),
      h('div.candidate-links', candidate.source_preview_uri && toggle,
        safeUrl(candidate.source_url) && link('Image source', candidate.source_url),
        safeUrl(candidate.identity_source_url) && candidate.identity_source_url !== candidate.source_url && link('Identity source', candidate.identity_source_url)),
      (candidate.crop_note || candidate.private_note) && disclosure(`cnote-${job.id}-${candidate.id}`, 'Notes',
        candidate.crop_note && h('p.note', candidate.crop_note), candidate.private_note && h('p.note', candidate.private_note)),
      approved ? h('p.done', 'Approved')
        : candidate.rejected ? h('p.note', 'Rejected')
        : waitingForCrop ? h('p.note', 'Waiting for the square crop')
        : button('Approve', () => api('review', {job: job.id, ...reviewVersion(job.review, 'photo', person), command: 'photo', person, candidate: candidate.id}),
          {primary: true, disabled: busy || !editable, done: `Portrait approved for ${item.name}.`})));
}

function requestForm(job, person, candidate, busy) {
  const key = `photo-request:${job.id}:${person}`;
  const action = draft(key + ':action', h('select', {name: 'action'},
    h('option', {value: 'different'}, 'Find a different image'),
    candidate?.kind === 'photo' && h('option', {value: 'recrop'}, 'Recrop this image'),
    h('option', {value: 'synthetic'}, 'Use initials or a firm or agency logo')), 'different');
  const hint = draft(key + ':hint', h('textarea', {name: 'hint', rows: 2, maxLength: 2000}));
  const enrichRunning = ['starting', 'running'].includes(job.stages.enrich.status);
  const form = h('form',
    h('label', 'What should Codex do?', action),
    h('label', 'Hint or reason (optional)', hint),
    h('div.actions', h('button', {type: 'submit', disabled: busy || enrichRunning}, 'Send to Codex')),
    enrichRunning && h('p.note', 'Available once research finishes.'));
  return disclosure(`request-${job.id}-${person}`, candidate ? 'Ask Codex to change the image' : 'Ask Codex for an image', submitForm(form, async () => {
    await api('review', {job: job.id, ...reviewVersion(job.review, 'photo', person), command: 'photo_request', person,
      candidate: candidate?.id || '', action: action.value, hint: hint.value});
    drafts.delete(key + ':hint');
    return 'Request sent to Codex.';
  }));
}

function uploadForm(job, person) {
  const form = h('form',
    h('label', 'Image', h('input', {name: 'image', type: 'file', accept: 'image/*', required: true})),
    h('label', 'Type', h('select', {name: 'kind'},
      h('option', {value: 'photo'}, 'Photo'), h('option', {value: 'logo'}, 'Firm or agency logo'), h('option', {value: 'initials'}, 'Initials or other graphic'))),
    h('label', 'Source link', h('input', {name: 'source_url', type: 'url', placeholder: 'https://…'})),
    h('label', 'Private note', h('input', {name: 'note', maxLength: 2000})),
    h('div.actions', h('button', {type: 'submit'}, 'Add image')));
  return disclosure(`upload-${job.id}-${person}`, 'Upload your own image', submitForm(form, async () => {
    const values = new FormData(form);
    const image = await smallImage(values.get('image'));
    await api('photo_add', {job: job.id, ...reviewVersion(job.review, 'photo', person), person, image,
      kind: values.get('kind'), source_url: values.get('source_url'), note: values.get('note')});
    return 'Image added.';
  }));
}

// ---------------------------------------------------------------- failure, publication, title

function stoppedBlock(job, recs, state) {
  if (job.status !== 'failed') return null;
  const repairing = recs.some(r => ['queued', 'starting', 'running', 'needs_input', 'waiting_for_stage', 'waiting_for_tests'].includes(r.status) && !phasePassed(state, r));
  if (repairing) return null;
  const [key, stage] = Object.entries(job.stages).find(([, s]) => s.status === 'failed') || [];
  const uncertain = stage?.error === 'upload_uncertain';
  return block('Stopped',
    h('p', key ? `${stageName(key)} failed${stage.error ? ': ' + stage.error.replace(/_/g, ' ') : ''}.` : 'This recording stopped.'),
    uncertain
      ? h('p.note', 'The upload may have reached YouTube. Check YouTube Studio before retrying so the video is not uploaded twice.')
      : h('p.note', 'Retry resumes from the failed phase; completed phases and your approvals are kept.'),
    h('div.actions', button('Retry', () => api('command', {command: 'retry', job: job.id}), {primary: true, disabled: uncertain, done: 'Retry queued.'})));
}

function publishBlock(job) {
  const upload = uploadResult(job), review = job.review;
  const failures = Object.values(job.video_actions || {}).filter(a => a.status === 'failed');
  const ready = readyToPublish(job), pending = publishPending(job);
  if (!ready && !failures.length) return null;
  const retry = action => button(action.kind === 'publish' ? 'Retry publication' : 'Retry title update', () => {
    const index = review.titles.findIndex(c => c.title === action.title);
    return api('review', {job: job.id, ...reviewVersion(review, 'title'), command: action.kind,
      ...(action.kind === 'title' ? {title: action.title} : {index})});
  });
  const thumbnail = job.stages.plan.result?.thumbnail_preview_uri;
  return block(ready && !pending ? 'Ready to publish' : 'Publication',
    thumbnail && preview({job: job.id, kind: 'thumbnail'}, thumbnail, 'Video thumbnail', 'thumbnail'),
    h('p.video-title', job.title),
    ready && !pending && h('p.note', 'The video is unlisted on YouTube. Publishing makes it public and visible to subscribers.'),
    pending && h('p.status', 'Publication requested; YouTube updates within a minute.'),
    failures.map(a => h('div.problem', h('p', (a.kind === 'publish' ? 'Publication' : 'Title update') + ' failed.'), retry(a))),
    h('div.actions',
      ready && !pending && button('Publish on YouTube', () => api('review', {job: job.id, ...reviewVersion(review, 'title'), command: 'publish'}),
        {primary: true, confirm: `Make “${job.title}” public on YouTube?`, done: 'Publication requested.'}),
      safeUrl(upload.video_url) && link('Watch unlisted video', upload.video_url, 'button-link')));
}

function titleBlock(job) {
  const review = job.review, upload = uploadResult(job);
  const current = job.selected_title || review.titles[0]?.title || job.title;
  const titlePending = Object.values(job.video_actions || {}).some(a => a.kind === 'title' && ACTIVE.includes(a.status));
  const uploading = ['starting', 'running'].includes(job.stages.upload.status);
  const locked = titlePending || uploading || !!(upload.video_id && !upload.postprocessing_complete);
  const onYouTube = !!upload.video_id;
  const alternatives = review.titles.map((candidate, index) => {
    const selected = candidate.title === current;
    return h('div.alternative', {class: selected ? 'selected' : undefined},
      h('p.alt-title', candidate.title),
      candidate.private_reason && h('p.note', candidate.private_reason),
      selected ? h('p.done', 'Current title')
        : button(onYouTube ? 'Use and update on YouTube' : 'Use this title',
          () => api('review', {job: job.id, ...reviewVersion(review, 'title'), command: 'title', index}),
          {disabled: locked, done: onYouTube ? 'Title update requested.' : 'Title saved.'}));
  });
  const key = `title:${job.id}`;
  const input = draft(key, h('textarea', {name: 'title', rows: 2, maxLength: 100, required: true}), current);
  const count = h('span.note');
  const updateCount = () => { count.textContent = `${[...input.value].length}/100`; };
  input.addEventListener('input', updateCount); updateCount();
  const form = h('form', h('label', 'Custom title', input),
    h('div.actions', count, h('button', {type: 'submit', disabled: locked}, onYouTube ? 'Update on YouTube' : 'Save title')));
  submitForm(form, async () => {
    await api('review', {job: job.id, ...reviewVersion(review, 'title'), command: 'title', title: input.value});
    drafts.delete(key);
    return onYouTube ? 'Title update requested.' : 'Title saved.';
  });
  const showCurrent = !readyToPublish(job);
  return block('Title',
    showCurrent && h('p.video-title', current),
    titlePending && h('p.status', 'Updating the title on YouTube…'),
    uploading && h('p.note', 'The title can change again once the upload finishes.'),
    disclosure(`titles-${job.id}`, review.titles.length > 1 ? `Alternatives and reasoning (${review.titles.length})` : 'Reasoning and custom title',
      alternatives, form));
}

// ---------------------------------------------------------------- spotify

function spotifyBlock(job, state) {
  const upload = uploadResult(job);
  if (!state.spotify_enabled || job.stages.upload.status !== 'complete' || !upload.postprocessing_complete) return null;
  const item = job.spotify || {}, status = item.status || '';
  const labels = {queued: 'Transfer queued', waiting_episode: 'Waiting for the podcast episode to appear', starting: 'Starting transfer',
    uploading: `Uploading ${Math.round((item.progress || 0) * 100)}%`, uploaded: 'Uploaded; ready to publish on Spotify',
    publish_queued: 'Publication requested', publishing: 'Spotify is processing', published: 'Published on Spotify',
    needs_auth: 'Spotify needs reconnecting', failed: 'Transfer failed'};
  const command = (value, extra = {}) => () => api('spotify', {job: job.id, command: value, ...extra});
  const episode = h('form',
    h('label', 'Spotify episode ID', h('input', {name: 'episode_id', required: true, pattern: '[A-Za-z0-9]{22}', maxLength: 22})),
    h('div.actions', h('button', {type: 'submit'}, 'Retry with this episode')));
  submitForm(episode, form => api('spotify', {job: job.id, command: 'retry', episode_id: form.elements.episode_id.value}));
  return block('Spotify',
    h('p', status ? labels[status] || status : 'The video is not on Spotify yet.'),
    item.error && h('p.note', item.error),
    item.thumbnail_note && h('p.note', item.thumbnail_note),
    h('div.actions',
      !status && button('Upload and publish on Spotify', command('transfer'), {done: 'Spotify transfer requested.'}),
      status === 'uploaded' && button('Finish Spotify transfer', command('transfer'), {primary: true,
        confirm: 'Replace the audio-only player on this Spotify episode with the uploaded video? The RSS podcast stays unchanged.'}),
      ['failed', 'needs_auth'].includes(status) && button('Retry transfer', command('retry')),
      status === 'needs_auth' && h('a.button-link', {href: '#/settings'}, 'Reconnect in Settings')),
    ['failed', 'needs_auth'].includes(status) && !item.upload_id && disclosure(`spotify-episode-${job.id}`, 'Choose the episode manually', episode));
}

// ---------------------------------------------------------------- progress and repairs

function stageDetail(key, stage) {
  if (stage.status === 'complete') {
    const elapsed = (Date.parse(stage.finished_at) - Date.parse(stage.started_at)) / 1000;
    return duration(elapsed) || 'done';
  }
  if (['starting', 'running'].includes(stage.status)) {
    if (key === 'render' && stage.tasks?.length) {
      const c = chunkCounts(stage);
      return `${c.complete} of ${c.total} chunks` + (c.failed ? `, ${c.failed} failed` : '');
    }
    return stage.status === 'starting' ? 'starting' : `${Math.round((stage.progress || 0) * 100)}%`;
  }
  if (stage.status === 'needs_review') return 'waiting for your review';
  if (stage.status === 'failed') return 'failed' + (stage.error ? ': ' + stage.error.replace(/_/g, ' ') : '');
  if (stage.status === 'cancelled') return 'cancelled';
  return '';
}

function progressBlock(job) {
  const labels = {chunks: 'Download and verify chunks', audio: 'Prepare audio', mux: 'Join video and audio', check: 'Verify output', save: 'Save artifact'};
  const timings = job.stages.assemble.result?.timings_seconds || job.stages.upload.result?.timings_seconds;
  return block('Progress',
    h('ol.phases', Object.entries(job.stages).map(([key, stage]) =>
      h('li', {dataset: {status: stage.status}},
        h('span.phase-name', STAGES[key]?.name || key),
        h('span.phase-detail', stageDetail(key, stage), stage.attempt > 1 && stage.status === 'complete' ? ` · attempt ${stage.attempt}` : '',
          key === 'align' && stage.result?.warnings > 0 && h('span.alignment-note', `${plural(stage.result.warnings, 'warning')} handled automatically`))))),
    timings && disclosure(`timings-${job.id}`, 'Assembly timings',
      h('dl.pairs', Object.entries(timings).filter(([, v]) => Number.isFinite(Number(v))).map(([k, v]) => [h('dt', labels[k] || k), h('dd', `${Number(v).toFixed(1)} s`)]))));
}

function repairsBlock(state, recs) {
  const labels = {repaired: 'resolved', cancelled: 'stopped', waiting_for_stage: 'waiting for the phase to retry',
    waiting_for_tests: 'running isolated checks', waiting_for_resource: 'paused: daily repair budget reached',
    needs_input: 'waiting for your answer', unresolved: 'stopped; needs your decision', queued: 'queued', starting: 'starting', running: 'running'};
  return block('Repairs', recs.map(rec => {
    const passed = phasePassed(state, rec);
    const status = passed && rec.status === 'running' ? 'phase completed; finishing log' : labels[rec.status] || rec.status.replace(/_/g, ' ');
    const open = ['unresolved', 'waiting_for_resource'].includes(rec.status) && !passed;
    const log = (rec.log || []).slice().reverse();
    const tone = passed || rec.status === 'repaired' ? 'success' : rec.status === 'unresolved' ? 'failure' : 'attention';
    return disclosure(`repair-${rec.id}`, h('span.repair-heading',
      h('strong', stageName(rec.stage)), h('span.repair-status', {dataset: {tone}}, status)), open,
      h('p.repair-meta.note', `${plural(rec.turns, 'repair turn')} · ${dateTime(rec.created_at)}${rec.finished_at ? ' – ' + dateTime(rec.finished_at) : ''}`),
      (passed || rec.resolution) && h('p.repair-resolution', passed ? 'Phase completed successfully.' : rec.resolution),
      !passed && h('div.actions',
        ['unresolved', 'waiting_for_resource'].includes(rec.status) && button('Resume repair', () => api('recovery_command', {recovery: rec.id, command: 'resume'}), {primary: true}),
        ['queued', 'starting', 'running', 'waiting_for_resource', 'waiting_for_stage', 'waiting_for_tests'].includes(rec.status) &&
          button('Stop repair', () => api('recovery_command', {recovery: rec.id, command: 'stop'}), {confirm: 'Stop this repair?'})),
      Object.values(rec.questions || {}).some(q => q.status !== 'pending') && disclosure(`repair-answers-${rec.id}`, 'Previous answers',
        Object.values(rec.questions || {}).filter(q => q.status !== 'pending').map(answeredQuestion)),
      disclosure(`repair-history-${rec.id}`, `Repair log (${log.length})`,
        h('ol.log', log.map(entry => h('li',
          h('span.note', `${dateTime(entry.at)} · ${entry.kind}`), h('p', entry.message))))));
  }));
}

// ---------------------------------------------------------------- background material

function backgroundBlock(job, editable, missing, activity) {
  const review = job.review;
  const approved = Object.keys(review.photos || {}).filter(person => !missing.includes(person));
  const cardsDone = review.cards?.length && !(cardsPending(job) && (editable || job.annotation_revision_only));
  const thumbnail = job.stages.plan.result?.thumbnail_preview_uri;
  const frame = job.stages.render.tasks?.[0]?.result?.preview_uri;
  const showThumbnail = thumbnail && !readyToPublish(job);
  return block('Details',
    approved.length && disclosure(`approved-${job.id}`, `Portraits (${approved.length} approved)`,
      approved.map(person => {
        const choice = job.approved_photos[person];
        const summary = h('span.portrait-summary',
          preview({job: job.id, kind: 'photo', person, candidate: choice.id}, review.photos[person].candidates?.find(c => c.id === choice.id)?.preview_uri, review.photos[person].name, 'avatar'),
          h('span', h('strong', review.photos[person].name), h('span.note', editable ? 'Approved · change image' : 'Approved')));
        return editable ? disclosure(`change-${job.id}-${person}`, summary, personBlock(job, person, review.photos[person], true))
          : h('div.approved-person', summary);
      }),
      (job.asset_publication?.results || []).filter(r => safeUrl(r.url)).map(r => link('Portrait commit on GitHub', r.url, 'small'))),
    cardsDone && disclosure(`cards-${job.id}`, `Annotation cards (${Object.values(job.card_selections || {}).filter(Boolean).length} of ${review.cards.length} shown)`,
      cardsBlock(job, true)),
    (showThumbnail || frame) && disclosure(`previews-${job.id}`, 'Thumbnail and rendered frame',
      showThumbnail && preview({job: job.id, kind: 'thumbnail'}, thumbnail, 'Video thumbnail', 'thumbnail'),
      frame && preview({job: job.id, kind: 'frame'}, frame, 'Rendered frame', 'thumbnail')),
    disclosure(`description-${job.id}`, 'Case description',
      h('p', textFromHtml(review.description?.facts_of_the_case)),
      h('p', textFromHtml(review.description?.question))),
    ((review.private_notes || []).length || Object.keys(review.provenance || {}).length) && disclosure(`research-${job.id}`, 'Research notes and sources',
      (review.private_notes || []).filter(note => !note.startsWith('Saved opportunity decisions:')).map(note => h('p.note', note)),
      Object.entries(review.provenance || {}).map(([field, record]) => h('div.provenance',
        h('p', h('strong', field.replace(/_/g, ' ')), ' · ', record.method),
        (record.sources || []).filter(s => safeUrl(s.url)).map(s => link(s.title || 'Source', s.url, 'small'))))),
    activity);
}

function activityBlock(state, job) {
  const events = (state.events || []).filter(e => e.job === job.id).reverse().slice(0, 40);
  if (!events.length) return null;
  return disclosure(`activity-${job.id}`, `Activity (${events.length})`,
    h('ol.log', events.map(e => h('li', h('span.note', dateTime(e.at)), h('p', e.message)))));
}

function manageBlock(job, state) {
  const queued = job.status === 'queued';
  const buttons = [
    queued && !job.run_requested && state.paused && button('Start this recording', () => api('command', {command: 'start', job: job.id}),
      {primary: true, done: 'Start requested.'}),
    queued && job.run_requested && h('p.note', 'Start requested; it begins at the next check.'),
    job.status === 'cancelled' && button('Retry', () => api('command', {command: 'retry', job: job.id}), {done: 'Retry queued.'}),
    !['complete', 'cancelled'].includes(job.status) && button('Cancel recording', () => api('command', {command: 'cancel', job: job.id}),
      {danger: true, confirm: `Cancel ${job.case_name}? Running work stops; you can retry later.`, done: 'Cancellation requested.'}),
  ].filter(Boolean);
  if (!buttons.length) return null;
  return h('section.block.manage', h('div.actions', buttons));
}
