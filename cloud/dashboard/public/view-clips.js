import {h,link,clock} from './dom.js';
import {api} from './api.js';
import {block,button,disclosure,draft,drafts,submitForm} from './ui.js';
const transcripts=new Map();
const forms=new Map();

export function clipsBlock(job){
 if(!job.stages.plan.result?.bundle_uri&&!Object.keys(job.clips||{}).length)return null;
 const prefix=job.id+'-clip-';
 const start=draft(prefix+'start',h('input',{type:'text',placeholder:'mm:ss',required:true,inputmode:'decimal'}));
 const end=draft(prefix+'end',h('input',{type:'text',placeholder:'mm:ss',required:true,inputmode:'decimal'}));
 const title=draft(prefix+'title',h('input',{type:'text',maxlength:100,required:true}),job.case_name);
 const audio=h('audio',{controls:true,preload:'none',src:job.audio_url,style:'width:100%'});
 const transcript=h('div.clip-transcript');
 const set=(field,key,value)=>{field.value=String(Math.round(value*20)/20);drafts.set(prefix+key,field.value);};
 async function load(){
  const url=job.podcast_alignment?.url;if(!url)throw Error('The shared aligned transcript is not available yet');
  if(!transcripts.has(url)){
   const response=await fetch(url,{credentials:'same-origin'});if(!response.ok)throw Error('Could not load the transcript');
   const data=await response.json();transcripts.set(url,data.sections.flatMap(s=>s.turns.flatMap(t=>t.text_blocks.map(b=>({start:b.start,stop:b.stop,name:t.speaker.name,text:b.text})))));
  }
  const rows=transcripts.get(url);let limit=60;
  const search=h('input',{type:'search',placeholder:'Search the transcript','aria-label':'Search the transcript'}),list=h('div');
  function show(){
   const selected=rows.filter(r=>!search.value||r.text.toLowerCase().includes(search.value.toLowerCase()));
   list.replaceChildren(...selected.slice(0,limit).map(r=>h('div.clip-passage',
    h('div.actions',button(clock(r.start),()=>{audio.currentTime=r.start;},{small:true}),h('strong',r.name),
      button('Start here',()=>set(start,'start',r.start),{small:true}),button('End here',()=>set(end,'end',r.stop),{small:true})),h('p',r.text))));
   if(selected.length>limit)list.append(button('Show more',()=>{limit+=60;show();},{small:true}));
  }
  search.addEventListener('input',()=>{limit=60;show();});show();transcript.replaceChildren(search,list);
 }
 let form=h('form.clip-form',h('label','Title',title),h('div.clip-times',h('label','Start',start),h('label','End',end)),
   h('p.note','Times refer to the original argument audio. Maximum clip length: 10 minutes.'),audio,
   disclosure(prefix+'transcript','Choose from the transcript',button('Load transcript',load,{done:''}),transcript),
   h('button.primary',{type:'submit'},'Render vertical clip'));
 if(transcripts.has(job.podcast_alignment?.url))load();
 submitForm(form,()=>api('clip',{job:job.id,command:'create',title:title.value,start:start.value,end:end.value}),'Clip queued.');
 const formKey=job.id+':'+(job.podcast_alignment?.url||'');
 if(forms.has(formKey))form=forms.get(formKey);else forms.set(formKey,form);
 const clips=Object.values(job.clips||{}).sort((a,b)=>b.created_at.localeCompare(a.created_at));
 const labels={render_queued:'Queued to render',upload_queued:'Queued to upload',tiktok_draft_queued:'Queued for TikTok draft',tiktok_publish_queued:'Queued to publish on TikTok',starting:'Starting',rendering:'Rendering',ready:'Ready to download',uploading:'Uploading',uploaded:'Uploaded unlisted',failed:'Failed'};
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
 return block('Vertical clips',
  clips.map(clip=>h('div.clip-item',h('h3',clip.title),h('p.note',`${clock(clip.start)}–${clock(clip.end)} · ${labels[clip.status]||clip.status}${['rendering','uploading'].includes(clip.status)?' · '+Math.round((clip.progress||0)*100)+'%':''}`),
    clip.error&&h('p.problem',clip.error),h('div.actions',
     clip.result?.video_uri&&button('Download MP4',async()=>{const result=await api('clip_download',{job:job.id,clip:clip.id});location.assign(result.url);}),
     clip.status==='ready'&&button('Upload unlisted to YouTube',()=>api('clip',{job:job.id,clip:clip.id,command:'upload'}),{done:'Clip upload queued.'}),
     clip.status==='failed'&&button('Retry',()=>api('clip',{job:job.id,clip:clip.id,command:'retry'}),{done:'Clip retry queued.'}),
     clip.youtube?.video_id&&link('YouTube',clip.youtube.video_url),
     clip.youtube?.video_id&&link('YouTube Studio','https://studio.youtube.com/video/'+clip.youtube.video_id+'/edit')),tiktok(clip))),
  disclosure(prefix+'form','Create a clip',form));
}
