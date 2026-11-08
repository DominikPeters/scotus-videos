const assert=require('node:assert/strict');
const {openingBlock}=require('../render/intro');
const duration=x=>x.duration+x.frameInfo.reduce((s,f)=>s+f[1],0);
for(const response of [
 {duration:20,frameInfo:[]},
 {duration:.05,frameInfo:Array.from({length:23},(_,i)=>[0,.05,(i+2)/24]).concat([[0,18.8,1]])},
 {duration:.05,frameInfo:[[3,.05],[1,.05],[2,.05],[0,9.8]]},
 {duration:.05,frameInfo:[[0,.45,1]]},
 {duration:2,frameInfo:[]},
]){
 const original=JSON.stringify(response),out=openingBlock(response);
 assert.equal(out.intro,Math.min(5,duration(response)));
 assert(Math.abs(out.intro+duration(out)-duration(response))<1e-8,'Audio duration changed');
 assert.equal(JSON.stringify(response),original,'Original response mutated');
}
const animated=openingBlock({duration:.05,frameInfo:[[1,.05,.5],[2,.05,1],[0,19.85,1]]});
assert.equal(animated.intro,5);assert.equal(animated.advance.length,3);assert.equal(animated.duration,15);assert.deepEqual(animated.frameInfo,[]);
console.log('Opening splash uses complete block timing, including card/scroll frames, without changing audio duration.');
