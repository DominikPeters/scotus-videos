'use strict';
// Refresh the existing fill after about two design pixels of movement.
function splitProgressEvent(event,info,audioStart,fps=20){
 if(!info||!(info.width>0)||!(info.end>info.start)||event.end_frame<=event.first_frame)return [event];
 const interval=Math.max(.5,Math.min(3,2*(info.end-info.start)/info.width));
 const step=Math.max(1,Math.round(interval*fps)),events=[];
 for(let first=event.first_frame;first<event.end_frame;first+=step){
  const timestamp=audioStart+(first-event.first_frame)/fps;
  const percent=Math.max(0,Math.min(100,100*(timestamp-info.start)/(info.end-info.start)));
  const progress={name:'setInteractionProgress',args:[info.section,info.interaction,percent]};
  events.push({ops:first===event.first_frame?[...event.ops,progress]:[progress],
              first_frame:first,end_frame:Math.min(event.end_frame,first+step)});
 }
 return events;
}
module.exports={splitProgressEvent};
