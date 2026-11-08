import {h,link,clock} from './dom.js';
import {api} from './api.js';
import {block,button,disclosure,draft,drafts,submitForm} from './ui.js';
const transcripts=new Map();
const forms=new Map();

export function clipsBlock(job){
 if(!job.stages.plan.result?.bundle_uri&&!Object.keys(job.clips||{}).length)return null;
 const prefix=job.id+'-clip-';
 function buildForm(){
 const start=draft(prefix+'start',h('input',{type:'text',placeholder:'mm:ss',required:true,inputmode:'decimal'}));
 const end=draft(prefix+'end',h('input',{type:'text',placeholder:'mm:ss',required:true,inputmode:'decimal'}));
 const title=draft(prefix+'title',h('input',{type:'text',maxlength:100,required:true}),job.case_name);
 const audio=h('audio',{controls:true,preload:'none',src:job.audio_url,style:'width:100%'});
 const transcript=h('div.clip-transcript');
 // Local controls must not use button(): its act() refreshes the dashboard.
 const localButton=(label,task)=>h('button.small',{type:'button',onclick:task},label);
 const range=h('p.clip-selection',{'aria-live':'polite'});
 let markSelection=()=>{};
 const seconds=value=>value.trim()===''?NaN:value.split(':').reduce((total,part)=>total*60+Number(part),0);
 const rangeTime=value=>Number.isFinite(seconds(value))?clock(seconds(value)):value||'choose time';
 const refreshRange=()=>{range.textContent=`Selected: ${rangeTime(start.value)} → ${rangeTime(end.value)}`;markSelection();};
 const set=(field,key,value)=>{field.value=String(Math.round(value*20)/20);drafts.set(prefix+key,field.value);refreshRange();};
 start.addEventListener('input',refreshRange);end.addEventListener('input',refreshRange);refreshRange();
 async function load(){
  const url=job.podcast_alignment?.url;if(!url)throw Error('The shared aligned transcript is not available yet');
  if(!transcripts.has(url)){
   const response=await fetch(url,{credentials:'same-origin'});if(!response.ok)throw Error('Could not load the transcript');
   const data=await response.json();transcripts.set(url,data.sections.flatMap(s=>s.turns.flatMap(t=>t.text_blocks.map(b=>({start:b.start,stop:b.stop,name:t.speaker.name,text:b.text})))));
  }
  const rows=transcripts.get(url);
  const search=h('input',{type:'search',placeholder:'Search words or a speaker','aria-label':'Search the transcript'}),list=h('div.clip-passages');
  const items=rows.map(r=>{
   const begin=localButton('Start here',()=>set(start,'start',r.start));
   const finish=localButton('End here',()=>set(end,'end',r.stop));
   const el=h('div.clip-passage',h('div.clip-passage-heading',localButton(clock(r.start),()=>{audio.currentTime=r.start;}),h('strong',r.name)),
    h('p',r.text),h('div.clip-boundaries',begin,finish));
   return {r,el,begin,finish};
  });
  markSelection=()=>{for(const {r,el,begin,finish} of items){
   const a=seconds(start.value),b=seconds(end.value);
   const isStart=start.value!==''&&Math.abs(a-r.start)<.03,isEnd=end.value!==''&&Math.abs(b-r.stop)<.03;
   el.classList.toggle('selected',start.value!==''&&end.value!==''&&b>a&&r.start<b&&r.stop>a);
   begin.textContent=isStart?'✓ Start here':'Start here';finish.textContent=isEnd?'✓ End here':'End here';
   begin.setAttribute('aria-pressed',String(isStart));finish.setAttribute('aria-pressed',String(isEnd));
  }};
  const count=h('span.note');
  const empty=h('p.note','No matching passages.');
  function show(){
   const query=search.value.trim().toLowerCase();let visible=0;
   for(const {r,el} of items){el.hidden=!!query&&!`${r.name} ${r.text}`.toLowerCase().includes(query);if(!el.hidden)visible++;}
   count.textContent=`${visible} passages`;empty.hidden=visible>0;list.scrollTop=0;
  }
  list.append(...items.map(i=>i.el),empty);
  search.addEventListener('input',show);show();markSelection();
  transcript.replaceChildren(h('div.clip-transcript-tools',search,count),list);

 }
 let form=h('form.clip-form',h('label','Title',title),h('div.clip-times',h('label','Start',start),h('label','End',end)),
   h('p.note','Times refer to the original argument audio. Maximum clip length: 10 minutes.'),audio,range,
   disclosure(prefix+'transcript','Choose from the transcript',button('Load transcript',load,{done:''}),transcript),
   h('button.primary',{type:'submit'},'Render vertical clip'));
 if(transcripts.has(job.podcast_alignment?.url))load();
 submitForm(form,()=>api('clip',{job:job.id,command:'create',title:title.value,start:start.value,end:end.value}),'Clip queued.');
 return form;
 }
 const formKey=job.id+':'+(job.podcast_alignment?.url||'');
 if(!forms.has(formKey))forms.set(formKey,buildForm());
 const form=forms.get(formKey);
 // Moving a retained form into a new dashboard tree can reset native scroll
 // offsets. Restore them after the new tree is attached, before the next paint.
 if(form.isConnected){
  const list=form.querySelector('.clip-passages'),offset=list?.scrollTop||0;
  const detail=document.getElementById('detail'),detailTop=detail?.scrollTop||0,pageTop=window.scrollY,hash=location.hash;
  queueMicrotask(()=>{if(form.isConnected&&location.hash===hash){if(list)list.scrollTop=offset;if(detail)detail.scrollTop=detailTop;window.scrollTo(0,pageTop);}});
 }
 const clips=Object.values(job.clips||{}).sort((a,b)=>b.created_at.localeCompare(a.created_at));
 const labels={render_queued:'Queued to render',upload_queued:'Queued to upload',tiktok_draft_queued:'Queued for TikTok draft',tiktok_publish_queued:'Queued to publish on TikTok',instagram_publish_queued:'Queued to publish on Instagram',youtube_link_queued:'Queued to link full argument',starting:'Starting',rendering:'Rendering',ready:'Ready to download',uploading:'Uploading',uploaded:'Uploaded unlisted',failed:'Failed'};
 function tiktok(clip){
  if(!clip.result?.video_uri)return null;
  const saved=clip.tiktok||{},busy=!['ready','uploaded','failed'].includes(clip.status);
  const caption=draft(prefix+clip.id+'-tiktok-caption',h('textarea',{rows:4,maxlength:4000,'aria-label':'TikTok caption',disabled:busy||saved.saved||saved.published}),saved.caption||`${clip.title}\n${clock(clip.start)}–${clock(clip.end)} from ${job.case_name} (${job.docket}).${clip.result.credit?'\n'+clip.result.credit:''}`);
  const send=async command=>{
   await api('clip',{job:job.id,clip:clip.id,command,caption:caption.value});
  };
  return h('div',h('p.note',saved.published?'Published on TikTok':saved.saved?'TikTok draft saved':busy&&clip.mode?.startsWith('tiktok_')?'Transferring to TikTok…':''),
   saved.url&&link('Open on TikTok',saved.url),
   saved.published&&link('TikTok Studio','https://www.tiktok.com/tiktokstudio/content'),
   !saved.published&&disclosure(prefix+clip.id+'-tiktok','TikTok',h('label','Caption',caption),h('div.actions',
    !saved.saved&&button('Save TikTok draft',()=>send('tiktok_draft'),{disabled:busy,done:'TikTok draft queued.'}),
    button(saved.saved?'Publish TikTok draft':'Publish on TikTok',()=>send('tiktok_publish'),{disabled:busy,confirm:'Publish this clip publicly on TikTok?',done:'TikTok publication queued.'})),
    link('Open TikTok Studio','https://www.tiktok.com/tiktokstudio/content')));
 }
 function instagram(clip){
  if(!clip.result?.video_uri)return null;
  const saved=clip.instagram||{},busy=!['ready','uploaded','failed'].includes(clip.status);
  if(saved.published)return h('div.actions',h('span.note','Published on Instagram'),saved.url&&link('Open on Instagram',saved.url));
  const caption=draft(prefix+clip.id+'-instagram-caption',h('textarea',{rows:4,maxlength:2200,'aria-label':'Instagram caption',disabled:busy||saved.caption_locked}),saved.caption||`${clip.title}\n${job.case_name} (${job.docket}).${clip.result.credit?'\n'+clip.result.credit:''}`);
  return disclosure(prefix+clip.id+'-instagram','Instagram',h('label','Caption',caption),
   button('Publish on Instagram',()=>api('clip',{job:job.id,clip:clip.id,command:'instagram_publish',caption:caption.value}),{disabled:busy,confirm:'Publish this clip publicly on Instagram?',done:'Instagram publication started.'}));
 }
 return block('Vertical clips',
  clips.map(clip=>h('div.clip-item',h('h3',clip.title),h('p.note',`${clock(clip.start)}–${clock(clip.end)} · ${labels[clip.status]||clip.status}${['rendering','uploading'].includes(clip.status)?' · '+Math.round((clip.progress||0)*100)+'%':''}`),
    clip.error&&h('p.problem',clip.error),h('div.actions',
     clip.result?.video_uri&&button('Download MP4',async()=>{const result=await api('clip_download',{job:job.id,clip:clip.id});location.assign(result.url);}),
     clip.status==='ready'&&button('Upload unlisted to YouTube',()=>api('clip',{job:job.id,clip:clip.id,command:'upload'}),{done:'Clip upload queued.'}),
     clip.status==='failed'&&button('Retry',()=>api('clip',{job:job.id,clip:clip.id,command:'retry'}),{done:'Clip retry queued.'}),
     clip.youtube?.video_id&&link('YouTube',clip.youtube.video_url),
     clip.youtube?.related_video_error&&h('span.note',clip.youtube.related_video_error),
     clip.youtube?.related_video_verified&&h('span.note','Full argument linked'),
     clip.youtube?.video_id&&!clip.youtube.related_video_verified&&['ready','uploaded','failed'].includes(clip.status)&&button('Link full argument',()=>api('clip',{job:job.id,clip:clip.id,command:'youtube_link'}),{done:'Full-video link requested.'}),
     clip.youtube?.video_id&&link('YouTube Studio','https://studio.youtube.com/video/'+clip.youtube.video_id+'/edit')),tiktok(clip),instagram(clip))),
  disclosure(prefix+'form','Create a clip',form));
}
