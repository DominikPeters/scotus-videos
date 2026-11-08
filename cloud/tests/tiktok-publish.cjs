// Test the observed optional-check confirmation without contacting TikTok.
const puppeteer=require('puppeteer'),assert=require('assert');
const {finishPublicPost}=require('../render/tiktok-draft.cjs');
(async()=>{
 const browser=await puppeteer.launch({headless:'new'});
 try{
  const page=await browser.newPage();await page.setRequestInterception(true);
  page.on('request',r=>r.respond({status:200,contentType:'text/html',body:`<p>Continue to post?</p><p>We're still checking your video for potential issues.</p><button onclick="history.replaceState(null,'','/tiktokstudio/content');document.body.textContent='Posted';">Post now</button>`}));
  await page.goto('http://localhost/tiktokstudio/upload');await finishPublicPost(page);
  assert(page.url().includes('/content'));assert.equal(await page.$eval('body',el=>el.textContent),'Posted');
  await finishPublicPost(page); // Already arrived: no second click.
  await page.goto('http://localhost/tiktokstudio/upload');
  await page.$eval('p:nth-child(2)',el=>el.textContent='A different warning');
  await assert.rejects(finishPublicPost(page), /Unknown posting confirmation/);
  assert(page.url().includes('/upload'));
  console.log('Passed optional posting confirmation, already-posted navigation and unknown-dialog rejection.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
