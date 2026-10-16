'use strict';
// Replay the existing presentation state, but capture/encode only the selected
// audio interval. The clip clock is rebased; source transcript timestamps stay intact.
const fs=require('fs'),path=require('path');
const {open,action,setupCredit,interactionProgress,chunk}=require('./original');
const {splitProgressEvent}=require('./progress');
function intersect(event,first,end){
 const a=Math.max(first,event.first_frame),b=Math.min(end,event.end_frame);
 return b>a?{ops:event.ops,first_frame:a-first,end_frame:b-first}:null;
}
async function clipPlan(root,id,start,stop,out){
 const first=Math.round(start*20),end=Math.round(stop*20);
 if(!Number.isFinite(first)||first<0||end<=first)throw Error('Invalid clip range');
 const {page,browser,server}=await open(root,id,true);
 try{
  await setupCredit(page,JSON.parse(fs.readFileSync(path.join(root,'credit.json'))));
  const events=[];let cursor=0,audioCursor=0,pending=[];
  async function op(name,args=[]){const command={name,args};pending.push(command);return action(page,command);}
  async function save(duration){
   if(!Number.isFinite(duration)||duration<0)throw Error('Invalid frame duration');
   const a=Math.round(cursor*20);cursor+=duration;const b=Math.round(cursor*20);
   const info=await interactionProgress(page);
   for(const event of splitProgressEvent({ops:pending.splice(0),first_frame:a,end_frame:b},info,audioCursor)){
    const selected=intersect(event,first,end);
    if(selected){selected.ops=[...pending,...selected.ops];pending=[];events.push(selected);}
    else if(event.first_frame<first)pending.push(...event.ops);
   }
   audioCursor+=duration;
  }
  await op('goToNextSection');await op('fitVertical');
  while(cursor<stop){
   const response=await op('nextTextBlock');if(!response)break;
   audioCursor=await page.evaluate(()=>sectionsObject[currentSection].turns[currentTurn].text_blocks[currentTextBlock].start);
   await save(response.duration);
   for(const [amount,duration,quote] of response.frameInfo){await op('scrollTranscript',[amount]);if(quote!==undefined&&quote!==null)await op('setQuoteProgress',[quote]);await save(duration);}
   if(response.goToNextSection)await op('goToNextSection');else if(response.lastTurn)break;
  }
  if(Math.round(cursor*20)<end||!events.length)throw Error('Clip exceeds available argument');
  fs.writeFileSync(out,JSON.stringify({schema_version:2,renderer:'original',layout:'vertical',width:1080,height:1920,case_id:id,fps:20,total_frames:end-first,events,chunks:[{index:0,first_frame:0,end_frame:end-first}]}));
 }finally{await browser.close();server.close();}
}
module.exports={intersect,clipPlan};
if(require.main===module){const [root,id,start,stop,out]=process.argv.slice(2);clipPlan(path.resolve(root),id,Number(start),Number(stop),out).then(()=>chunk(path.resolve(root),out,0,out+'.mp4')).catch(e=>{console.error(e);process.exitCode=1;});}
