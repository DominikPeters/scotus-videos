'use strict';
const $=id=>document.getElementById(id);
let csrf='',state,session,selectedJob='',busy=false,connectionPoll=null,connectionData=null,connectionLoginId='';
const bytes=value=>Uint8Array.from(atob(value.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));
const encoded=value=>btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
const date=value=>value ? new Date(value).toLocaleString() : '—';
function message(value){$('message').textContent=value;}
function transientMessage(value){message(value);setTimeout(()=>{if($('message').textContent===value)message('');},8000);}
async function api(action,data={},get=false){
  const response=await fetch(`api.php?action=${action}`,get?{credentials:'same-origin'}:{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(data)});
  const body=await response.json();
  if(!response.ok || !body.ok){const error=Error(body.error || 'Request failed');error.status=response.status;throw error;}
  return body.result;
}
async function passkey(register){
  const options=await api(register?'register_options':'login_options');
  options.publicKey.challenge=bytes(options.publicKey.challenge);
  if(register){
    options.publicKey.user.id=bytes(options.publicKey.user.id);
    for(const credential of options.publicKey.excludeCredentials||[])credential.id=bytes(credential.id);
  }else{for(const credential of options.publicKey.allowCredentials||[])credential.id=bytes(credential.id);}
  const credential=await navigator.credentials[register?'create':'get'](options);
  const response=credential.response;
  const payload={id:credential.id,clientDataJSON:encoded(response.clientDataJSON)};
  if(register)payload.attestationObject=encoded(response.attestationObject);
  else Object.assign(payload,{authenticatorData:encoded(response.authenticatorData),signature:encoded(response.signature)});
  const result=await api(register?'register':'login',payload);csrf=result.csrf;
}
async function initialize(){
  session=await api('session',{},true);csrf=session.csrf;
  const token=new URLSearchParams(location.hash.slice(1)).get('setup');
  if(token){history.replaceState(null,'',location.pathname);await api('bootstrap',{token});session.enrollment_allowed=true;}
  $('dashboard').hidden=!session.signed_in;$('logout').hidden=!session.signed_in;$('signin').hidden=session.signed_in;
  if(!session.signed_in){
    if(session.enrollment_allowed){$('signin-title').textContent='Create a passkey';$('signin-note').textContent='Register a passkey to access this dashboard.';$('signin-button').textContent='Create a passkey';message('');}
    else if(!session.initialized){$('signin-title').textContent='Setup required';$('signin-note').textContent='Open your one-time setup link to register the first passkey.';$('signin-button').hidden=true;message('');}
    else message('');
    return;
  }
  await refresh();message('');
  Promise.allSettled([secrets(),connectionStatus()]);
  const fragment=new URLSearchParams(location.hash.slice(1));
  if(fragment.has('connected')){const provider=fragment.get('connected');message(`${({youtube:'YouTube',github:'GitHub'})[provider]||'Account'} connected.`);history.replaceState(null,'',location.pathname);}
  else if(fragment.get('connection')==='failed'){message('Connection was not completed. Sign in again, or use the setup instructions below.');history.replaceState(null,'',location.pathname);}

}
function cell(text){const td=document.createElement('td');td.textContent=text;return td;}
function button(text,action){const b=document.createElement('button');b.textContent=text;b.onclick=()=>run(action,b);return b;}
function progress(job){return Object.values(job.stages).reduce((sum,s)=>sum+(s.status==='complete'?1:s.progress||0),0)/Object.keys(job.stages).length;}
function phaseDuration(stage){
  if(stage.status!=='complete')return '';
  const elapsed=Date.parse(stage.finished_at)-Date.parse(stage.started_at);
  if(!Number.isFinite(elapsed)||elapsed<0)return '';
  const seconds=Math.round(elapsed/1000),hours=Math.floor(seconds/3600),minutes=Math.floor(seconds%3600/60),remaining=seconds%60;
  return [hours?`${hours}h`:'',minutes?`${minutes}m`:'',remaining||!seconds?`${remaining}s`:''].filter(Boolean).join(' ');
}
function chunkProgress(stage){
  if(!stage.tasks?.length)return '';
  const counts={};for(const task of stage.tasks)counts[task.status]=(counts[task.status]||0)+1;
  return `${counts.complete||0}/${stage.tasks.length} chunks complete`+['running','pending','failed'].filter(status=>counts[status]).map(status=>`; ${counts[status]} ${status==='pending'?'waiting':status}`).join('');
}
function spotifyControls(job){
  const box=document.createElement('div');box.className='spotify-controls';
  if(!state.spotify_enabled||job.stages.upload.status!=='complete'||!job.stages.upload.result?.postprocessing_complete)return box;
  const item=job.spotify||{},status=item.status||'',labels={queued:'Transfer queued',waiting_episode:'Waiting for RSS episode',starting:'Starting transfer',uploading:`Uploading ${Math.round((item.progress||0)*100)}%`,uploaded:'Ready to publish',publish_queued:'Publication requested',publishing:'Spotify processing',published:'Published',needs_auth:'Reconnect required',failed:'Needs retry'};
  const command=async value=>{await api('spotify',{job:job.id,command:value});await refresh();};
  if(status)box.append(paragraph('Spotify: '+(labels[status]||status),'secondary'));
  if(!status)box.append(button('Transfer to Spotify',()=>command('transfer')));
  if(status==='uploaded')box.append(button('Publish on Spotify',()=>{if(confirm('Replace the audio-only player on this Spotify episode with the uploaded video? The RSS podcast stays unchanged.'))return command('publish');}));
  if(['failed','needs_auth'].includes(status)){
    if(item.error)box.append(paragraph(item.error,'note'));
    box.append(button('Retry Spotify transfer',()=>command('retry')));
    if(status==='needs_auth')box.append(button('Reconnect Spotify',()=>connect('spotify')));
    if(!item.upload_id){const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Choose Spotify episode';details.append(summary);const form=document.createElement('form');form.innerHTML='<label>Episode ID<input name="episode_id" required pattern="[A-Za-z0-9]{22}" maxlength="22"></label><button type="submit">Retry with this episode</button>';form.onsubmit=event=>{event.preventDefault();run(async()=>{await api('spotify',{job:job.id,command:'retry',episode_id:form.elements.episode_id.value});await refresh();},event.submitter);};details.append(form);box.append(details);}
  }
  if(/^[A-Za-z0-9]{22}$/.test(item.episode_id||''))box.append(externalLink('Open on Spotify',`https://open.spotify.com/episode/${item.episode_id}`));
  return box;
}
function render(){
  $('pipeline-status').textContent=state.paused?'Automatic work paused':'Automatic work enabled';$('pause').textContent=state.paused?'Resume automatic work':'Pause automatic work';
  const jobs=Object.values(state.jobs||{}).sort((a,b)=>b.created_at.localeCompare(a.created_at));$('empty').hidden=jobs.length>0;$('jobs').replaceChildren();
  for(const job of jobs){
    const row=document.createElement('tr'),name=cell(''),title=document.createElement('span'),docket=document.createElement('span');
    title.className='job-title';title.textContent=job.case_name;docket.className='secondary';docket.textContent=job.docket;
    const argumentDate=document.createElement('time');argumentDate.className='secondary job-date-mobile';argumentDate.dateTime=job.argument_date;argumentDate.textContent=job.argument_date;name.append(title,docket,argumentDate);
    const status=cell(({queued:'Queued',running:'Running',needs_review:'Needs review',failed:'Failed',cancelled:'Cancelled',complete:job.privacy==='public'?'Published':'Uploaded'})[job.status]||job.status),completed=Object.entries(job.stages).filter(([,s])=>['starting','running','failed'].includes(s.status));
    for(const [name,phase]of completed){const detail=document.createElement('div');detail.className='secondary';detail.textContent=name+(phase.error?`: ${phase.error.replace(/_/g,' ')}`:'');status.append(detail);}
    const p=cell(`${Math.round(progress(job)*100)}%`),bar=document.createElement('div'),fill=document.createElement('span');bar.className='progress';fill.style.width=`${progress(job)*100}%`;bar.append(fill);p.append(bar);
    const actions=cell('');actions.append(button('Details',()=>{selectedJob=selectedJob===job.id?'':job.id;render();}));
    if(job.status==='queued'){
      const start=button(job.run_requested?'Start requested':'Start',async()=>{await api('command',{command:'start',job:job.id});await refresh();});
      start.disabled=!!job.run_requested;start.title='Start this recording, even while automatic work is paused';actions.append(start);
    }
    if(['failed','cancelled'].includes(job.status))actions.append(button('Retry',async()=>{await api('command',{command:'retry',job:job.id});await refresh();}));
    else if(job.status!=='complete')actions.append(button('Cancel',async()=>{await api('command',{command:'cancel',job:job.id});await refresh();}));
    actions.append(spotifyControls(job));
    const dateCell=cell(job.argument_date);dateCell.className='job-date-column';row.append(name,dateCell,status,p,actions);$('jobs').append(row);
  }
  $('job-detail').replaceChildren();$('job-detail').hidden=!selectedJob;
  const job=state.jobs?.[selectedJob];
  if(job){const detail=document.createElement('div');detail.className='steps';for(const [name,s]of Object.entries(job.stages)){const p=document.createElement('p'),duration=phaseDuration(s);p.textContent=`${name}: ${s.status}${duration?` (${duration}${s.attempt>1?', latest attempt':''})`:s.status==='running'?` (${Math.round((s.progress||0)*100)}%)`:''}`;if(name==='render'&&s.tasks?.length)p.append(document.createTextNode(` — ${chunkProgress(s)}`));if(duration)p.title='Elapsed time from dispatch to completion, including worker startup';detail.append(p);if(s.result?.timings_seconds){const timings=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Assembly timings';timings.append(summary);const labels={chunks:'Download and verify chunks',audio:'Prepare audio',mux:'Join video and audio',check:'Verify output',save:'Save artifact'};for(const [key,seconds]of Object.entries(s.result.timings_seconds)){const value=Number(seconds);if(!Number.isFinite(value)||value<0)continue;const line=document.createElement('p');line.className='secondary';line.textContent=`${labels[key]||key}: ${value.toFixed(1)}s`;timings.append(line);}detail.append(timings);}}if(job.stages.upload.result?.video_url){const a=document.createElement('a');a.href=job.stages.upload.result.video_url;a.target='_blank';a.rel='noopener';a.textContent='Open video';detail.append(a);}$('job-detail').append(detail);}
  $('events').replaceChildren();for(const e of (state.events||[]).slice().reverse().slice(0,30)){const li=document.createElement('li'),time=document.createElement('time');time.textContent=date(e.at);li.append(time,document.createTextNode(e.message));$('events').append(li);}
  renderRecoveries();renderReviews();
}
function renderRecoveries(){
  const records=Object.values(state.recoveries||{}).sort((a,b)=>(a.status==='needs_input'?0:1)-(b.status==='needs_input'?0:1)||b.updated_at.localeCompare(a.updated_at));
  $('recovery-empty').hidden=records.length>0;
  const budget=state.repair_budget;
  $('repair-budget').textContent=budget?'Repair reservations: '+Object.entries(budget.days||{}).sort(([a],[b])=>b.localeCompare(a)).slice(0,2).map(([day,usd])=>`${day}: $${Number(usd).toFixed(2)} / $1`).join('; '):'Repair budget: $1 per day. Reservations use conservative runtime estimates.';
  const container=$('recoveries');
  // Preserve any in-progress answer while polling other recording progress.
  const signature=JSON.stringify(records);
  if(container.dataset.signature===signature)return;
  const answers=new Map([...container.querySelectorAll('form')].map(form=>[form.dataset.question,{text:form.elements.text.value,choice:form.elements.choice.value}]));
  const openLogs=new Set([...container.querySelectorAll('article>details[open]')].map(details=>details.parentElement.id));
  const historyOpen=$('resolved-recoveries')?.open||false;
  container.dataset.signature=signature;container.replaceChildren();
  const history=document.createElement('details'),historySummary=document.createElement('summary');history.id='resolved-recoveries';history.open=historyOpen;history.append(historySummary);let resolvedCount=0;
  for(const rec of records){
    const box=document.createElement('article');box.className='recovery';box.id='recovery-'+rec.id;
    const heading=document.createElement('h3'),status=document.createElement('p');
    heading.textContent=`${state.jobs?.[rec.job]?.case_name||rec.job} — ${rec.stage}`;
    const phase=state.jobs?.[rec.job]?.stages?.[rec.stage],phasePassed=phase?.status==='complete'&&phase.recovery_id===rec.id;
    const labels={repaired:'Resolved',waiting_for_stage:'Waiting for the phase retry',waiting_for_tests:'Waiting for isolated checks; resumes automatically',waiting_for_resource:'Waiting for resources',needs_input:'Needs your input',unresolved:'Needs attention'};
    status.className='note';status.textContent=`${phasePassed&&rec.status==='running'?'Phase completed; finishing recovery log':labels[rec.status]||rec.status.replace(/_/g,' ')} · ${rec.turns} repair ${rec.turns===1?'turn':'turns'}`;
    box.append(heading,status);
    if(rec.resolution)box.append(paragraph(rec.resolution));
    if(rec.finished_at)box.append(paragraph('Completed '+date(rec.finished_at),'note'));
    if(!phasePassed&&['unresolved','waiting_for_resource'].includes(rec.status))box.append(button('Resume recovery',async()=>{await api('recovery_command',{recovery:rec.id,command:'resume'});await refresh();}));
    if(!phasePassed&&['queued','starting','running','needs_input','waiting_for_resource','waiting_for_stage','waiting_for_tests'].includes(rec.status))box.append(button('Stop recovery',async()=>{await api('recovery_command',{recovery:rec.id,command:'stop'});await refresh();}));
    for(const question of Object.values(rec.questions||{}).reverse().sort((a,b)=>(a.status==='pending'?0:1)-(b.status==='pending'?0:1))){
      const text=document.createElement('p');text.textContent=question.message;box.append(text);
      if(question.status==='dismissed'||(phasePassed&&question.status==='pending')){box.append(paragraph('No longer needed: '+(question.reason||'this phase completed successfully.'),'note'));continue;}
      if(question.status!=='pending'){const answer=document.createElement('p');answer.className='note';answer.textContent='Answered: '+(question.answer.text||question.answer.choice);box.append(answer);continue;}
      const form=document.createElement('form');form.dataset.question=rec.id+':'+question.id;
      const select=document.createElement('select');select.name='choice';select.setAttribute('aria-label','Answer choice');
      const blank=document.createElement('option');blank.value='';blank.textContent='Choose an answer or write below';select.append(blank);
      for(const option of question.options||[]){const item=document.createElement('option');item.value=option.id;item.textContent=(option.actor==='worker'?'Codex: ':option.actor==='operator'?'You: ':'Reply: ')+option.label;select.append(item);}
      const effect=paragraph('Your answer resumes Codex; choosing an option does not itself run a command.','note');
      const showEffect=()=>{const choice=(question.options||[]).find(o=>o.id===select.value);effect.textContent=choice?((choice.actor==='operator'?'Your action: ':choice.actor==='worker'?'Codex’s next step: ':'Proposed next step: ')+choice.private_effect):'Your answer resumes Codex; choosing an option does not itself run a command.';};
      select.addEventListener('change',showEffect);
      const input=document.createElement('textarea');input.name='text';input.rows=3;input.maxLength=4000;input.setAttribute('aria-label','Additional answer');
      const saved=answers.get(form.dataset.question);if(saved){select.value=saved.choice;input.value=saved.text;}showEffect();
      const submit=document.createElement('button');submit.type='submit';submit.textContent='Send answer';submit.disabled=rec.status!=='needs_input';
      form.append(select,effect,input,submit);form.onsubmit=event=>{event.preventDefault();run(async()=>{await api('recovery_answer',{recovery:rec.id,question:question.id,revision:rec.input_revision,choice:select.value,text:input.value});await refresh();message('Answer saved. Recovery queued.');},submit);};box.append(form);
    }
    const details=document.createElement('details'),summary=document.createElement('summary'),log=document.createElement('ol');
    summary.textContent='Recovery log';log.className='recovery-log';details.open=rec.status==='needs_input'||openLogs.has(box.id);
    for(const entry of (rec.log||[]).slice().reverse()){const item=document.createElement('li'),when=document.createElement('time'),kind=document.createElement('span'),body=document.createElement('p');when.textContent=date(entry.at);kind.textContent=' · '+entry.kind;body.textContent=entry.message;item.append(when,kind,body);log.append(item);}
    details.append(summary,log);box.append(details);
    if(['repaired','cancelled'].includes(rec.status)){history.append(box);resolvedCount++;}else container.append(box);
  }
  if(resolvedCount){historySummary.textContent=`Resolved recoveries (${resolvedCount})`;container.append(history);}
  const requested=new URLSearchParams(location.hash.slice(1)).get('recovery');
  if(requested){const target=$('recovery-'+requested);if(target){if(target.closest('#resolved-recoveries'))history.open=true;target.querySelector('details').open=true;target.scrollIntoView({block:'nearest'});}}
}

const previewUrls=new Map(),previewPending=new Map();
let previewActive=0;const previewQueue=[];
async function previewSlot(task){
  if(previewActive>=2)await new Promise(resolve=>previewQueue.push(resolve));
  previewActive++;try{return await task();}finally{previewActive--;previewQueue.shift()?.();}
}
async function preview(image,job,kind,person='',candidate='',variant=''){
  const recording=state.jobs?.[job]||Object.values(state.jobs||{}).find(j=>j.id===job);
  const selected=recording?.review?.photos?.[person]?.candidates?.find(c=>c.id===candidate);
  const uri=kind==='photo'?(variant==='source'?(selected?.source_preview_uri||selected?.preview_uri):selected?.preview_uri):kind==='card'?(recording?.review.cards?.find(c=>c.id===candidate)?.[variant==='frame'?'frame_uri':'card_uri']):kind==='thumbnail'?recording?.stages.plan.result?.thumbnail_preview_uri:recording?.stages.render.tasks?.[0]?.result?.preview_uri;
  const key=[job,kind,person,candidate,variant,uri].join(':');image.dataset.previewKey=key;
  try{
    if(!previewUrls.has(key)){
      if(!previewPending.has(key))previewPending.set(key,previewSlot(async()=>{
        let value;try{value=await api('asset_data',{job,kind,person,candidate,variant});}
        catch(error){if(error.status!==503)throw error;await new Promise(resolve=>setTimeout(resolve,500));value=await api('asset_data',{job,kind,person,candidate,variant});}
        previewUrls.set(key,URL.createObjectURL(new Blob([Uint8Array.from(atob(value.data),c=>c.charCodeAt(0))],{type:value.mime})));
      }).finally(()=>previewPending.delete(key)));
      await previewPending.get(key);
    }
    if(image.dataset.previewKey===key)image.src=previewUrls.get(key);
  }catch{image.alt='Preview unavailable';}
}
function paragraph(text,className=''){const p=document.createElement('p');p.textContent=text;p.className=className;return p;}
function reviewHeading(text){const heading=document.createElement('h3');heading.className='review-heading';heading.textContent=text;return heading;}
function publicText(html){const documentValue=new DOMParser().parseFromString(html||'','text/html');return documentValue.body.textContent;}
function photoFeedback(job,person,candidate,pending,drafts){
  const revise=document.createElement('details'),summary=document.createElement('summary');summary.textContent=candidate?'Reject or revise':'Request an image';revise.append(summary);
  const form=document.createElement('form');form.className='photo-feedback';form.dataset.key=job.id+':'+person+':'+(candidate?.id||'missing');
  form.innerHTML='<label>Action<select name="action"><option value="different">Find different image</option><option value="recrop">Recrop</option><option value="synthetic">Switch to synthetic picture</option></select></label><label>Hint or reason (optional)<textarea name="hint" rows="3" maxlength="2000"></textarea></label><p class="note">Synthetic alternatives use initials or a verified firm/agency logo.</p><button type="submit">Send to Codex</button>';
  if(candidate?.kind!=='photo')form.querySelector('option[value="recrop"]').remove();
  const draft=drafts.get(form.dataset.key);if(draft){form.elements.action.value=draft.action;form.elements.hint.value=draft.hint;}
  form.querySelector('button').disabled=pending||job.stages.plan.status!=='pending'||['starting','running'].includes(job.stages.enrich.status);
  form.onsubmit=event=>{event.preventDefault();run(async()=>{await api('review',{job:job.id,revision:job.review.revision,command:'photo_request',person,candidate:candidate?.id||'',action:form.elements.action.value,hint:form.elements.hint.value});await refresh();},event.submitter);};revise.append(form);return revise;
}
function renderReviews(){
  const reviewPriority=job=>job.review.cards?.length&&job.cards_approved_revision!==job.review.card_revision?0:Object.entries(job.review.photos||{}).some(([person])=>!job.approved_photos?.[person])?0:job.stages.upload.status==='complete'&&job.privacy==='unlisted'?1:2;
  const archived=job=>job.privacy==='public'||job.status==='cancelled';
  const jobs=Object.values(state.jobs||{}).filter(job=>job.review).sort((a,b)=>reviewPriority(a)-reviewPriority(b)||(b.updated_at||b.created_at).localeCompare(a.updated_at||a.created_at));
  $('review-empty').hidden=jobs.some(job=>!archived(job));
  $('review-empty').textContent='Nothing needs review.';
  const container=$('reviews'),signature=JSON.stringify(jobs.map(job=>[job.id,job.review,job.approved_photos,job.selected_title,job.cards_approved_revision,job.card_selections,job.privacy,job.stages.upload.status,job.stages.upload.result,job.video_actions,job.asset_publication,job.stages.plan.result,job.stages.render.tasks?.[0]?.result?.preview_uri,job.stages.enrich.status,Object.values(job.photo_requests||{}).map(r=>[r.id,r.status,r.error]) ]));
  if(container.dataset.signature===signature)return;
  const openIds=new Set([...container.querySelectorAll('details[open]')].map(item=>item.id));
  const titleDrafts=new Map([...container.querySelectorAll('.title-editor')].map(form=>[form.dataset.job,{value:form.elements.title.value,dirty:form.dataset.dirty==='true'}]));
  const cardDrafts=new Map([...container.querySelectorAll('.card-review')].map(form=>[form.dataset.revision,{dirty:form.dataset.dirty==='true',values:Object.fromEntries([...form.querySelectorAll('input[type=checkbox]')].map(input=>[input.name,input.checked]))}]));
  const drafts=new Map([...container.querySelectorAll('.photo-feedback')].map(form=>[form.dataset.key,{hint:form.elements.hint.value,action:form.elements.action.value}]));
  container.dataset.signature=signature;container.replaceChildren();
  const requested=new URLSearchParams(location.hash.slice(1)).get('review');
  const history=document.createElement('details'),historySummary=document.createElement('summary');history.id='review-history';history.open=openIds.has(history.id);history.append(historySummary);let historyCount=0;
  for(const job of jobs){
    const review=job.review,box=document.createElement('details'),heading=document.createElement('summary');box.id='review-'+review.id;
    box.open=openIds.has(box.id)||(!archived(job)&&reviewPriority(job)<=1)||requested===review.id;
    box.className='review-card';
    const name=document.createElement('span');name.className='review-name';name.textContent=job.case_name;
    const subtitle=document.createElement('span');subtitle.className='review-status';
    const missing=Object.entries(review.photos||{}).filter(([person])=>!job.approved_photos?.[person]).length;
    const cardsPending=review.cards?.length&&job.cards_approved_revision!==review.card_revision;
    subtitle.textContent=job.docket+' · '+(cardsPending?`${review.cards.length} cards to review${missing?` · ${missing} images to approve`:''}`:(archived(job)?(job.privacy==='public'?'Published':'Cancelled'):missing?`${missing} image${missing===1?'':'s'} to approve`:job.stages.upload.status==='complete'?(job.privacy==='unlisted'?'Ready to publish':'Uploaded'):'Images approved · processing'));
    heading.append(name,subtitle);box.append(heading);
    const upload=job.stages.upload.result;
    const actions=document.createElement('div');actions.className='review-actions';
    if(upload?.video_url)actions.append(externalLink('Open on YouTube',upload.video_url));
    if(/^[A-Za-z0-9_-]{11}$/.test(upload?.video_id||''))actions.append(externalLink('YouTube Studio',`https://studio.youtube.com/video/${upload.video_id}/edit`));
    if(job.stages.upload.status==='complete'&&upload?.postprocessing_complete&&job.privacy==='unlisted'){
      const pending=Object.values(job.video_actions||{}).some(action=>action.kind==='publish'&&['queued','starting','running'].includes(action.status));
      const publish=button(pending?'Publication requested':'Publish video',async()=>{await api('review',{job:job.id,revision:review.revision,command:'publish'});await refresh();});publish.disabled=pending;actions.prepend(publish);
    }
    if(actions.childNodes.length)box.append(actions);
    if(review.cards?.length){
      const form=document.createElement('form');form.className='card-review';form.dataset.revision=review.card_revision;
      const h=document.createElement('h3');h.textContent='Annotation cards';form.append(h);
      const draft=cardDrafts.get(review.card_revision),frozen=job.stages.plan.status!=='pending';
      for(const card of review.cards){
        const item=document.createElement('article');item.className='annotation-review';
        const label=document.createElement('label'),toggle=document.createElement('input');toggle.type='checkbox';toggle.name=card.id;toggle.checked=draft?.dirty?draft.values[card.id]:(job.card_selections?.[card.id]??card.recommended);toggle.disabled=frozen;toggle.onchange=()=>form.dataset.dirty='true';
        const text=document.createElement('span');text.textContent='Show this card';label.append(toggle,text);item.append(label);
        const image=document.createElement('img');image.className='annotation-preview';image.alt='Rendered annotation card';item.append(image);Object.assign(image.dataset,{assetJob:job.id,assetKind:'card',assetCandidate:card.id});
        item.append(paragraph(`${Math.floor(card.start/60)}:${String(Math.floor(card.start%60)).padStart(2,'0')}–${Math.floor(card.end/60)}:${String(Math.floor(card.end%60)).padStart(2,'0')} · Sol proposes ${card.recommended?'showing':'hiding'} this card`,'note'),paragraph(card.reason,'note'));
        const evidence=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Full frame and sources';evidence.append(summary);const frame=document.createElement('img');frame.className='frame-preview';frame.alt='Annotation in the full video frame';evidence.append(frame);evidence.addEventListener('toggle',()=>{if(evidence.open)preview(frame,job.id,'card','',card.id,'frame');});
        for(const source of card.sources||[]){evidence.append(externalLink('Source · PDF page '+source.page,source.url),paragraph(source.quote,'note'));}item.append(evidence);form.append(item);
      }
      const save=document.createElement('button');save.type='submit';save.textContent=cardsPending?'Approve card selections':'Update card selections';save.disabled=frozen;form.append(save);
      form.onsubmit=event=>{event.preventDefault();run(async()=>{const selections=Object.fromEntries([...form.querySelectorAll('input[type=checkbox]')].map(input=>[input.name,input.checked]));await api('review',{job:job.id,revision:review.revision,command:'cards',selections});form.dataset.dirty='false';await refresh();},event.submitter);};box.append(form);
    }
    const titleBlock=document.createElement('div');titleBlock.className='current-title';titleBlock.append(paragraph(job.selected_title||review.titles[0]?.title||job.title,'candidate-title'));box.append(titleBlock);
    const editing=document.createElement('details'),editSummary=document.createElement('summary');editing.id=box.id+'-edit-title';editing.open=openIds.has(editing.id);editSummary.textContent='Edit title';editing.append(editSummary);
    const editor=document.createElement('form');editor.className='title-editor';editor.dataset.job=job.id;
    const label=document.createElement('label');label.textContent='Video title';const input=document.createElement('textarea');input.name='title';input.rows=2;input.maxLength=100;input.required=true;input.value=job.selected_title||review.titles[0]?.title||job.title;
    const draft=titleDrafts.get(job.id);if(draft?.dirty){input.value=draft.value;editor.dataset.dirty='true';}label.append(input);
    const count=paragraph('','note');const updateCount=()=>count.textContent=`${[...input.value].length}/100 characters`;updateCount();input.addEventListener('input',()=>{editor.dataset.dirty='true';updateCount();});
    const save=document.createElement('button');save.type='submit';save.textContent=upload?.video_id?'Update on YouTube':'Save title';
    const titlePending=Object.values(job.video_actions||{}).some(a=>a.kind==='title'&&['queued','starting','running'].includes(a.status));
    save.disabled=titlePending||['starting','running'].includes(job.stages.upload.status)||!!(upload?.video_id&&!upload.postprocessing_complete);
    editor.append(label,count,save);editor.onsubmit=event=>{event.preventDefault();run(async()=>{await api('review',{job:job.id,revision:review.revision,command:'title',title:input.value});editor.dataset.dirty='false';await refresh();transientMessage(upload?.video_id?'Title update requested.':'Title saved.');},event.submitter);};editing.append(editor);box.append(editing);
    const titles=document.createElement('details'),titleSummary=document.createElement('summary');titles.id=box.id+'-titles';titles.open=openIds.has(titles.id);titleSummary.textContent='Title alternatives and reasoning';titles.append(titleSummary);box.append(titles);
    for(const [index,candidate] of review.titles.entries()){
      const row=document.createElement('div');row.className='title-choice';row.append(paragraph(candidate.title,'candidate-title'));
      if(candidate.private_reason)row.append(paragraph(candidate.private_reason,'note'));
      const selected=(job.selected_title||review.titles[0]?.title)===candidate.title;
      const choice=button(selected?'Selected':'Use this title',async()=>{await api('review',{job:job.id,revision:review.revision,command:'title',index});await refresh();});choice.disabled=titlePending||['starting','running'].includes(job.stages.upload.status);if(selected)row.append(paragraph('Selected title','selection-status'));else row.append(choice);titles.append(row);
    }
    const metadata=document.createElement('details'),summary=document.createElement('summary');metadata.id=box.id+'-metadata';metadata.open=openIds.has(metadata.id);summary.textContent='Case description and private notes';metadata.append(summary);
    metadata.append(paragraph(publicText(review.description.facts_of_the_case)),paragraph(publicText(review.description.question)));
    for(const note of review.private_notes||[])metadata.append(paragraph(note,'note'));
    for(const [field,record] of Object.entries(review.provenance||{})){metadata.append(paragraph(field.replace(/_/g,' ')+': '+record.method,'note'));for(const source of record.sources||[])if(/^https:\/\//.test(source.url||''))metadata.append(externalLink(source.title||'Source',source.url));}
    box.append(metadata);
    const approvedImages=document.createElement('details'),approvedSummary=document.createElement('summary');approvedImages.id=box.id+'-approved';approvedImages.open=openIds.has(approvedImages.id);approvedSummary.textContent='Approved images';approvedImages.append(approvedSummary);let approvedCount=0;
    if(missing)box.append(reviewHeading('Images to approve'));
    for(const [person,item] of Object.entries(review.photos||{})){
      const photos=document.createElement('div');photos.className='portrait-review';const name=document.createElement('h4');name.textContent=item.name;photos.append(name);
      const evidence=document.createElement('details'),evidenceLabel=document.createElement('summary');evidenceLabel.textContent='Identity and research notes';evidence.append(evidenceLabel,paragraph(item.identity_evidence||'','note'));photos.append(evidence);const choices=document.createElement('div');choices.className='portrait-options';
      for(const note of item.private_notes||[])evidence.append(paragraph(note,'note'));
      const requests=Object.values(job.photo_requests||{}).filter(r=>r.person===person).reverse(),pending=requests.some(r=>['queued','starting','running'].includes(r.status));
      for(const request of requests){
        photos.append(paragraph('Codex photo request: '+request.action+' — '+request.status,'note'));
        if(request.error)photos.append(paragraph(request.error,'note'));
        if(request.status==='failed')photos.append(button('Retry photo request',async()=>{await api('review',{job:job.id,revision:review.revision,command:'photo_retry',request:request.id});await refresh();}));
      }
      for(const candidate of item.candidates||[]){
        const card=document.createElement('div'),image=document.createElement('img');image.alt=item.name;image.loading='lazy';card.append(image);
        image.dataset.assetJob=job.id;image.dataset.assetKind='photo';image.dataset.assetPerson=person;image.dataset.assetCandidate=candidate.id;
        card.append(paragraph(candidate.kind||'photo','note'));
        const view=button('Show full image',async()=>{const full=image.classList.toggle('full-image');view.textContent=full?'Show square preview':'Show full image';await preview(image,job.id,'photo',person,candidate.id,full?'source':'');});card.append(view);
        if(candidate.crop_note)card.append(paragraph(candidate.crop_note,'note'));
        if(candidate.rejected)card.append(paragraph('Rejected','note'));
        for(const [label,url] of [['Image source',candidate.source_url],['Identity source',candidate.identity_source_url]])if(url&&/^https:\/\//.test(url))card.append(externalLink(label,url));
        if(candidate.private_note)card.append(paragraph(candidate.private_note,'note'));
        const approved=job.approved_photos?.[person]?.id===candidate.id;
        const choose=button(approved?'Approved':'Approve image',async()=>{await api('review',{job:job.id,revision:review.revision,command:'photo',person,candidate:candidate.id});await refresh();});choose.disabled=candidate.rejected||pending||job.stages.plan.status!=='pending'||(candidate.kind==='photo'&&candidate.origin!=='curated_cache'&&!candidate.square_asset);if(approved)card.append(paragraph('Approved','selection-status'));else card.append(choose);
        card.append(photoFeedback(job,person,candidate,pending,drafts));choices.append(card);
      }
      photos.append(choices);
      if(!item.candidates?.length)photos.append(paragraph('An image is required before this recording can continue.'),photoFeedback(job,person,null,pending,drafts));
      const more=document.createElement('details'),label=document.createElement('summary');label.textContent='Add an image';more.append(label);
      const form=document.createElement('form');form.innerHTML='<label>Image<input name="image" type="file" accept="image/*" required></label><label>Type<select name="kind"><option value="photo">Photo</option><option value="logo">Firm or agency logo</option><option value="initials">Initials or other graphic</option></select></label><label>Source link<input name="source_url" type="url" placeholder="https://…"></label><label>Private note<input name="note" maxlength="2000"></label><button type="submit">Add candidate</button>';
      form.onsubmit=event=>{event.preventDefault();run(async()=>{const values=new FormData(form),image=await smallImage(values.get('image'));await api('photo_add',{job:job.id,revision:review.revision,person,image,kind:values.get('kind'),source_url:values.get('source_url'),note:values.get('note')});await refresh();},event.submitter);};more.append(form);photos.append(more);if(job.approved_photos?.[person]){approvedImages.append(photos);approvedCount++;}else box.append(photos);
    }
    if(missing)box.append(titleBlock,editing,titles,metadata);
    if(approvedCount){approvedSummary.textContent=`Approved images (${approvedCount})`;box.append(approvedImages);}
    if(job.stages.plan.result?.thumbnail_preview_uri||job.stages.render.tasks?.[0]?.result?.preview_uri){
      const previews=document.createElement('details'),label=document.createElement('summary');previews.id=box.id+'-previews';previews.open=openIds.has(previews.id);label.textContent='Thumbnail and rendered frame';previews.append(label);
      for(const [kind,uri,alt]of [['thumbnail',job.stages.plan.result?.thumbnail_preview_uri,'Video thumbnail'],['frame',job.stages.render.tasks?.[0]?.result?.preview_uri,'Rendered frame']]){
        if(!uri)continue;const image=document.createElement('img');image.className='video-preview';image.alt=alt;image.dataset.assetJob=job.id;image.dataset.assetKind=kind;previews.append(reviewHeading(alt),image);
      }box.append(previews);
    }
    for(const action of Object.values(job.video_actions||{}))if(action.status!=='complete'){box.append(paragraph((action.kind==='publish'?'Publication':'Title update')+': '+action.status,'note'));if(action.status==='failed')box.append(button('Retry '+(action.kind==='publish'?'publication':'title update'),async()=>{const index=review.titles.findIndex(c=>c.title===action.title);await api('review',{job:job.id,revision:review.revision,command:action.kind==='publish'?'publish':'title',...(action.kind==='title'?{title:action.title}:{index})});await refresh();}));}
    for(const result of job.asset_publication?.results||[])if(result.url)approvedImages.append(externalLink('Portrait commit on GitHub',result.url));
    if(job.asset_publication?.status==='failed')approvedImages.append(button('Retry portrait commit',async()=>{await api('review',{job:job.id,revision:review.revision,command:'asset_retry'});await refresh();}));
    if(!approvedCount&&approvedImages.childNodes.length>1)box.append(approvedImages);
    if(archived(job)){history.append(box);historyCount++;if(requested===review.id)history.open=true;}else container.append(box);
  }
  if(historyCount){historySummary.textContent=`Completed reviews (${historyCount})`;container.append(history);}
  const loadVisible=()=>{for(const image of container.querySelectorAll('img[data-asset-job]')){
    let closed=false;for(let parent=image.parentElement;parent;parent=parent.parentElement)if(parent.tagName==='DETAILS'&&!parent.open){closed=true;break;}
    if(closed||!image.getClientRects().length||image.dataset.previewStarted)continue;
    image.dataset.previewStarted='true';preview(image,image.dataset.assetJob,image.dataset.assetKind,image.dataset.assetPerson||'',image.dataset.assetCandidate||'');
  }};
  if(container.previewListener)container.removeEventListener('toggle',container.previewListener,true);
  container.previewListener=loadVisible;container.addEventListener('toggle',loadVisible,true);loadVisible();
}
async function smallImage(file){
  if(!file||!file.size)throw Error('Choose an image.');
  // Resize before transfer; only a small portrait travels over the metered connection.
  const bitmap=await createImageBitmap(file),canvas=document.createElement('canvas');
  const scale=Math.min(1,1024/Math.max(bitmap.width,bitmap.height));canvas.width=Math.round(bitmap.width*scale);canvas.height=Math.round(bitmap.height*scale);
  const context=canvas.getContext('2d');context.fillStyle='#fff';context.fillRect(0,0,canvas.width,canvas.height);context.drawImage(bitmap,0,0,canvas.width,canvas.height);bitmap.close();
  for(const quality of [.9,.8,.65,.5]){const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',quality));if(blob.size<=131072){const value=new Uint8Array(await blob.arrayBuffer()),parts=[];for(let i=0;i<value.length;i+=32768)parts.push(String.fromCharCode(...value.subarray(i,i+32768)));return btoa(parts.join(''));}}
  throw Error('The resized image is too large. Choose a smaller image.');
}
async function refresh(clear=true){const value=await api('state',{revision:state?._revision});if(!value._unchanged){state=value;render();}if(clear)message('');}
async function secrets(){
  try{
    connectionData=await api('secret_status');
    $('cloud-status').textContent=connectionData.workers_enabled?'Cloud workers enabled.':'Cloud connected. Video workers are not enabled yet.';
    $('secrets').replaceChildren();
    for(const [name,s]of Object.entries(connectionData.credentials)){
      const tr=document.createElement('tr'),actions=cell('');
      actions.append(button(name==='spotify'?'Reconnect Spotify':name==='youtube'?'Sign in to YouTube':name==='codex'?'Sign in to Codex':s.configured?'Check GitHub connection':'Connect GitHub',()=>connect(name)));
      tr.append(cell(({youtube:'YouTube',codex:'Codex',github:'GitHub',spotify:'Spotify'})[name]),cell(s.configured?'Saved':s.app_created?'App created; installation needed':'Not configured'),cell(date(s.updated_at)),actions);$('secrets').append(tr);
    }
  }catch(error){$('cloud-status').textContent=error.message;}
}
function guide(title,paragraph,provider=''){
  if($('credentials-details'))$('credentials-details').open=true;
  const box=$('connection-guide');box.hidden=false;box.replaceChildren();
  box.dataset.provider=provider;
  const heading=document.createElement('h2'),p=document.createElement('p');heading.textContent=title;p.textContent=paragraph;box.append(heading,p);return box;
}
function externalLink(label,url){const a=document.createElement('a');a.textContent=label;a.href=url;a.target='_blank';a.rel='noopener';return a;}
async function connect(provider){
  if(provider==='spotify'){
    const box=guide('Reconnect Spotify','Paste the sp_dc and sp_key cookies from your signed-in Spotify session. The cloud exchanges them for a renewable token and removes the cookies.','spotify');
    const form=document.createElement('form');form.innerHTML='<label>sp_dc<input name="sp_dc" type="password" autocomplete="off" required></label><label>sp_key<input name="sp_key" type="password" autocomplete="off" required></label><button type="submit">Save Spotify sign-in</button>';
    form.onsubmit=event=>{event.preventDefault();run(async()=>{await api('secret_replace',{name:'spotify',value:{sp_dc:form.elements.sp_dc.value,sp_key:form.elements.sp_key.value}});form.reset();await api('spotify_probe');box.hidden=true;await secrets();transientMessage('Spotify connected.');},event.submitter);};box.append(form);box.scrollIntoView({block:'nearest'});return;
  }
  if(provider==='youtube'&&!connectionData?.youtube_client_configured){$('credential-import-details').open=true;$('secret-form').elements.name.value='youtube_client';$('credential-import-details').scrollIntoView({block:'nearest'});message('Import a Google Web application client with redirect URI '+new URL('oauth-callback.php?provider=youtube',location.href).href);return;}
  if(provider==='codex'){
    if(!connectionData?.codex_login_enabled)throw Error('The cloud sign-in helper is not deployed yet.');
    const result=await api('connect_start',{provider});connectionLoginId=result.id;
    guide('Sign in to Codex','Waiting for Cloud Run to start the sign-in helper.','codex');startConnectionPoll();await connectionStatus();return result;
  }
  if(provider==='github'){
    const box=guide('Connect GitHub','Create a private GitHub app and select the repositories it should access, including DominikPeters/scotus-videos. This grants Contents read and write permission. The video publisher uses a token scoped to scotus-videos.');
    box.append(button('Continue on GitHub',async()=>{
      const result=await api('connect_start',{provider});
      if(result.form_url){
        const form=document.createElement('form');form.method='POST';form.action=result.form_url;
        const input=document.createElement('input');input.type='hidden';input.name='manifest';input.value=JSON.stringify(result.manifest);form.append(input);document.body.append(form);form.submit();
      }else if(result.install_url){
        const pending=guide('Install the GitHub app','Open GitHub and select the repositories you want to connect, including DominikPeters/scotus-videos. Return here afterwards to check the connection.');
        pending.append(externalLink('Open GitHub installation',result.install_url),button('Check installation',async()=>{await api('github_install');await secrets();guide('GitHub connected','The image publisher can now use short-lived tokens for this repository.');}));
      }else location.assign(result.url);
    }));return;
  }
  const result=await api('connect_start',{provider});location.assign(result.url);
}
function startConnectionPoll(){if(connectionPoll)return;connectionPoll=setInterval(()=>{if(!busy)run(connectionStatus);},3000);}
async function connectionStatus(){
  const login=await api('connect_status');
  if(!login){
    if(connectionLoginId){clearInterval(connectionPoll);connectionPoll=null;connectionLoginId='';guide('Codex sign-in ended','This dashboard session no longer has an active sign-in request. Choose Sign in to Codex to start again.');}
    return;
  }
  const wasActive=connectionLoginId===login.id;
  if(login.status==='starting'){
    connectionLoginId=login.id;
    const elapsed=Math.max(0,Math.floor((Date.now()-Date.parse(login.created_at))/1000));
    const waiting=Number.isFinite(elapsed)?` Waiting ${Math.floor(elapsed/60)}m ${elapsed%60}s.`:'';
    const box=guide('Sign in to Codex','Waiting for Cloud Run to start the sign-in helper. Container startup can take a couple of minutes.'+waiting,'codex');
    box.append(button('Cancel sign-in',async()=>{await api('connect_cancel');await connectionStatus();}));startConnectionPoll();return;
  }
  if(login.status==='pending'){
    connectionLoginId=login.id;
    const box=guide('Sign in to Codex','Open the OpenAI sign-in page and enter this one-time code. The dashboard will save the cloud login when you finish.','codex');
    const code=document.createElement('code');code.className='device-code';code.textContent=login.user_code;box.append(code,externalLink('Open OpenAI sign-in',login.verification_url),button('Cancel sign-in',async()=>{await api('connect_cancel');await connectionStatus();}));
    const note=document.createElement('p');note.className='note';note.textContent='If device login is unavailable, enable it in your ChatGPT security settings. This creates a separate login for the cloud worker.';box.append(note);startConnectionPoll();return;
  }
  clearInterval(connectionPoll);connectionPoll=null;
  connectionLoginId='';
  if(login.status==='complete'){
    if($('connection-guide').dataset.provider==='codex'){$('connection-guide').hidden=true;$('connection-guide').replaceChildren();}
    if(wasActive){transientMessage('Codex connected.');await secrets();}
  }else if(['failed','expired'].includes(login.status)&&wasActive){guide('Codex sign-in ended','Sign in again to retry. If device login is unavailable, enable it in ChatGPT security settings or import a separate cloud auth.json file.','codex');}
  else if(login.status==='cancelled'&&$('connection-guide').dataset.provider==='codex'){$('connection-guide').hidden=true;}
}
async function run(action,control=null){
  if(busy)return;busy=true;
  const wasDisabled=control?.disabled;
  if(control){
    control.disabled=true;control.setAttribute('aria-busy','true');document.body.dataset.actionBusy='true';
    $('action-label').textContent=control.textContent+'…';$('action-status').hidden=false;
  }
  try{await action();}catch(error){message(error.name==='NotAllowedError'?'Passkey request cancelled or timed out.':error.message);}
  finally{
    busy=false;
    if(control){control.removeAttribute('aria-busy');if(control.isConnected)control.disabled=wasDisabled;delete document.body.dataset.actionBusy;$('action-status').hidden=true;}
  }
}
$('signin-button').onclick=()=>run(async()=>{await passkey(session.enrollment_allowed);await initialize();},$('signin-button'));
$('add-passkey').onclick=()=>run(async()=>{await passkey(true);message('Passkey added.');},$('add-passkey'));
$('logout').onclick=()=>run(async()=>{await api('logout');location.reload();},$('logout'));
$('refresh').onclick=()=>run(refresh,$('refresh'));
$('pause').onclick=()=>run(async()=>{await api('command',{command:state.paused?'resume':'pause'});await refresh();},$('pause'));
$('dispatch').onclick=()=>run(async()=>{const result=await api('dispatch');await refresh();message(result.message||'Work checked.');},$('dispatch'));
$('queue-form').onsubmit=event=>{event.preventDefault();run(async()=>{const form=event.target;await api('enqueue',Object.fromEntries(new FormData(form)));form.reset();await refresh();},event.submitter);};
$('secret-form').onsubmit=event=>{event.preventDefault();run(async()=>{const form=event.target,data=new FormData(form),file=data.get('file'),name=data.get('name');if(file.size>(name==='youtube_client'?65536:131072))throw Error('Credential file is too large.');const value=JSON.parse(await file.text());if(name==='youtube_client'){const uri=new URL('oauth-callback.php?provider=youtube',location.href).href;if(!value.web?.redirect_uris?.includes(uri))throw Error(`Use a Web application client with redirect URI ${uri}`);await api('youtube_client_replace',{value});}else await api('secret_replace',{name,value});form.reset();await secrets();message('Credential saved.');},event.submitter);};
initialize().catch(error=>message(error.message));
setInterval(()=>{if(session?.signed_in&&!busy)run(()=>refresh(false));},15000);
