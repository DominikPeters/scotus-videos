#!/usr/bin/env node
// Deterministic frame export: split at BOTH transcript and artifact boundaries.
const fs = require('fs');
const path = require('path');
const http = require('http');
const {spawnSync} = require('child_process');
const puppeteer = require('puppeteer');

const ROOT = path.resolve(__dirname, '..');
function option(name, fallback) {
    const i = process.argv.indexOf(`--${name}`);
    if (i < 0) return fallback;
    if (!process.argv[i + 1] || process.argv[i + 1].startsWith('--')) throw Error(`--${name} needs a value`);
    return process.argv[i + 1];
}
const caseID = option('case', '25A312');
if (!/^[A-Za-z0-9-]+$/.test(caseID)) throw Error('Invalid case ID');
const folder = path.join(ROOT, 'artifacts/output', caseID);
const preview = path.join(folder, 'preview');
const prepared = spawnSync(process.env.PYTHON || 'python3',[path.join(__dirname,'prepare_preview.py'),'--case',caseID],{encoding:'utf8'});
if(prepared.status!==0) throw Error(prepared.stderr || 'Could not prepare preview assets');
const manifest = JSON.parse(fs.readFileSync(path.join(folder, 'manifest.json')));
const start = Number(option('start', Math.max(0, manifest.cues[0]?.start - 5 || 0)));
const end = Number(option('end', start + 60));
if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) throw Error('Require 0 <= start < end');
const output = path.resolve(option('output', path.join(folder, 'demo.mp4')));
const frames = fs.mkdtempSync(path.join(folder, 'render-'));
const mime = {'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.mp3':'audio/mpeg','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg'};
const server = http.createServer((req, res) => {
    try {
        const file = path.resolve(preview, '.' + decodeURIComponent(new URL(req.url, 'http://localhost').pathname));
        if (!file.startsWith(preview + path.sep) || !fs.statSync(file).isFile()) {res.writeHead(404);res.end();return;}
        const size=fs.statSync(file).size;
        const range=/^bytes=(\d+)-(\d*)$/.exec(req.headers.range || '');
        const headers={'Content-Type':mime[path.extname(file)] || 'application/octet-stream','Accept-Ranges':'bytes'};
        if(range) {
            const begin=Number(range[1]), finish=range[2] ? Math.min(size-1,Number(range[2])) : size-1;
            if(begin>=size || finish<begin){res.writeHead(416,{'Content-Range':`bytes */${size}`});res.end();return;}
            res.writeHead(206,{...headers,'Content-Length':finish-begin+1,'Content-Range':`bytes ${begin}-${finish}/${size}`});
            fs.createReadStream(file,{start:begin,end:finish}).pipe(res);
        } else {res.writeHead(200,{...headers,'Content-Length':size});fs.createReadStream(file).pipe(res);}
    } catch {res.writeHead(404);res.end();}
});

(async () => {
    let browser;
    try {
        await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
        const port=server.address().port;
        browser=await puppeteer.launch({headless:'new', protocolTimeout:240000, ...(process.env.PUPPETEER_EXECUTABLE_PATH ? {executablePath:process.env.PUPPETEER_EXECUTABLE_PATH}: {})});
        const page=await browser.newPage();
        await page.setViewport({width:1920,height:1080,deviceScaleFactor:1});
        const errors=[];
        page.on('pageerror',error=>errors.push(error.message));
        await page.goto(`http://127.0.0.1:${port}/artifact-player.html?case=${caseID}&render=1&t=${start}`);
        await page.evaluate(()=>window.artifactReady);
        await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(img=>img.complete?Promise.resolve():new Promise(resolve=>{img.onload=resolve;img.onerror=resolve;})));});
        const rows=await page.evaluate(()=>window.artifactData.rows);
        if(process.argv.includes('--check')) {
            const result=await page.evaluate(async()=>{
                const {manifest,rows}=window.artifactData;
                let checks=0;
                for(const cue of manifest.cues) {
                    for(const t of [Math.max(0,cue.start-.001),cue.start,cue.end-.001,cue.end,cue.start]) {
                        await window.artifactRenderAt(t);
                        const expected=manifest.cues.find(c=>c.start<=t && t<c.end);
                        const excerpt=document.getElementById('excerpt');
                        const image=document.getElementById('document-image');
                        if(excerpt.hidden===Boolean(expected)) throw Error(`Wrong panel visibility at ${t}`);
                        if(expected && (!image.src.endsWith(expected.image) || image.naturalWidth===0)) throw Error(`Wrong or unloaded source image at ${t}`);
                        const active=document.querySelector('.speech.current p');
                        const expectedRow=rows.filter(b=>b.start<=t).at(-1);
                        if(expectedRow && active?.textContent!==expectedRow.text) throw Error(`Wrong transcript after seek at ${t}`);
                        checks++;
                    }
                }
                for(const url of ['/credentials.json','/client_secret.json','/artifacts/pipeline.py']) {
                    if((await fetch(url)).status!==404) throw Error(`Unexpected non-public file ${url}`);
                    checks++;
                }
                return checks;
            });
            if(errors.length) throw Error(errors.join('; '));
            const qa=path.join(folder,'qa');
            fs.mkdirSync(qa,{recursive:true});
            for(const cue of manifest.cues) {
                await page.evaluate(t=>window.artifactRenderAt(t),cue.start);
                await page.screenshot({path:path.join(qa,`${cue.id}.png`)});
            }
            fs.rmSync(frames,{recursive:true,force:true});
            console.log(`Passed ${result} browser checks: excerpt boundaries, backward seeks, transcript state, image loading, and public-bundle scope.`);
            return;
        }
        const duration=Math.max(...rows.map(b=>b.stop || b.start));
        if(end>duration) throw Error(`Requested end ${end} exceeds transcript length ${duration}`);
        const points=[start,end,...rows.flatMap(b=>[b.start,b.stop]),...manifest.cues.flatMap(c=>[c.start,c.end])];
        const boundaries=[...new Set(points.filter(x=>Number.isFinite(x) && x>=start && x<=end))].sort((a,b)=>a-b);
        const durations=[];
        let posterFrame=null;
        for(let i=0;i<boundaries.length-1;i++) {
            const t=boundaries[i], next=boundaries[i+1];
            const state=await page.evaluate(t=>window.artifactRenderAt(t),t);
            const file=`frame-${String(i).padStart(5,'0')}.png`;
            await page.screenshot({path:path.join(frames,file)});
            if(state.cue && !posterFrame) posterFrame=file;
            // Only transcript/source transitions need a new frame; clock is frozen between them.
            durations.push(`file '${file}'\nduration ${(next-t).toFixed(6)}`);
            console.log(`${t.toFixed(2)}-${next.toFixed(2)}s: ${state.cue || 'speaker'}`);
        }
        if(errors.length) throw Error(`Browser errors: ${errors.join('; ')}`);
        durations.push(`file 'frame-${String(boundaries.length-2).padStart(5,'0')}.png'`);
        const concat=path.join(frames,'frames.txt');
        fs.writeFileSync(concat,durations.join('\n')+'\n');
        const audio=path.join(ROOT,manifest.audio.replace(/^\//,''));
        fs.mkdirSync(path.dirname(output),{recursive:true});
        const result=spawnSync('ffmpeg',['-y','-hide_banner','-loglevel','warning','-f','concat','-safe','0','-i',concat,'-ss',String(start),'-t',String(end-start),'-i',audio,'-t',String(end-start),'-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-vf','fps=20','-c:a','aac','-b:a','160k','-movflags','+faststart',output],{stdio:'inherit'});
        if(result.status!==0) throw Error('ffmpeg failed');
        fs.copyFileSync(path.join(frames,posterFrame || 'frame-00000.png'),output.replace(/\.mp4$/i,'')+'-preview.png');
        fs.rmSync(frames,{recursive:true,force:true});
        console.log(`Rendered ${end-start}s to ${output}`);
    } finally {
        if(browser) await browser.close();
        server.close();
    }
})().catch(error=>{console.error(error.message);process.exitCode=1;});
