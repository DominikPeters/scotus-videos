'use strict';
// Workflow adapter only. index.html and script.js are the original, hashed files.
const fs=require('fs'),path=require('path'),http=require('http'),puppeteer=require('puppeteer'),{spawnSync}=require('child_process');
const {splitProgressEvent}=require('./progress');
// Temporary frames favor capture speed over PNG compression; pixels stay lossless.
const screenshotOptions={type:'png',optimizeForSpeed:true};
function serverFor(root){return http.createServer((req,res)=>{
 try{let pathname=decodeURIComponent(new URL(req.url,'http://localhost').pathname);if(pathname==='/')pathname='/index.html';
 const target=path.resolve(root,'.'+pathname);if(!target.startsWith(root+path.sep)||!fs.statSync(target).isFile())throw Error();
 res.writeHead(200,{'Content-Type':({'.html':'text/html','.js':'text/javascript','.json':'application/json','.svg':'image/svg+xml','.jpg':'image/jpeg','.png':'image/png','.otf':'font/otf','.ttf':'font/ttf'})[path.extname(target).toLowerCase()]||'application/octet-stream'});fs.createReadStream(target).pipe(res);
 }catch{res.writeHead(404);res.end();}});}
async function open(root,id,vertical=false){
 const server=serverFor(root);await new Promise(resolve=>server.listen(8002,'127.0.0.1',resolve));
 const browser=await puppeteer.launch({headless:'new',executablePath:process.env.PUPPETEER_EXECUTABLE_PATH||undefined,args:process.env.CLOUD_RUN_JOB?['--no-sandbox','--disable-dev-shm-usage']:[]});
 const page=await browser.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message));await page.setRequestInterception(true);page.on('request',request=>{const url=request.url();if(url.startsWith('http://localhost:8002/')||url.startsWith('data:'))request.continue();else request.abort();});await page.setViewport(vertical?{width:1080,height:1920,deviceScaleFactor:1}:{width:1920,height:1080,deviceScaleFactor:2});
 await page.goto(`http://localhost:8002/${vertical?'vertical.html':''}?case=${id}`);await page.waitForSelector('#loading-finished');
 await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(img=>img.decode().catch(()=>{})));});
 if(errors.length)throw Error('Original presentation initialization failed: '+errors[0]);
 return {page,browser,server};
}
async function action(page,op){return page.evaluate(async op=>{
 if(op.name==='fitVertical'){
  const title=document.querySelector('div.title h1'),seal=document.querySelector('div.title > img');
  const width=1080-40-(seal?.getBoundingClientRect().width||130)-20;
  let size=60;title.style.fontSize=size+'px';
  while(title.scrollWidth>width&&size>40){size-=.5;title.style.fontSize=size+'px';}
  if(title.scrollWidth>width){
   // Too long for one readable line: two balanced lines rather than shrinking further.
   const ratio=title.getBoundingClientRect().height/size,lines=()=>Math.round(title.getBoundingClientRect().height/(ratio*size));
   Object.assign(title.style,{whiteSpace:'normal',textWrap:'balance',maxWidth:width+'px'});
   document.querySelector('div.title-text').style.minWidth='0';document.querySelector('div.title').style.height='auto';
   size=50;title.style.fontSize=size+'px';
   while((lines()>2||title.scrollWidth>width)&&size>18){size-=.5;title.style.fontSize=size+'px';}
  }
  document.querySelector('.subtitle').style.visibility='visible';
  document.querySelector('div.title-text').style.minWidth='0';
  document.getElementById('transcript').style.height=(1920-document.querySelector('div.header').getBoundingClientRect().height)+'px';
  return;
 }
 if(op.name==='setInteractionProgress'){
  const [section,index,percent]=op.args;
  if(!Number.isFinite(percent))throw Error('Invalid interaction progress');
  if(currentSection===section&&currentInteraction===index){
   const image=document.getElementById('interaction-'+index)?.children[0];
   if(image)image.style.setProperty('--percent',Math.max(0,Math.min(100,percent))+'%');
  }
  return;
 }
 const allowed={...(typeof setQuoteProgress==='function'?{setQuoteProgress}:{}),showSplash,goToNextSection,nextTextBlock,scrollTranscript,showConclusion,announceNextArgument,announceOpinionAnnouncements,loadNextOpinionAnnouncement};
 const response=allowed[op.name](...(op.args||[]));
 if(window.scotusCredit){const ack=document.querySelector('.acknowledgement');ack.textContent=window.scotusCredit.text;ack.style.display=window.scotusCredit.text?'':'none';}
 await document.fonts.ready;
 window.scotusDecodedImages ||= new WeakMap();
 await Promise.all([...document.images].map(image=>{const source=image.src+' '+image.srcset;const cached=window.scotusDecodedImages.get(image);if(cached?.source===source)return cached.ready;const ready=image.decode().catch(()=>{});window.scotusDecodedImages.set(image,{source,ready});return ready;}));
 return response;
},op);}
async function setupCredit(page,credit){await page.evaluate(credit=>{window.scotusCredit=credit;},credit);}
async function interactionProgress(page){return page.evaluate(()=>{
 if(announcementMode||currentInteraction<0||!document.getElementById('conversation').getBoundingClientRect().width)return null;
 const interaction=interactions_data.sections[currentSection].interactions[currentInteraction];
 const image=document.getElementById('interaction-'+currentInteraction)?.children[0];
 if(!interaction||!image)return null;
 return {section:currentSection,interaction:currentInteraction,start:interaction.startTime,end:interaction.endTime,width:image.getBoundingClientRect().width};
});}
async function plan(root,id,out){const {page,browser,server}=await open(root,id);try{
 const credit=JSON.parse(fs.readFileSync(path.join(root,'credit.json')));await setupCredit(page,credit);
 await page.screenshot({...screenshotOptions,path:path.join(root,'thumbnail.png')});
 const events=[];let cursor=0,audioCursor=0;const pending=[];
 const op=async(name,args=[])=>{const command={name,args};pending.push(command);const response=await action(page,command);
  if(name==='nextTextBlock'&&response)audioCursor=await page.evaluate(()=>sectionsObject[currentSection].turns[currentTurn].text_blocks[currentTextBlock].start);
  return response;
 };
 const save=async duration=>{if(!Number.isFinite(duration)||duration<0)throw Error('Invalid original frame duration');const first=Math.round(cursor*20);cursor+=duration;const end=Math.round(cursor*20);
  const info=await interactionProgress(page);events.push(...splitProgressEvent({ops:pending.splice(0),first_frame:first,end_frame:end},info,audioCursor));audioCursor+=duration;
 };
 await op('showSplash');await op('goToNextSection');let first=true;
 while(true){const response=await op('nextTextBlock');if(!response)throw Error('Original renderer ended unexpectedly');
  if(first){
   // Original intro occupies the first min(5, first block duration) seconds.
   // Record it separately before applying the first text-block command.
   const commands=pending.splice(0);events.push({ops:[commands[0]],first_frame:0,end_frame:Math.round(Math.min(5,response.duration)*20)});
   cursor=Math.min(5,response.duration);audioCursor+=cursor;pending.push(...commands.slice(1));response.duration-=cursor;first=false;
  }
  await save(response.duration);
  for(const [amount,duration,quote]of response.frameInfo){await op('scrollTranscript',[amount]);if(quote!==undefined&&quote!==null)await op('setQuoteProgress',[quote]);await save(duration);}
  if(response.goToNextSection){const info=await page.evaluate(current=>{const next=current+1;return {different:(sectionsObject[next].argument_index||0)>(sectionsObject[current].argument_index||0),title:sectionsObject[next].argument_title};},response.currentSection||0);if(info.different){await op('announceNextArgument',[info.title]);await save(3);}await op('goToNextSection');}
  else if(response.lastTurn)break;
 }
 // The existing screenshot workflow calls showConclusion without returning its result.
 // Preserve its timeline; the opinion path adds its own concluding frame below.
 await op('showConclusion');
 const interactions=JSON.parse(fs.readFileSync(path.join(root,`json/${id}-interactions.json`)));
 if(interactions.announcements?.length){await op('announceOpinionAnnouncements');await save(8);for(const ignored of interactions.announcements){await op('loadNextOpinionAnnouncement');while(true){const response=await op('nextTextBlock');await save(response.duration);for(const [amount,duration,quote]of response.frameInfo){await op('scrollTranscript',[amount]);if(quote!==undefined&&quote!==null)await op('setQuoteProgress',[quote]);await save(duration);}if(response.goToNextSection)await op('goToNextSection');else if(response.lastTurn)break;}}await op('showConclusion');await save(5);}
 const total=Math.round(cursor*20),size=6000,chunks=[];for(let first=0;first<total;first+=size)chunks.push({index:chunks.length,first_frame:first,end_frame:Math.min(total,first+size)});
 fs.writeFileSync(out,JSON.stringify({schema_version:2,renderer:'original',case_id:id,fps:20,total_frames:total,events,chunks}));
 }finally{await browser.close();server.close();}}
async function chunk(root,planPath,index,out){const data=JSON.parse(fs.readFileSync(planPath)),part=data.chunks[index],{page,browser,server}=await open(root,data.case_id,data.layout==='vertical');const folder=out+'.frames';fs.mkdirSync(folder,{recursive:true});try{
 await setupCredit(page,JSON.parse(fs.readFileSync(path.join(root,'credit.json'))));const rows=[];let image=0;
 for(const event of data.events){for(const op of event.ops)await action(page,op);const first=Math.max(part.first_frame,event.first_frame),end=Math.min(part.end_frame,event.end_frame);if(end<=first)continue;
  const file=`frame-${String(image++).padStart(6,'0')}.png`;await page.screenshot({...screenshotOptions,path:path.join(folder,file)});rows.push(`file '${file}'\noption framerate 20\nduration ${(end-first)/20}`);if(image===1)fs.copyFileSync(path.join(folder,file),out.replace(/\.mp4$/,'-preview.png'));console.log(JSON.stringify({progress:(end-part.first_frame)/(part.end_frame-part.first_frame)}));if(event.end_frame>=part.end_frame)break;
 }
 if(!rows.length)throw Error('Empty original render range');rows.push(rows.at(-1).split('\n')[0]+'\noption framerate 20');const list=path.join(folder,'frames.txt');fs.writeFileSync(list,rows.join('\n')+'\n');
 const result=spawnSync('ffmpeg',['-nostdin','-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',list,'-vf','fps=20','-frames:v',String(part.end_frame-part.first_frame),'-an','-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p',out],{stdio:'inherit'});if(result.status)throw Error('Encoding failed');
 const probe=spawnSync('ffprobe',['-v','error','-select_streams','v:0','-show_entries','stream=nb_frames,codec_name,width,height,r_frame_rate,time_base,profile','-of','json',out],{encoding:'utf8'});if(probe.status)throw Error('Encoded chunk probe failed');const stream=JSON.parse(probe.stdout).streams[0];if(Number(stream.nb_frames)!==part.end_frame-part.first_frame||stream.width!==(data.width||3840)||stream.height!==(data.height||2160)||stream.r_frame_rate!=='20/1')throw Error('Encoded frame metadata or geometry differs');delete stream.nb_frames;
 fs.writeFileSync(out+'.receipt.json',JSON.stringify({frames:part.end_frame-part.first_frame,first_frame:part.first_frame,end_frame:part.end_frame,stream,renderer:'original'}));
 }finally{await browser.close();server.close();fs.rmSync(folder,{recursive:true,force:true});}}
async function cardPreview(root,id,block,out){const {page,browser,server}=await open(root,id);try{
 await setupCredit(page,JSON.parse(fs.readFileSync(path.join(root,'credit.json'))));
 await action(page,{name:'showSplash'});await action(page,{name:'goToNextSection'});
 let response;
 for(let i=0;i<=block;i++){response=await action(page,{name:'nextTextBlock'});if(!response)throw Error('Missing preview block');if(i<block&&response.goToNextSection)await action(page,{name:'goToNextSection'});}
 const cue=JSON.parse(fs.readFileSync(path.join(root,`json/${id}-cards.json`))).cues[0];
 for(let attempt=0;attempt<100;attempt++){
  const current=await page.evaluate(()=>({id:activeQuoteCue?.id,time:sectionsObject[currentSection].turns[currentTurn].text_blocks[currentTextBlock].start}));
  if(current.id===cue.id)break;
  if(current.time>=cue.end||response.lastTurn)throw Error('No readable block inside the card window');
  if(response.goToNextSection)await action(page,{name:'goToNextSection'});
  response=await action(page,{name:'nextTextBlock'});
 }
 if(!(await page.evaluate(id=>activeQuoteCue?.id===id,cue.id)))throw Error('Card did not appear');
 await page.evaluate(()=>{if(quoteSwap)setQuoteProgress({swap:1});else setQuoteProgress(1);});
 await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(img=>img.decode().catch(()=>{})));});
 const metrics=await page.evaluate(()=>{const el=document.getElementById('quote-body');const rect=el.getBoundingClientRect();const range=document.createRange();range.selectNodeContents(el);const ink=range.getBoundingClientRect();return {width:rect.width,height:rect.height,font_size:parseFloat(getComputedStyle(el).fontSize),scroll_height:el.scrollHeight,client_height:el.clientHeight,scroll_width:el.scrollWidth,client_width:el.clientWidth,overflow:ink.bottom>rect.bottom+1||ink.right>rect.right+1||el.scrollWidth>el.clientWidth+2,visible:rect.height>0&&rect.width>0};});
 fs.writeFileSync(out+'.json',JSON.stringify(metrics));
 if(!metrics.visible||metrics.overflow){await page.screenshot({type:'jpeg',quality:85,path:out});throw Error('Card preview does not fit: '+JSON.stringify(metrics));}
 await page.screenshot({type:'jpeg',quality:85,path:out});
 const element=await page.$('#quote-card');const box=await element.boundingBox();await page.screenshot({type:'jpeg',quality:90,path:out+'.card.jpg',clip:box});
 fs.writeFileSync(out+'.json',JSON.stringify(metrics));
 }finally{await browser.close();server.close();}}
module.exports={open,action,setupCredit,interactionProgress,plan,chunk,cardPreview};
if(require.main===module){
 const [mode,rootArg,idOrPlan,indexOrOut,out]=process.argv.slice(2),root=path.resolve(rootArg);
 (mode==='plan'?plan(root,idOrPlan,indexOrOut):mode==='card'?cardPreview(root,idOrPlan,Number(indexOrOut),out):chunk(root,idOrPlan,Number(indexOrOut),out)).catch(error=>{console.error(error.message);process.exitCode=1;});
}
