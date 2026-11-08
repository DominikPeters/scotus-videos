'use strict';
const fs=require('fs'),path=require('path'),http=require('http'),{spawnSync}=require('child_process'),puppeteer=require('puppeteer');
const [bundle,planPath,indexString,output]=process.argv.slice(2);
if(!bundle||!output)throw Error('Usage: node chunk.js BUNDLE PLAN INDEX OUTPUT');
const root=path.resolve(bundle),plan=JSON.parse(fs.readFileSync(planPath)),chunk=plan.chunks[Number(indexString)];
if(!chunk)throw Error('Unknown render chunk');
const mime={'.html':'text/html','.css':'text/css','.js':'text/javascript','.json':'application/json','.png':'image/png','.jpg':'image/jpeg','.webp':'image/webp','.svg':'image/svg+xml'};
const server=http.createServer((req,res)=>{try{const relative=decodeURIComponent(new URL(req.url,'http://localhost').pathname);const file=path.resolve(root,'.'+relative);if(!file.startsWith(root+path.sep)||!fs.statSync(file).isFile()){res.writeHead(404);return res.end();}res.writeHead(200,{'Content-Type':mime[path.extname(file)]||'application/octet-stream'});fs.createReadStream(file).pipe(res);}catch{res.writeHead(404);res.end();}});
(async()=>{
  let browser;const frames=path.join(path.dirname(output),`frames-${chunk.index}`);fs.mkdirSync(frames,{recursive:true});
  try{
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
    browser=await puppeteer.launch({headless:'new',executablePath:process.env.PUPPETEER_EXECUTABLE_PATH||undefined,args:process.env.CLOUD_RUN_JOB?['--no-sandbox','--disable-dev-shm-usage']:[]});
    const page=await browser.newPage(),manifest=JSON.parse(fs.readFileSync(path.join(root,'manifest.json'))),render=manifest.render||{};
    await page.setViewport({width:1920,height:1080,deviceScaleFactor:(render.width||3840)/1920});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/player.html`);await page.evaluate(()=>window.ready);
    const points=[chunk.first_frame,...plan.events.map(e=>e.frame).filter(f=>f>chunk.first_frame&&f<chunk.end_frame),chunk.end_frame];
    const durations=[];let savedActivePreview=false;
    for(let i=0;i<points.length-1;i++){
      const state=await page.evaluate(time=>window.renderAt(time),points[i]/plan.fps);
      const name=`frame-${String(i).padStart(5,'0')}.png`;await page.screenshot({path:path.join(frames,name)});
      if(i===0 || (!savedActivePreview && state.paragraph>=0)){fs.copyFileSync(path.join(frames,name),output.replace(/\.mp4$/,'-preview.png'));if(state.paragraph>=0)savedActivePreview=true;}
      durations.push(`file '${name}'\noption framerate ${plan.fps}\nduration ${(points[i+1]-points[i])/plan.fps}`);
      process.stdout.write(JSON.stringify({progress:(i+1)/(points.length-1)})+'\n');
    }
    if(errors.length)throw Error(errors.join('; '));
    durations.push(`file 'frame-${String(points.length-2).padStart(5,'0')}.png'\noption framerate ${plan.fps}`);
    const list=path.join(frames,'frames.txt');fs.writeFileSync(list,durations.join('\n')+'\n');
    const result=spawnSync('ffmpeg',['-nostdin','-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',list,'-r',String(plan.fps),'-fps_mode','cfr','-frames:v',String(chunk.end_frame-chunk.first_frame),'-an','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-g','100','-keyint_min','100','-sc_threshold','0','-bf','0','-video_track_timescale','10240',output],{stdio:'inherit'});
    if(result.status!==0)throw Error('Video encoding failed');
    const probe=spawnSync('ffprobe',['-v','error','-select_streams','v:0','-count_frames','-show_entries','stream=nb_read_frames,width,height,r_frame_rate,codec_name,time_base','-of','json',output],{encoding:'utf8'});
    if(probe.status!==0)throw Error('Chunk verification failed');const stream=JSON.parse(probe.stdout).streams[0];
    if(Number(stream.nb_read_frames)!==chunk.end_frame-chunk.first_frame)throw Error('Chunk frame count differs');
    fs.writeFileSync(output+'.receipt.json',JSON.stringify({chunk,...stream,frames:Number(stream.nb_read_frames),manifest_sha256:plan.manifest_sha256})+'\n');
  }finally{if(browser)await browser.close();server.close();fs.rmSync(frames,{recursive:true,force:true});}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
