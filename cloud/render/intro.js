'use strict';

// A text block may be split into 0.05s scroll/card animation steps. The splash
// borrows time from the whole block, not just its first animation frame.
function openingBlock(response,maxSeconds=5){
 const frames=response.frameInfo.map(frame=>[...frame]);
 const total=response.duration+frames.reduce((sum,frame)=>sum+frame[1],0);
 if(!Number.isFinite(total)||total<0||!(maxSeconds>=0))throw Error('Invalid opening block duration');
 const intro=Math.min(maxSeconds,total);let remaining=intro,duration=response.duration;
 const advance=[];
 if(remaining<=duration){duration-=remaining;remaining=0;}
 else{
  remaining-=duration;duration=0;
  while(frames.length&&remaining>1e-9){
   const frame=frames.shift();advance.push(frame);
   if(remaining>=frame[1]-1e-9)remaining=Math.max(0,remaining-frame[1]);
   else{duration=frame[1]-remaining;remaining=0;}
  }
 }
 return {intro,duration,frameInfo:frames,advance};
}

module.exports={openingBlock};
