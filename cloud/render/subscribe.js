'use strict';

// The planner supplies actual visible intervals, including card entry/exit frames.
function reminderWindow(cues,duration,{after=600,minGap=15,visible=8,cardTransition=0,fps=20}={}){
 if(!Number.isFinite(duration)||duration<=0||!Number.isFinite(after)||after<0||!(minGap>=visible&&visible>0)||!(cardTransition>=0)||!(fps>0))throw Error('Invalid reminder timing');
 const last=Math.floor(duration*fps),needed=Math.ceil(minGap*fps);
 let first=Math.ceil(after*fps);
 const occupied=cues.map(cue=>{
  if(!Number.isFinite(cue.start)||!Number.isFinite(cue.end)||cue.start<0||cue.end<=cue.start)throw Error('Invalid annotation interval');
  return [Math.floor(cue.start*fps),Math.ceil((cue.end+cardTransition)*fps)];
 }).sort((a,b)=>a[0]-b[0]);
 for(const [start,end] of [...occupied,[last,last]]){
  const stop=Math.min(start,last);
  if(stop-first>=needed)return {start:first/fps,end:(first+Math.round(visible*fps))/fps};
  first=Math.max(first,end);
 }
 return null;
}

// Explicit frame operations make fades repeatable across separately rendered chunks.
function splitReminderEvent(event,window,audioStart,fps=20){
 if(!window)return [event];
 const offset=event.first_frame-Math.round(audioStart*fps),start=Math.round(window.start*fps)+offset,end=Math.round(window.end*fps)+offset;
 const fade=Math.round(.4*fps),cuts=new Set([event.first_frame,event.end_frame]);
 for(let f=start;f<=start+fade;f++)if(f>event.first_frame&&f<event.end_frame)cuts.add(f);
 for(let f=end-fade;f<=end;f++)if(f>event.first_frame&&f<event.end_frame)cuts.add(f);
 const boundaries=[...cuts].sort((a,b)=>a-b),output=[];
 for(let i=0;i<boundaries.length-1;i++){
  const first=boundaries[i],ops=first===event.first_frame?[...event.ops]:[];
  if(first>=start&&first<=end)ops.push({name:'setSubscribeReminderProgress',args:[(first-start)/fps,window.end-window.start]});
  else if(first>end&&ops.some(op=>op.name==='nextTextBlock'))ops.push({name:'setSubscribeReminderProgress',args:[window.end-window.start,window.end-window.start]});
  output.push({first_frame:first,end_frame:boundaries[i+1],ops});
 }
 if(!output.length){
  const ops=[...event.ops];
  if(event.first_frame===end)ops.push({name:'setSubscribeReminderProgress',args:[window.end-window.start,window.end-window.start]});
  return [{...event,ops}];
 }
 return output;
}
module.exports={reminderWindow,splitReminderEvent};
