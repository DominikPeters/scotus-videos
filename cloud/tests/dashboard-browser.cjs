// Browser test of the dashboard app against a throwaway local PHP server and state file.
// Uses a virtual authenticator only on localhost, never on the live site. Run from the repository: node cloud/tests/dashboard-browser.cjs
const puppeteer=require('puppeteer');
const fs=require('fs'),os=require('os'),path=require('path'),crypto=require('crypto'),{spawn}=require('child_process');
const root=path.resolve(__dirname,'..','dashboard');
const port=18800+Math.floor(Math.random()*80),base=`http://localhost:${port}`;
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'scotus-dashboard-test-')),statePath=path.join(dir,'state.json');
const shots=process.env.SCOTUS_SCREENSHOTS||path.join(os.tmpdir(),'scotus-dashboard-test');

function setup(){
  for(const name of fs.readdirSync(path.join(root,'private')))if(name.endsWith('.php')&&name!=='config.php')fs.symlinkSync(path.join(root,'private',name),path.join(dir,name));
  fs.symlinkSync(path.join(root,'private','vendor'),path.join(dir,'vendor'));
  fs.mkdirSync(path.join(dir,'sessions'));
  const key=crypto.generateKeyPairSync('ec',{namedCurve:'P-256'}).publicKey.export({format:'jwk'});
  const raw=Buffer.concat([Buffer.from([4]),Buffer.from(key.x,'base64url'),Buffer.from(key.y,'base64url')]).toString('base64url');
  fs.writeFileSync(path.join(dir,'config.php'),`<?php return ['origin'=>'${base}','rp_id'=>'localhost','cookie_path'=>'/','setup_hash'=>hash('sha256','test-enrollment-token'),'setup_expires'=>time()+3600,'control_url'=>'','control_key'=>'','worker_keys'=>[],'push_public_key'=>'${raw}'];`);
}
const readState=()=>JSON.parse(fs.readFileSync(statePath));
const writeState=value=>fs.writeFileSync(statePath,JSON.stringify(value));
const check=(ok,message)=>{if(!ok)throw Error(message);};

(async()=>{
  setup();
  const server=spawn('php',['-S',`localhost:${port}`,'-t',path.join(root,'public')],{env:{...process.env,SCOTUS_DASHBOARD_PRIVATE_DIR:dir},stdio:'ignore'});
  for(let i=0;i<50;i++){try{await fetch(base+'/api.php?action=session');break;}catch{await new Promise(r=>setTimeout(r,100));}}
  const browser=await puppeteer.launch({headless:'new',executablePath:process.env.PUPPETEER_EXECUTABLE_PATH||undefined});let page;
  try{
    fs.mkdirSync(shots,{recursive:true});
    page=await browser.newPage();await page.setViewport({width:390,height:844,isMobile:true,hasTouch:true});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
    const cdp=await page.createCDPSession();await cdp.send('WebAuthn.enable');
    await cdp.send('WebAuthn.addVirtualAuthenticator',{options:{protocol:'ctap2',transport:'internal',hasResidentKey:true,hasUserVerification:true,isUserVerified:true,automaticPresenceSimulation:true}});
    const text=selector=>page.$eval(selector,el=>el.textContent);
    const click=(selector,label)=>page.evaluate((s,t)=>{const el=[...document.querySelectorAll(s)].find(e=>e.textContent.trim()===t&&!e.disabled);if(!el)throw Error('No '+s+' "'+t+'"');el.click();},selector,label);
    const waitText=(selector,value,timeout=10000)=>page.waitForFunction((s,v)=>[...document.querySelectorAll(s)].some(e=>e.textContent.includes(v)),{timeout},selector,value);

    // Enrollment, sign-out and passkey sign-in.
    await page.goto(base+'/#setup=test-enrollment-token');
    await waitText('#signin button','Create a passkey');await click('#signin button','Create a passkey');
    await waitText('#list','No recordings yet');
    await page.goto(base+'/#/settings');await waitText('#detail button','Sign out');
    await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),click('#detail button','Sign out')]);
    await waitText('#signin button','Sign in with passkey');await click('#signin button','Sign in with passkey');
    await waitText('#detail h1','Settings');

    // Add a recording; adding opens its screen, where it can be started while automatic work is paused.
    await click('#detail summary','Recording details');
    await page.type('input[name=docket]','23-1038');
    await page.$eval('input[name=argument_date]',el=>{el.value='2024-12-02';el.dispatchEvent(new Event('input'));});
    await page.type('input[name=case_name]','FDA v. Wages and White Lion Investments');
    await page.type('input[name=title]','Oral Argument on flavored e-cigarettes: FDA v. Wages');
    await page.type('input[name=pdf_url]','https://www.supremecourt.gov/oral_arguments/argument_transcripts/2024/23-1038_3d94.pdf');
    await page.type('input[name=audio_url]','https://www.supremecourt.gov/media/audio/mp3files/23-1038.mp3');
    await click('#detail button','Add recording');
    await waitText('#detail h1','FDA v. Wages');
    await click('#detail button','Start this recording');await waitText('#detail','Start requested');
    let saved=readState(),id=Object.keys(saved.jobs)[0];
    check(saved.paused&&saved.jobs[id].run_requested,'Start did not preserve automatic pause');
    const blocked=await page.evaluate(async()=>(await fetch('api.php?action=command',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':'wrong'},body:JSON.stringify({command:'resume'})})).status);
    check(blocked===403,'Wrong CSRF token was accepted');

    // A case review: cards and a portrait. Notification links in the old format still land here.
    saved=readState();const job=saved.jobs[id];
    job.status='needs_review';job.stages.prepare.status='complete';job.stages.enrich.status='needs_review';job.stages.align.status='complete';
    job.review={id:'fixture-review',revision:'b'.repeat(64),card_revision:'c'.repeat(64),
      titles:[{title:'Oral Argument on the first topic: Example v. Case',private_reason:'First private explanation.'},{title:'Oral Argument on another topic: Example v. Case',private_reason:'Second private explanation.'}],
      description:{facts_of_the_case:'<p>A short factual description.</p>',question:'<p>A neutral question.</p>'},private_notes:['Private caveat.'],
      cards:[{id:'one',start:10,end:120,recommended:true,reason:'Defines the disputed term.',cue:{kind:'Statute',label:'Who is a consumer?'},card_uri:'gs://private/one.jpg',frame_uri:'gs://private/one-frame.jpg',sources:[]},
             {id:'two',start:300,end:360,recommended:true,reason:'Quotes the exception.',cue:{kind:'Statute',label:'Consent'},card_uri:'gs://private/two.jpg',frame_uri:'gs://private/two-frame.jpg',sources:[]}],
      photos:{lawyer:{name:'Verified advocate',identity_evidence:'Official appearances evidence.',candidates:[{id:'candidate',kind:'photo',square_asset:true,source_uri:'gs://private/original.bin',source_preview_uri:'gs://private/source-preview.jpg',portrait_uri:'gs://private/portrait.jpg',preview_uri:'gs://private/preview.jpg',sha256:'c'.repeat(64),source_url:'https://example.org/portrait'}]}}};
    writeState(saved);
    // Private binary previews keep authentication and ETags without rewriting state.
    const pixel='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jWZkAAAAASUVORK5CYII=';
    fs.mkdirSync(path.join(dir,'preview-cache'),{recursive:true});
    fs.writeFileSync(path.join(dir,'preview-cache',crypto.createHash('sha256').update('gs://private/one.jpg').digest('hex')+'.json'),JSON.stringify({mime:'image/png',data:pixel}));
    const imageUrl=base+'/api.php?'+new URLSearchParams({action:'asset_image',job:id,kind:'card',candidate:'one'});
    const cookie=(await page.cookies()).map(c=>c.name+'='+c.value).join('; '),stateBeforePreview=fs.readFileSync(statePath,'utf8');
    const imageResponse=await fetch(imageUrl,{headers:{Cookie:cookie}});
    check(imageResponse.status===200&&imageResponse.headers.get('content-type')==='image/png','Authenticated binary preview failed');
    check(Buffer.from(await imageResponse.arrayBuffer()).equals(Buffer.from(pixel,'base64')),'Preview bytes changed');
    const etag=imageResponse.headers.get('etag');
    check((await fetch(imageUrl,{headers:{Cookie:cookie,'If-None-Match':etag}})).status===304,'Immutable preview was not revalidated');
    check((await fetch(imageUrl,{headers:{'If-None-Match':etag}})).status===401,'Anonymous conditional request bypassed sign-in');
    check(fs.readFileSync(statePath,'utf8')===stateBeforePreview,'Preview read rewrote workflow state');
    await page.setRequestInterception(true);
    let fakeLogin=null, importedSpec=null, previewDelay=0, activePreviews=0, peakPreviews=0;
    page.on('request',request=>{
      const action=new URL(request.url()).searchParams.get('action');let result;
      if(action==='secret_status')result={workers_enabled:false,codex_login_enabled:true,youtube_client_configured:false,credentials:{codex:{configured:fakeLogin?.status==='complete',updated_at:null}}};
      else if(action==='card_import'){importedSpec=JSON.parse(request.postData()).spec;result={status:'queued',card_count:1};}
      else if(action==='connect_start'){fakeLogin={id:'fake-login',status:'starting',created_at:new Date(Date.now()-95000).toISOString()};result=fakeLogin;}
      else if(action==='asset_data')result={mime:'image/png',data:'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jWZkAAAAASUVORK5CYII='};
      else if(action==='asset_image'){
        activePreviews++;peakPreviews=Math.max(peakPreviews,activePreviews);
        setTimeout(()=>request.respond({status:200,contentType:'image/png',body:Buffer.from(pixel,'base64')}).finally(()=>activePreviews--),previewDelay);return;
      }
      else if(action==='connect_status')result=fakeLogin;
      else if(action==='connect_cancel'){fakeLogin={...fakeLogin,status:'cancelled'};result=fakeLogin;}
      else return request.continue();
      return request.respond({status:200,contentType:'application/json',body:JSON.stringify({ok:true,result})});
    });
    await page.goto(base+'/#review=fixture-review');
    await page.waitForFunction(id=>location.hash==='#/case/'+encodeURIComponent(id),{},id);
    await waitText('.todo','2 annotation cards to review');await waitText('.todo','1 portrait to approve');
    check((await page.title())==='(1) Scotus videos','Title does not count the case that needs review');
    check(await page.$eval('details[id^="card-review-"]',el=>el.open),'Pending cards did not open initially');
    await click('#detail summary','Annotation cards to review');
    check(!await page.$eval('details[id^="card-review-"]',el=>el.open),'Card review cannot collapse');
    await page.goto(base+'/#/settings');await waitText('#detail h1','Settings');
    await page.goto(base+'/#/case/'+id);await waitText('#detail','Annotation cards to review');
    check(!await page.$eval('details[id^="card-review-"]',el=>el.open),'Card review collapse lost during rerender');
    await click('#detail summary','Annotation cards to review');
    await page.$eval('.candidate',el=>el.scrollIntoView());await page.waitForSelector('.candidate img[src^="blob:"]');
    check(await page.$eval('.candidate .portrait',el=>getComputedStyle(el).objectFit)==='cover','Square crop preview missing');
    await page.screenshot({path:path.join(shots,'case-review.png'),fullPage:true});

    // Card enlargement works by keyboard and keeps the background inert until closed.
    await page.$eval('.card-image', el=>el.scrollIntoView());
    await page.waitForSelector('.card-image[src]');
    await page.focus('.card-image');await page.keyboard.press('Enter');
    await page.waitForSelector('dialog.lightbox[open]');
    check(await page.evaluate(()=>document.querySelector('.lightbox').contains(document.activeElement)), 'Image modal did not receive focus');
    await page.$eval('.card-item .segmented button',el=>el.focus());
    check(await page.evaluate(()=>document.querySelector('.lightbox').contains(document.activeElement)), 'Focus escaped to a background control');
    await page.keyboard.press('Escape');await page.waitForFunction(()=>!document.querySelector('.lightbox'));
    check(await page.evaluate(()=>document.activeElement.matches('.card-image')), 'Closing image did not restore preview focus');
    await page.keyboard.press('Space');await page.waitForSelector('dialog.lightbox[open]');
    await page.keyboard.press('Enter');await page.waitForFunction(()=>!document.querySelector('.lightbox'));

    // A second finger cancels refresh; a normal one-finger pull still refreshes.
    let gestureRequests=0;
    const countGesture=request=>{if(new URL(request.url()).searchParams.get('action')==='state')gestureRequests++;};
    page.on('request',countGesture);
    const gesture=steps=>page.evaluate(steps=>{
      window.scrollTo(0,0);
      for(const [name,points] of steps){
        const event=new Event(name,{bubbles:true});
        Object.defineProperty(event,'touches',{value:points.map(clientY=>({clientY}))});
        document.querySelector('#topbar').dispatchEvent(event);
      }
    },steps);
    await gesture([['touchstart',[20]],['touchmove',[220,300]],['touchend',[300]],['touchend',[]]]);
    await new Promise(resolve=>setTimeout(resolve,150));
    check(gestureRequests===0,'Two-finger gesture triggered refresh');
    check(await page.$eval('#pull',el=>el.hidden),'Cancelled gesture left a refresh indicator');
    const refreshed=page.waitForResponse(response=>new URL(response.url()).searchParams.get('action')==='state');
    await gesture([['touchstart',[20]],['touchmove',[220]],['touchend',[]]]);await refreshed;
    await page.waitForFunction(()=>document.getElementById('pull').hidden);
    check(gestureRequests===1,'One-finger pull did not trigger exactly one refresh');
    page.off('request',countGesture);

    // A selected import file survives a dashboard rerender and submits the actual JSON.
    await click('#detail summary','Import annotation cards');
    const importFile=path.join(dir,'proposals.json');fs.writeFileSync(importFile,JSON.stringify({cards:[{id:'portable-proposal'}]}));
    await (await page.$('input[aria-label="Card file"]')).uploadFile(importFile);
    await page.goto(base+'/#/list');await page.goto(base+'/#/case/'+encodeURIComponent(id));
    await waitText('#detail','proposals.json');
    await click('#detail button','Prepare imported cards');await waitText('#toasts','Card import queued.');
    check(importedSpec?.cards[0].id==='portable-proposal','Import lost its selected file during rerender');

    // An exceptional second Opus pass is an explicit owner action, not a retry loop.
    saved=readState();saved.jobs[id].research_attention={kind:'decision',phase:'editor',message:'Opus already ran; another pass needs authorization.',another_editor_pass:true};
    saved.jobs[id].card_research={version:1,checkpoint:{events:[],plan:{hybrid:{calls:{editor:1},tool_calls:{editor:5},readers:{haiku:{saved:true}}}}}};writeState(saved);
    await page.reload();await waitText('#detail button','Authorize another Opus pass');
    await click('#detail button','Authorize another Opus pass');await waitText('#toasts','Saved research queued.');
    saved=readState();check(!saved.jobs[id].research_attention&&saved.jobs[id].card_research.checkpoint.plan.hybrid.calls.editor===0,'Explicit Opus authorization was not saved');
    check(saved.paused&&saved.jobs[id].card_research.checkpoint.plan.hybrid.readers.haiku.saved,'Research resume changed pause preference or lost the reader');
    saved.jobs[id].status='needs_review';saved.jobs[id].stages.enrich.status='needs_review';writeState(saved);await page.reload();await waitText('#detail button','Approve card selections');

    // Card choices default to the recommendation and are approved together.
    await page.evaluate(()=>document.querySelector('.card-item .segmented button:nth-child(2)').click());
    await click('#detail button','Approve card selections');
    await page.waitForFunction(()=>!document.querySelector('.todo')?.textContent.includes('annotation card'));
    saved=readState();check(saved.jobs[id].card_selections.one===false&&saved.jobs[id].card_selections.two===true,'Card selections not saved');

    // Asking for another image rejects the candidate and keeps the hint.
    await click('#detail summary','Ask Codex to change the image');
    await page.select('select[name=action]','recrop');await page.type('textarea[name=hint]','Leave room above his head');
    await click('#detail button','Send to Codex');await waitText('#detail','Codex is recropping');
    saved=readState();const request=Object.values(saved.jobs[id].photo_requests)[0];
    check(request.hint==='Leave room above his head'&&saved.jobs[id].review.photos.lawyer.candidates[0].rejected,'Photo feedback not persisted');
    request.status='complete';saved.jobs[id].review.photos.lawyer.candidates.push({...saved.jobs[id].review.photos.lawyer.candidates[0],id:'new-crop',rejected:false,sha256:'d'.repeat(64)});
    saved.jobs[id].review.revision='e'.repeat(64);writeState(saved);
    await page.reload();await waitText('.candidate button','Approve');await click('.candidate button','Approve');
    await waitText('#detail','Start requested');
    saved=readState();check(saved.jobs[id].approved_photos.lawyer.id==='new-crop'&&saved.jobs[id].status==='queued'&&saved.jobs[id].run_requested&&saved.paused,'Photo approval lost the individual start request');

    // Approved portrait editor: one heading, compact image, clearly separated change actions.
    await click('#detail summary','Portraits (1 approved)');
    await page.click('#change-'+id+'-lawyer > summary');
    check(await page.$eval('.portrait-editor',el=>!el.querySelector('h3')),'Portrait editor repeats the name');
    await page.$eval('.portrait-editor',el=>el.scrollIntoView());
    await (await page.$('.portrait-editor')).screenshot({path:path.join(shots,'portrait-change.png')});

    // Title alternatives.
    await click('#detail summary','Alternatives and reasoning (2)');
    await click('#detail button','Use this title');await waitText('.alternative.selected','another topic');
    check(readState().jobs[id].selected_title.includes('another topic'),'Title not selected');

    // A question from Codex: typed answers survive polling re-renders.
    saved=readState();
    saved.recoveries={rec:{id:'rec',job:id,stage:'plan',status:'needs_input',turns:1,input_revision:'r1',created_at:new Date().toISOString(),updated_at:new Date().toISOString(),log:[{at:new Date().toISOString(),kind:'diagnosis',message:'Plan failed on a null court entry.'}],
      questions:{q:{id:'q',message:'May I patch the adapter?',status:'pending',options:[{id:'yes',label:'Authorize the fix',actor:'operator',private_effect:'You allow the narrow change.'},{id:'no',label:'Deploy it yourself',actor:'operator',private_effect:'Codex waits for your deployment.'}]}}}};
    saved.jobs[id].status='failed';saved.jobs[id].stages.plan.status='failed';saved.jobs[id].stages.plan.recovery_id='rec';writeState(saved);
    await page.reload();await waitText('#detail h2','Question from Codex');
    await page.evaluate(()=>document.querySelector('input[type=radio][value=yes]').click());
    await page.type('.question textarea','Keep the regression test.');
    await page.evaluate(()=>{document.activeElement.blur();document.dispatchEvent(new CustomEvent('rerender'));});
    check(await page.$eval('.question textarea',el=>el.value)==='Keep the regression test.','Typed answer lost on re-render');
    await click('#detail button','Send answer');await page.waitForFunction(()=>!document.querySelector('.question'));
    saved=readState();check(saved.recoveries.rec.questions.q.answer.choice==='yes'&&saved.recoveries.rec.questions.q.answer.text==='Keep the regression test.','Answer not saved');

    // Ready to publish: its own calm group (publishing may wait), outside the badge; publication is one confirmed tap.
    saved.jobs[id].status='complete';saved.jobs[id].privacy='unlisted';
    for(const stage of Object.values(saved.jobs[id].stages))stage.status='complete';
    saved.jobs[id].stages.upload.result={video_id:'fixture0001',video_url:'https://www.youtube.com/watch?v=fixture0001',postprocessing_complete:true};
    saved.recoveries.rec.status='repaired';writeState(saved);
    await page.goto(base+'/#/');await waitText('#list .row-status','Ready to publish');
    check(await page.evaluate(()=>[...document.querySelectorAll('#list .group')].map(g=>g.querySelector('h2').textContent).join('|'))==='Ready to publish','Ready video is not in its own group');
    check((await page.title())==='Scotus videos','A video waiting to be published counts as needing attention');
    await page.screenshot({path:path.join(shots,'list.png'),fullPage:true});
    await click('#list .row-title','FDA v. Wages and White Lion Investments');
    await waitText('#detail h2','Ready to publish');await click('#detail button','Publish on YouTube');
    await waitText('#detail','Publication requested');
    check(Object.values(readState().jobs[id].video_actions)[0].kind==='publish','Publication not queued');
    const uppercase=await page.evaluate(()=>[...document.querySelectorAll('h1,h2,h3,summary,button')].some(el=>getComputedStyle(el).textTransform==='uppercase'));
    check(!uppercase,'Uppercase styling');

    await page.click('#repair-rec > summary');
    check(await page.$eval('#repair-history-rec',el=>!el.open),'Historical repair log starts expanded');
    await (await page.$('#repair-rec')).screenshot({path:path.join(shots,'repair-summary.png')});

    // Settings: slow Codex sign-in start, device code, then completion.
    await page.goto(base+'/#/settings');await waitText('.connection','Codex');
    await click('.connection button','Connect');
    await waitText('.guide','Waiting 1m');check(await page.evaluate(()=>[...document.querySelectorAll('.guide button')].some(b=>b.textContent==='Cancel sign-in')),'Startup cancellation is missing');
    fakeLogin={...fakeLogin,status:'pending',verification_url:'https://auth.openai.com/codex/device',user_code:'ABCD-1234'};
    await page.waitForFunction(()=>document.querySelector('.device-code')?.textContent==='ABCD-1234',{timeout:10000});
    fakeLogin={...fakeLogin,status:'complete'};
    await page.waitForFunction(()=>!document.querySelector('.guide')&&[...document.querySelectorAll('.toast')].some(t=>t.textContent==='Codex connected.'),{timeout:10000});
    await waitText('#detail','Notifications');

    saved=readState();saved.push_subscriptions={device:{id:'device',label:'iPhone, Home Screen app',created_at:new Date().toISOString(),last_sent_at:new Date().toISOString()}};writeState(saved);
    await page.reload();await waitText('#detail summary','Devices (1)');
    await click('#detail summary','Devices (1)');
    await page.waitForFunction(()=>document.getElementById('push-devices')?.open);
    await page.evaluate(()=>document.dispatchEvent(new CustomEvent('rerender')));
    check(await page.$eval('#push-devices',el=>el.open),'Device disclosure closed during re-render');
    await page.screenshot({path:path.join(shots,'settings-mobile.png'),fullPage:true});
    await page.setViewport({width:1280,height:900,isMobile:true,hasTouch:true});
    await page.waitForFunction(()=>document.getElementById('push-devices')?.open);
    // Viewport-driven renders can replace the disclosure while an element
    // screenshot scrolls it; capture the page without retaining a stale handle.
    await page.screenshot({path:path.join(shots,'settings-devices.png'),fullPage:true});
    await page.screenshot({path:path.join(shots,'settings-wide.png'),fullPage:true});

    // Wide screens show the list beside the selected recording.
    await page.setViewport({width:1280,height:900});
    await page.goto(base+'/#/case/'+encodeURIComponent(id));await waitText('#detail h1','FDA v. Wages');
    check(await page.evaluate(()=>getComputedStyle(document.getElementById('list')).display!=='none'&&!!document.querySelector('#list a[aria-current=page]')),'Two-pane layout missing');
    await page.screenshot({path:path.join(shots,'wide.png')});
    // TikTok controls use the same authenticated clip command route; no external
    // browser worker is configured in this throwaway server.
    saved=readState();saved.jobs[id].stages.plan.result={bundle_uri:'gs://fixture/bundle.tar.gz'};
    saved.jobs[id].clips={tk:{id:'tk',title:'A short passage',start:30,end:40,status:'ready',created_at:new Date().toISOString(),result:{video_uri:'gs://fixture/clip.mp4',credit:'Justice portraits: Oyez.org'}}};writeState(saved);
    await page.reload();await waitText('#detail h2','Vertical clips');
    await click('#detail summary','TikTok');
    check((await page.$eval('textarea[aria-label="TikTok caption"]',el=>el.value)).includes('A short passage'),'TikTok caption was not prefilled');
    await click('#detail button','Save TikTok draft');await waitText('#toasts','TikTok draft queued.');
    check(readState().jobs[id].clips.tk.status==='tiktok_draft_queued','TikTok draft not queued');
    saved=readState();saved.jobs[id].clips.tk.status='ready';saved.jobs[id].clips.tk.tiktok.saved=true;writeState(saved);
    await page.reload();await waitText('#detail','TikTok draft saved');
    await click('#detail button','Publish TikTok draft');await waitText('#toasts','TikTok publication queued.');
    check(readState().jobs[id].clips.tk.status==='tiktok_publish_queued','Confirmed TikTok publication not queued');
    await page.setViewport({width:390,height:844,isMobile:true,hasTouch:true});
    await page.screenshot({path:path.join(shots,'tiktok-mobile.png'),fullPage:true});
    saved=readState();saved.jobs[id].clips.tk.status='ready';writeState(saved);
    await page.reload();await waitText('#detail h2','Vertical clips');
    await click('#detail summary','Instagram');
    check((await page.$eval('textarea[aria-label="Instagram caption"]',el=>el.value)).includes('A short passage'),'Instagram caption was not prefilled');
    await click('#detail button','Publish on Instagram');await waitText('#toasts','Instagram publication started.');
    check(readState().jobs[id].clips.tk.status==='instagram_publish_queued','Confirmed Instagram publication not queued');
    saved=readState();saved.jobs[id].clips.tk.status='uploaded';saved.jobs[id].clips.tk.youtube={video_id:'STr6IuBQYss',video_url:'https://youtube.com/watch?v=STr6IuBQYss',privacy:'public'};saved.jobs[id].stages.upload.result={video_id:'RVlud1nKiXY'};writeState(saved);
    await page.reload();await waitText('#detail button','Link full argument');
    await click('#detail button','Link full argument');await waitText('#toasts','Full-video link requested.');
    check(readState().jobs[id].clips.tk.status==='youtube_link_queued','YouTube metadata link not queued');
    // A render revision preserves the old upload and offers the corrected MP4.
    saved=readState();saved.jobs[id].status='complete';saved.jobs[id].privacy='unlisted';saved.jobs[id].stages.upload.status='complete';saved.jobs[id].stages.upload.result.postprocessing_complete=true;
    saved.jobs[id].render_revision={status:'complete',version:1,upload_matches_current:false,existing_youtube_url:'https://www.youtube.com/watch?v=abcdefghijk'};writeState(saved);
    await page.reload();await waitText('#detail h2','Corrected render');
    check(await page.$eval('#detail',e=>e.innerText.includes('Download corrected MP4')&&e.innerText.includes('existing YouTube video is unchanged')),'Corrected render download/old upload notice missing');
    check(!await page.$eval('#detail',e=>[...e.querySelectorAll('button')].some(b=>b.textContent==='Publish on YouTube')),'Old upload presented as the corrected render ready to publish');
    check(await page.$eval('#detail',e=>e.innerText.includes('Upload corrected MP4 to YouTube')),'Explicit corrected upload action missing');
    saved=readState();saved.jobs[id].render_revision.upload_matches_current=true;writeState(saved);
    await page.reload();await waitText('#detail','The corrected MP4 is uploaded to YouTube.');
    check(!await page.$eval('#detail',e=>[...e.querySelectorAll('button')].some(b=>b.textContent==='Upload corrected MP4 to YouTube')),'Completed correction offered duplicate upload');
    // Infrastructure failures have a technical status, never an owner answer box.
    saved=readState();saved.statistics={status:'idle',count:756,pending:1,message:'Statistics published',questions:{},technical_errors:{'2026/25-498':{status:'retry_pending',notes:'RuntimeError: Object upload failed: HTTP 408'}}};writeState(saved);
    await page.goto(base+'/#/settings');await page.reload();await waitText('#detail','Automatic retry queued');
    check(!await page.$eval('#detail',e=>e.innerText.includes('Send answer')),'Technical failure offered an owner answer form');
    await page.goto(base+'/#/');await waitText('#list','Automatic retry queued');
    check(!await page.$eval('#list',e=>e.innerText.includes('Codex needs your input')),'Technical failure mislabeled as owner input');
    saved=readState();saved.statistics.questions={'2026/25-2':'Which opinion controls Part II?'};writeState(saved);
    await page.reload();await waitText('#list','Codex needs your input');
    await page.goto(base+'/#/settings');await waitText('#detail','Send answer');
    // On a slow connection, several cards ahead load before they enter the viewport.
    saved=readState();saved.jobs[id].annotation_revision_only=true;
    saved.jobs[id].review.cards=Array.from({length:8},(_,i)=>({id:'ahead-'+i,start:10+i*30,end:35+i*30,recommended:true,cue:{kind:'Statute'},card_uri:'gs://private/ahead-'+i+'.jpg',frame_uri:'gs://private/full-ahead-'+i+'.jpg',sources:[]}));
    saved.jobs[id].review.card_revision='prefetch-fixture';delete saved.jobs[id].cards_approved_revision;writeState(saved);
    previewDelay=300;peakPreviews=0;
    await page.setViewport({width:1440,height:900,isMobile:false,hasTouch:false});
    await page.goto(base+'/#/case/'+id);await waitText('#detail','Annotation cards to review');
    await page.$eval('.card-item',e=>e.scrollIntoView());
    await page.waitForFunction(()=>[...document.querySelectorAll('.card-image[src]')].some(e=>e.getBoundingClientRect().top>document.querySelector('#detail').getBoundingClientRect().bottom));
    check(peakPreviews>=3&&peakPreviews<=4,'Preview lookahead was serialized or exceeded its connection bound');
    if(errors.length)throw Error(errors.join('; '));
    console.log('Passed passkeys, adding and starting while paused, CSRF, legacy links, card and portrait review, photo feedback, title choice, answering Codex with drafts kept, publication, Codex device login and the two-pane layout.');
  }catch(error){
    if(page){await page.screenshot({path:path.join(shots,'failure.png'),fullPage:true}).catch(()=>{});
      console.error('Original browser failure:',error.stack);console.error('Page at failure:',await page.evaluate(()=>location.href).catch(()=>'(closed)'),await page.evaluate(()=>document.body.innerText.slice(0,1500)).catch(()=>''));}
    throw error;
  }finally{await browser.close();server.kill();fs.rmSync(dir,{recursive:true,force:true});}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
