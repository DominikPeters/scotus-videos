// Integration check against a downloaded presentation bundle (never modifies it).
// node cloud/tests/vertical-cards.cjs /path/to/bundle CASE_ID /tmp/vertical-card-check
const fs=require('fs'),path=require('path'),os=require('os'),assert=require('assert');
const {open,action}=require('../render/original');
const {clipPlan}=require('../render/vertical');
(async()=>{
 const [source,id,output]=process.argv.slice(2);
 if(!source||!id||!output)throw Error('Supply bundle, case ID and output directory');
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'vertical-cards-')),root=path.join(temp,'bundle');
 fs.cpSync(path.resolve(source),root,{recursive:true});fs.mkdirSync(output,{recursive:true});
 fs.copyFileSync(path.resolve(__dirname,'../presentation/renderer/vertical.html'),path.join(root,'vertical.html'));
 const cues=[{id:'definition',start:2,end:9,kind:'Statute',heading:'Consumer',source:'18 U.S.C. § 2710',quote:'the term “consumer” means any renter, purchaser, or subscriber of goods or services from a video tape service provider'},
 {id:'comparison',start:9,end:18,kind:'Comparison',heading:'The disputed definition',source:'Test fixture',compare:[{title:'Consumer',text:'Renter, purchaser, or subscriber'},{title:'Provider',text:'A person engaged in the business'}]}];
 fs.writeFileSync(path.join(root,'json',id+'-cards.json'),JSON.stringify({cues}));
 try{
  // Start inside an existing card: replay must restore it and then handle swap/exit.
  const planFile=path.join(output,'plan.json');await clipPlan(root,id,5,60,planFile);
  const plan=JSON.parse(fs.readFileSync(planFile));assert(plan.events.some(e=>e.ops.some(o=>o.name==='setQuoteProgress')));
  const {page,browser,server}=await open(root,id,true);
  try{
   const captured=new Set();
   for(const event of plan.events){
    for(const op of event.ops)await action(page,op);
    const state=await page.evaluate(()=>{
     const card=document.getElementById('quote-card'),body=document.getElementById('quote-body'),tr=document.getElementById('transcript');
     return {id:card.dataset.showing,visible:card.classList.contains('visible'),height:card.getBoundingClientRect().height,padding:parseFloat(getComputedStyle(tr).paddingTop),scroll:body.scrollHeight,client:body.clientHeight,overflow:body.scrollHeight>body.clientHeight+2,swapping:!!document.getElementById('quote-card-under')};
    });
    if(state.visible&&!state.swapping&&state.height>0){
     if(state.overflow)await page.screenshot({path:path.join(output,'overflow.png')});
     assert(!state.overflow,'Card body overflow: '+JSON.stringify(state));
     assert(state.padding>15,'Visible card must make room in transcript');
     if(state.padding>=state.height+38&&!captured.has(state.id)){await page.screenshot({path:path.join(output,state.id+'.png')});captured.add(state.id);}
    }
   }
   assert(captured.has('definition')&&captured.has('comparison'),'Both cards should survive clip state replay');
   assert.equal(await page.evaluate(()=>document.getElementById('quote-card').classList.contains('visible')),false);
   assert.equal(await page.evaluate(()=>parseFloat(getComputedStyle(document.getElementById('transcript')).paddingTop)),15);
   console.log('Passed vertical card replay, comparison, transitions, fitting and transcript reset.');
  }finally{await browser.close();server.close();}
 }finally{fs.rmSync(temp,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exitCode=1;});
