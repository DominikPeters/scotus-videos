// This uses a virtual authenticator only on localhost, never on the live site.
const puppeteer=require('puppeteer');
const fs=require('fs');
const base='http://localhost:18883';
(async()=>{
  const browser=await puppeteer.launch({headless:'new'});
  try{
    const page=await browser.newPage();await page.setViewport({width:1250,height:900});
    const cdp=await page.createCDPSession();await cdp.send('WebAuthn.enable');
    await cdp.send('WebAuthn.addVirtualAuthenticator',{options:{protocol:'ctap2',transport:'internal',hasResidentKey:true,hasUserVerification:true,isUserVerified:true,automaticPresenceSimulation:true}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base+'/#setup=test-enrollment-token');
    await page.waitForFunction(()=>document.getElementById('signin-button').textContent==='Create a passkey');
    await page.click('#signin-button');
    await page.waitForFunction(()=>!document.getElementById('dashboard').hidden,{timeout:20000});
    await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.click('#logout')]);
    await page.waitForFunction(()=>!document.getElementById('signin').hidden);
    await page.click('#signin-button');
    await page.waitForFunction(()=>!document.getElementById('dashboard').hidden,{timeout:20000});
    if(await page.$eval('#queue-details',el=>el.open))throw Error('Queue form should start collapsed');
    await page.click('#queue-details summary');
    await page.type('input[name=docket]','23-1038');
    await page.$eval('input[name=argument_date]',el=>{el.value='2024-12-02';});
    await page.type('input[name=case_name]','FDA v. Wages and White Lion Investments');
    await page.type('input[name=title]','Oral Argument on flavored e-cigarettes: FDA v. Wages');
    await page.type('input[name=pdf_url]','https://www.supremecourt.gov/oral_arguments/argument_transcripts/2024/23-1038_3d94.pdf');
    await page.type('input[name=audio_url]','https://www.supremecourt.gov/media/audio/mp3files/23-1038.mp3');
    await page.click('#queue-form button');
    await page.waitForFunction(()=>document.querySelectorAll('#jobs tr').length===1);
    const blocked=await page.evaluate(async()=>{
      const response=await fetch('api.php?action=command',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':'wrong'},body:JSON.stringify({command:'resume'})});return response.status;
    });
    if(blocked!==403)throw Error('Wrong CSRF token was accepted');
    await page.evaluate(()=>[...document.querySelectorAll('#jobs button')].find(b=>b.textContent==='Start').click());
    await page.waitForFunction(()=>[...document.querySelectorAll('#jobs button')].some(b=>b.textContent==='Start requested'&&b.disabled));
    const started=JSON.parse(fs.readFileSync('/tmp/scotus-dashboard-cleanup-test/state.json'));
    if(!started.paused||!Object.values(started.jobs)[0].run_requested)throw Error('Start did not preserve automatic pause');
    const hasUppercaseStyle=await page.evaluate(()=>[...document.querySelectorAll('h1,h2,th')].some(el=>getComputedStyle(el).textTransform==='uppercase'));
    if(hasUppercaseStyle)throw Error('Uppercase headings');
    // Exercise a slow cloud launch and automatic instruction/completion polling.
    let fakeLogin=null;
    await page.setRequestInterception(true);
    page.on('request',request=>{
      const action=new URL(request.url()).searchParams.get('action');let result;
      if(action==='secret_status')result={workers_enabled:false,codex_login_enabled:true,youtube_client_configured:false,credentials:{codex:{configured:fakeLogin?.status==='complete',updated_at:null}}};
      else if(action==='connect_start'){fakeLogin={id:'fake-login',status:'starting',created_at:new Date(Date.now()-95000).toISOString()};result=fakeLogin;}
      else if(action==='asset_data')result={mime:'image/png',data:'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jWZkAAAAASUVORK5CYII='};
      else if(action==='connect_status')result=fakeLogin;
      else if(action==='connect_cancel'){fakeLogin={...fakeLogin,status:'cancelled'};result=fakeLogin;}
      else return request.continue();
      return request.respond({status:200,contentType:'application/json',body:JSON.stringify({ok:true,result})});
    });
    await page.evaluate(()=>secrets());
    await page.click('#credentials-details summary');
    await page.click('#secrets button');
    await page.waitForFunction(()=>document.getElementById('connection-guide').textContent.includes('Waiting 1m'));
    if(!await page.$('#connection-guide button'))throw Error('Startup cancellation is missing');
    fakeLogin={...fakeLogin,status:'pending',verification_url:'https://auth.openai.com/codex/device',user_code:'ABCD-1234'};
    await page.waitForFunction(()=>document.querySelector('.device-code')?.textContent==='ABCD-1234',{timeout:10000});
    fakeLogin={...fakeLogin,status:'complete'};
    await page.waitForFunction(()=>document.getElementById('connection-guide').hidden&&document.getElementById('message').textContent==='Codex connected.',{timeout:10000});
    await page.reload();await page.waitForFunction(()=>!document.getElementById('dashboard').hidden);
    await page.waitForFunction(()=>document.getElementById('cloud-status').textContent.includes('Cloud connected'));
    if(!await page.$eval('#connection-guide',el=>el.hidden))throw Error('Completed Codex sign-in resurfaced after reload');
    if(await page.$('#youtube-client-details'))throw Error('YouTube setup instructions were not removed');
    if(await page.$('#notification-test'))throw Error('Redundant notification setup section remains');
    const privatePath='/tmp/scotus-dashboard-cleanup-test/state.json';
    const snapshot=JSON.parse(fs.readFileSync(privatePath)),job=Object.values(snapshot.jobs)[0];
    job.status='needs_review';job.stages.enrich.status='needs_review';
    job.review={id:'fixture-review',revision:'b'.repeat(64),titles:[{title:'Oral Argument on the first topic: Example v. Case',private_reason:'First private explanation.'},{title:'Oral Argument on another topic: Example v. Case',private_reason:'Second private explanation.'}],description:{facts_of_the_case:'<p>A short factual description.</p>',question:'<p>A neutral question.</p>'},private_notes:['Private caveat.'],photos:{lawyer:{name:'Verified advocate',identity_evidence:'Official appearances evidence.',candidates:[{id:'candidate',kind:'photo',square_asset:true,source_uri:'gs://private/original.bin',source_preview_uri:'gs://private/source-preview.jpg',portrait_uri:'gs://private/portrait.jpg',preview_uri:'gs://private/preview.jpg',sha256:'c'.repeat(64),source_url:'https://example.org/portrait'}]}}};
    fs.writeFileSync(privatePath,JSON.stringify(snapshot));await page.evaluate(()=>refresh());
    await page.waitForSelector('#review-fixture-review[open] .portrait-options img');
    if(await page.$eval('.portrait-options img',el=>getComputedStyle(el).objectFit)!=='cover')throw Error('Square video crop preview missing');
    await page.evaluate(()=>[...document.querySelectorAll('.portrait-options button')].find(b=>b.textContent==='Show full image').click());
    await page.waitForFunction(()=>document.querySelector('.portrait-options img')?.classList.contains('full-image'));
    if(await page.$eval('.portrait-options img',el=>getComputedStyle(el).objectFit)!=='contain')throw Error('Full image preview missing');
    const titleButtons=await page.$$('#review-fixture-review .title-choice button');await titleButtons[1].click();
    await page.waitForFunction(()=>document.querySelectorAll('.title-choice button')[1]?.textContent==='Selected');
    const options=await page.$$eval('.photo-feedback option',els=>els.map(el=>el.value));
    if(!['different','recrop','synthetic'].every(value=>options.includes(value)))throw Error('Photo feedback actions missing');
    await page.evaluate(()=>{const form=document.querySelector('.photo-feedback');form.elements.action.value='recrop';form.elements.hint.value='Leave room above his head';form.requestSubmit();});
    await page.waitForFunction(()=>document.getElementById('reviews').textContent.includes('Codex photo request: recrop — queued'));
    const requested=JSON.parse(fs.readFileSync(privatePath)),requestedJob=Object.values(requested.jobs)[0],req=Object.values(requestedJob.photo_requests)[0];
    if(req.hint!=='Leave room above his head'||!requestedJob.review.photos.lawyer.candidates[0].rejected)throw Error('Photo feedback not persisted');
    requestedJob.photo_requests[req.id].status='complete';requestedJob.review.photos.lawyer.candidates.push({...requestedJob.review.photos.lawyer.candidates[0],id:'new-crop',rejected:false,sha256:'d'.repeat(64)});requestedJob.review.revision='e'.repeat(64);fs.writeFileSync(privatePath,JSON.stringify(requested));await page.evaluate(()=>refresh());
    await page.evaluate(()=>[...document.querySelectorAll('.portrait-options button')].find(b=>b.textContent==='Approve image'&&!b.disabled).click());
    await page.waitForFunction(()=>[...document.querySelectorAll('.portrait-options button')].some(b=>b.textContent==='Approved'));
    const saved=JSON.parse(fs.readFileSync(privatePath));if(Object.values(saved.jobs)[0].status!=='queued'||!Object.values(saved.jobs)[0].run_requested||!saved.paused)throw Error('Photo approval lost the individual start request');
    // Delayed actions must show progress immediately and preserve disabled states.
    await page.evaluate(()=>{const button=document.createElement('button');button.id='delayed-action';button.textContent='Approve image';document.getElementById('reviews').append(button);button.onclick=()=>run(()=>new Promise(resolve=>setTimeout(resolve,700)),button);});
    await page.click('#delayed-action');
    if(!await page.$eval('#delayed-action',el=>el.disabled&&el.getAttribute('aria-busy')==='true'))throw Error('Delayed approval has no busy state');
    if(await page.$eval('#action-status',el=>el.hidden))throw Error('Loading status not visible');
    await page.waitForFunction(()=>!document.getElementById('delayed-action').disabled&&document.getElementById('action-status').hidden);
    const selected=Object.values(saved.jobs)[0];selected.status='complete';selected.stages.upload={status:'complete',result:{video_id:'fixture',video_url:'https://www.youtube.com/watch?v=fixture',postprocessing_complete:true}};fs.writeFileSync(privatePath,JSON.stringify(saved));await page.evaluate(()=>refresh());
    const publication=await page.evaluate(()=>[...document.querySelectorAll('#reviews button')].find(b=>b.textContent==='Publish video')!==undefined);if(!publication)throw Error('Completed unlisted publication control missing');
    await page.evaluate(()=>[...document.querySelectorAll('#reviews button')].find(b=>b.textContent==='Publish video').click());
    await page.waitForFunction(()=>[...document.querySelectorAll('#reviews button')].some(b=>b.textContent==='Publication requested'&&b.disabled));
    if(errors.length)throw Error(errors.join('; '));
    await page.screenshot({path:'/tmp/scotus-dashboard-test/dashboard.png',fullPage:true});
    console.log('Passed virtual passkeys, collapsed queue, individual Start while paused, CSRF, device login polling, title selection, image approval/resume and publication controls.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
