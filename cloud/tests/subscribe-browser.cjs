// Local-only integration: use a copied bundle and its already generated plan.
const fs=require('fs'),path=require('path'),assert=require('assert'),crypto=require('crypto');
const {open,action,setupCredit}=require('../render/original');
(async()=>{
 const [root,id,planFile,output]=process.argv.slice(2),data=JSON.parse(fs.readFileSync(planFile));
 const window=data.subscribe_reminder;if(!window)throw Error('This integration fixture needs an eligible gap');
 fs.mkdirSync(output,{recursive:true});const {page,browser,server}=await open(root,id);
 const credit=JSON.parse(fs.readFileSync(path.join(root,'credit.json'))),hash=x=>crypto.createHash('sha256').update(x).digest('hex');
 try{
  await setupCredit(page,credit);let middle=null;
  const samples=[window.start-.05,window.start+.2,window.start+1,window.start+5,window.end-.2,window.end];let checks=0;
  for(const event of data.events){
   for(const op of event.ops)await action(page,op);
   const state=await page.evaluate(()=>{const el=document.querySelector('.subscribe-suggestion'),r=el.getBoundingClientRect(),c=document.getElementById('conversation').getBoundingClientRect();return {display:getComputedStyle(el).display,opacity:+getComputedStyle(el).opacity,inside:r.left>=c.left&&r.right<=c.right&&r.bottom<=c.bottom&&r.bottom<=1080,card:[...document.querySelectorAll('#quote-card,#quote-card-under')].some(e=>e.classList.contains('visible'))};});
   const time=event.first_frame/20;
   if(state.display!=='none'&&state.opacity>0){assert(time>=window.start&&time<window.end);assert(!state.card,'Reminder overlapped an annotation');assert(state.inside,'Reminder escaped the sidebar');}
   for(const sample of samples)if(event.first_frame<=Math.round(sample*20)&&event.end_frame>Math.round(sample*20)){
    if(sample<window.start||sample>=window.end)assert.equal(state.display,'none');else assert(state.opacity>0);
    const file=path.join(output,'at-'+sample.toFixed(2)+'.png');const bytes=await page.screenshot({path:file});checks++;
    if(sample===window.start+5){const box=await page.$eval('.subscribe-suggestion',el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};});middle=hash(await page.screenshot({clip:box}));}
   }
   if(time>window.end)break;
  }
  assert.equal(checks,samples.length);
  // A new page reconstructs the middle of the reminder as a separate chunk would.
  const peer=await browser.newPage();await peer.setViewport({width:1920,height:1080,deviceScaleFactor:2});
  await peer.goto('http://localhost:8002/?case='+id);await peer.waitForSelector('#loading-finished');await setupCredit(peer,credit);
  for(const event of data.events){for(const op of event.ops)await action(peer,op);if(event.end_frame>Math.round((window.start+5)*20))break;}
  await peer.screenshot({path:path.join(output,'parallel-replay.png')});
  const box=await peer.$eval('.subscribe-suggestion',el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};});
  assert.equal(hash(await peer.screenshot({clip:box,path:path.join(output,'parallel-reminder.png')})),middle,'Parallel replay changed reminder pixels');
  // A section transition must never trigger the old subscribe popup.
  await action(page,{name:'setSubscribeReminderProgress',args:[8,8]});await action(page,{name:'goToNextSection'});
  assert.equal(await page.$eval('.subscribe-suggestion',el=>getComputedStyle(el).display),'none');
  console.log(JSON.stringify({window,screenshot_checks:checks,card_overlap:false,sidebar_bounds:true,parallel_reminder_pixels_identical:true,section_popup_removed:true}));
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e.stack);process.exitCode=1});
