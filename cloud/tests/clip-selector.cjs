// Focused browser check: node cloud/tests/clip-selector.cjs
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert'),puppeteer=require('puppeteer');
const root=path.resolve(__dirname,'../dashboard/public');
const fixture={sections:[{turns:[{speaker:{name:'Justice Kagan'},text_blocks:Array.from({length:140},(_,i)=>({start:i*10,stop:i*10+9,text:'Passage '+i+' with enough words to choose a useful clip.'}))}]}]};
(async()=>{
 const server=http.createServer((req,res)=>{
  const url=new URL(req.url,'http://localhost');
  if(url.pathname==='/fixture.json'){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify(fixture));}
  if(url.pathname==='/'){res.setHeader('Content-Type','text/html');return res.end(`<link rel="stylesheet" href="app.css"><meta name="viewport" content="width=device-width,initial-scale=1"><main id="target"></main><div id="toasts"></div><script type="module">
   import {clipsBlock} from './view-clips.js';import {onRefresh} from './ui.js';
   window.refreshes=0;onRefresh(()=>{window.refreshes++});
   const job={id:'test',case_name:'Test case',clips:{},stages:{plan:{result:{bundle_uri:'fixture'}}},podcast_alignment:{url:'/fixture.json'}};
   window.render=()=>document.querySelector('#target').replaceChildren(clipsBlock(job));window.render();
  </script>`);}
  const file=path.join(root,url.pathname);if(!file.startsWith(root+'/')||!fs.existsSync(file)){res.statusCode=404;return res.end();}
  res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'application/octet-stream');res.end(fs.readFileSync(file));
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));let browser;
 try{
  browser=await puppeteer.launch({headless:'new',protocolTimeout:30000});const page=await browser.newPage();await page.setViewport({width:390,height:844});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('http://127.0.0.1:'+server.address().port);
  await page.waitForSelector('.clip-form');await page.evaluate(()=>document.querySelectorAll('details').forEach(d=>d.querySelector('summary').click()));
  await page.evaluate(()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Load transcript').click());
  await page.waitForSelector('.clip-passage:nth-child(140)');
  const result=await page.evaluate(async()=>{
   const list=document.querySelector('.clip-passages'),row=list.children[100];list.scrollTop=10000;
   const before=list.scrollTop;row.querySelector('.clip-boundaries button').click();row.querySelector('.clip-boundaries button:last-child').click();
   const after=list.scrollTop,values=[...document.querySelectorAll('.clip-times input')].map(e=>e.value);window.render();await Promise.resolve();
   return {before,after,restored:document.querySelector('.clip-passages').scrollTop,values,refreshes:window.refreshes};
  });
  assert.deepEqual(result.values,['1000','1009']);assert.equal(result.before,result.after);assert.equal(result.before,result.restored);assert.equal(result.refreshes,1,'Only loading may refresh; boundary selection must be local');
  await page.evaluate(()=>{const search=document.querySelector('input[type=search]');search.value='Passage 139';search.dispatchEvent(new Event('input',{bubbles:true}));});assert.equal(await page.$$eval('.clip-passage:not([hidden])',els=>els.length),1);
  console.log('Selector assertions passed; capturing mobile preview.');
  await page.screenshot({path:'/tmp/scotus-clip-selector-mobile.png',fullPage:true});assert.deepEqual(errors,[]);console.log('Passed full transcript, local boundary selection, range values, scroll retention on rerender and search.');
 }finally{if(browser)await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1});
