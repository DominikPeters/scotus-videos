// Derived status: what each recording needs from the owner, and how far along it is.
import {plural, shortDate} from './dom.js';

export const STAGES = {
  prepare: {name: 'Prepare sources', active: 'Preparing sources'},
  enrich: {name: 'Research', active: 'Researching'},
  align: {name: 'Align audio', active: 'Aligning audio'},
  plan: {name: 'Plan video', active: 'Planning'},
  render: {name: 'Render', active: 'Rendering'},
  assemble: {name: 'Assemble', active: 'Assembling'},
  upload: {name: 'Upload', active: 'Uploading'},
};
export const stageName = key => STAGES[key]?.name || key;

const ACTIVE = ['queued', 'starting', 'running'];
const PUBLISH_READY = ['Ready to publish', 'Ready to publish on Spotify'];
const REPAIRING = ['queued', 'starting', 'running', 'waiting_for_stage', 'waiting_for_tests'];

export const recoveriesFor = (state, job) =>
  Object.values(state.recoveries || {}).filter(r => r.job === job.id)
    .sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''));

/** A recovery whose phase has since completed is history even if its record lags. */
export function phasePassed(state, rec) {
  const stage = state.jobs?.[rec.job]?.stages?.[rec.stage];
  return stage?.status === 'complete' && stage.recovery_id === rec.id;
}

export const pendingQuestions = (state, rec) =>
  rec.status === 'needs_input' && !phasePassed(state, rec)
    ? Object.values(rec.questions || {}).filter(q => q.status === 'pending') : [];

export const cardsPending = job =>
  !!job.review?.cards?.length && job.cards_approved_revision !== job.review.card_revision;

export const photoRequestActive = (job, person) =>
  Object.values(job.photo_requests || {}).some(r => r.person === person && ACTIVE.includes(r.status));

export const missingPortraits = job =>
  Object.keys(job.review?.photos || {}).filter(person => !job.approved_photos?.[person]);

export const reviewEditable = job =>
  job.status !== 'cancelled' && job.stages.plan.status === 'pending';

export const uploadResult = job => job.stages.upload.result || {};

export const publishPending = job =>
  Object.values(job.video_actions || {}).some(a => a.kind === 'publish' && ACTIVE.includes(a.status));

export const readyToPublish = job => {
  const upload = uploadResult(job);
  if (job.render_revision?.upload_matches_current === false) return false;
  return job.stages.upload.status === 'complete' && upload.postprocessing_complete &&
    job.privacy === 'unlisted' && job.status === 'complete';
};

export function progress(job) {
  const stages = Object.values(job.stages);
  return stages.reduce((sum, s) => sum + (s.status === 'complete' ? 1 : s.progress || 0), 0) / stages.length;
}

export function chunkCounts(stage) {
  const counts = {total: stage.tasks?.length || 0, complete: 0, running: 0, failed: 0};
  for (const task of stage.tasks || []) if (task.status in counts) counts[task.status]++;
  return counts;
}

function activeLine(job, state) {
  const running = Object.entries(job.stages).filter(([, s]) => ['starting', 'running'].includes(s.status));
  if (running.length) {
    return running.map(([key, s]) => {
      let text = STAGES[key]?.active || key;
      if (key === 'render' && s.tasks?.length) {
        const c = chunkCounts(s);
        text += ` · ${c.complete} of ${c.total} chunks`;
      } else if (s.status === 'running' && s.progress > 0 && s.progress < 1) text += ` · ${Math.round(s.progress * 100)}%`;
      return text;
    }).join(', ');
  }
  if (job.stages.upload.status === 'complete' && !uploadResult(job).postprocessing_complete) return 'YouTube is processing the upload';
  if (publishPending(job)) return 'Publication requested';
  if (job.status === 'needs_review') return 'Preparing new portrait options';
  if (job.status === 'queued') return job.run_requested || !state.paused ? 'Queued' : 'Waiting: automatic work is paused';
  return '';
}

/**
 * Summarize one recording. todo items are decisions or fixes only the owner can make;
 * everything else is a status line.
 */
export function describe(job, state) {
  const todo = [];
  if (job.research_attention) todo.push('Card research needs your decision');
  const recs = recoveriesFor(state, job);
  const questions = recs.flatMap(rec => pendingQuestions(state, rec));
  if (questions.length) todo.push(questions.length === 1 ? 'Codex has a question' : `Codex has ${questions.length} questions`);
  if (recs.some(r => r.status === 'unresolved' && !phasePassed(state, r))) todo.push('Repair stopped; needs your decision');
  if (recs.some(r => r.status === 'waiting_for_resource' && !phasePassed(state, r))) todo.push('Repair paused: daily budget reached');
  if (['failed', 'needs_rebind'].includes(job.card_import?.status)) todo.push('Card import needs attention');
  else if (cardsPending(job) && (reviewEditable(job) || job.annotation_revision_only) && !['uploading', 'queued', 'starting', 'running', 'waiting_for_metadata'].includes(job.card_import?.status)) todo.push(plural(job.review.cards.length, 'annotation card') + ' to review');
  const portraits = missingPortraits(job).filter(person => !photoRequestActive(job, person));
  if (portraits.length && reviewEditable(job)) todo.push(plural(portraits.length, 'portrait') + ' to approve');
  if (Object.values(job.photo_requests || {}).some(r => r.status === 'failed')) todo.push('Portrait request failed');
  const repairing = recs.some(r => REPAIRING.includes(r.status) && !phasePassed(state, r));
  if (job.status === 'failed' && !repairing && !questions.length) {
    const [key, stage] = Object.entries(job.stages).find(([, s]) => s.status === 'failed') || [];
    todo.push(key ? `Stopped at ${stageName(key).toLowerCase()}${stage.error ? ': ' + stage.error.replace(/_/g, ' ') : ''}` : 'Stopped');
  }
  if (readyToPublish(job) && !publishPending(job)) todo.push('Ready to publish');
  for (const action of Object.values(job.video_actions || {})) {
    if (action.status === 'failed') todo.push(action.kind === 'publish' ? 'Publication failed' : 'Title update failed');
  }
  if (job.asset_publication?.status === 'failed') todo.push('Portrait commit to GitHub failed');
  if (state.spotify_enabled) {
    const spotify = job.spotify?.status;
    if (spotify === 'uploaded') todo.push('Ready to publish on Spotify');
    if (spotify === 'needs_auth') todo.push('Spotify needs reconnecting');
    if (spotify === 'failed') todo.push('Spotify transfer failed');
  }

  // Publishing can wait deliberately, so ready videos form their own calm group; only
  // decisions and fixes that hold up work count as needing the owner.
  const urgent = todo.filter(text => !PUBLISH_READY.includes(text));
  let group, line;
  if (urgent.length) {
    group = 'action';
    line = todo.join(' · ');
  } else if (todo.length) {
    group = 'publish';
    line = todo.join(' · ');
  } else if (job.status === 'cancelled') {
    group = 'done'; line = 'Cancelled';
  } else if (job.status === 'complete' && job.privacy === 'public') {
    group = 'done'; line = 'Published';
  } else if (job.status === 'queued' && !job.run_requested && state.paused) {
    group = 'waiting'; line = 'Waiting: automatic work is paused';
  } else {
    group = 'active';
    const base = activeLine(job, state);
    const repair = repairing && `Repairing ${stageName(recs.find(r => REPAIRING.includes(r.status)).stage).toLowerCase()}`;
    line = !repair ? base : job.status === 'failed' || !base ? repair : `${base} · repair in progress`;
  }
  return {job, group, todo, urgent, line, progress: progress(job), repairing};
}

export function groups(state) {
  const all = Object.values(state.jobs || {}).map(job => describe(job, state));
  const byDate = (a, b) => b.job.argument_date.localeCompare(a.job.argument_date) || b.job.created_at.localeCompare(a.job.created_at);
  const pick = name => all.filter(item => item.group === name).sort(byDate);
  return {action: pick('action'), active: pick('active'), publish: pick('publish'), waiting: pick('waiting'), done: pick('done')};
}

export function upcoming(state) {
  return Object.values(state.source_watches || {})
    .filter(w => !['found', 'expired'].includes(w.status))
    .sort((a, b) => (a.starts_at || '').localeCompare(b.starts_at || ''));
}

export const caseMeta = job => `${job.docket} · ${shortDate(job.argument_date)}`;
