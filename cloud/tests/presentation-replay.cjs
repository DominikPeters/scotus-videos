// Uses only existing local assets and case data. No network or model downloads.
const fs=require('fs'),path=require('path'),os=require('os'),crypto=require('crypto');
const driver=require('../render/original.js');
const repo=path.resolve(__dirname,'../..'),root=fs.mkdtempSync(path.join(os.tmpdir(),'scotus-presentation-replay-'));
const id='63775',hash=buffer=>crypto.createHash('sha256').update(buffer).digest('hex');
(async()=>{
 const sources=JSON.parse(fs.readFileSync(path.join(repo,'cloud/presentation/sources.json')));
 for(const name of ['index.html','script.js']){const copied=fs.readFileSync(path.join(repo,'cloud/presentation/renderer',name));if(hash(copied)!==sources['renderer/'+name].sha256)throw Error('Presentation checksum differs: '+name);fs.writeFileSync(path.join(root,name),copied);}
 fs.cpSync(path.join(repo,'cloud/presentation/renderer/maps'),path.join(root,'maps'),{recursive:true});
 for(const name of ['json','advocates','justices','fonts','seal.svg','subscribe.png'])if(fs.existsSync(path.join(repo,name)))fs.symlinkSync(path.join(repo,name),path.join(root,name));
 const assets=JSON.parse(fs.readFileSync(path.join(repo,'cloud/presentation/renderer/assets.json')));for(const name of Object.keys(assets)){const target=path.join(root,name);if(!fs.existsSync(target)){fs.mkdirSync(path.dirname(target),{recursive:true});fs.symlinkSync(path.join(repo,name),target);}}
 const {page,browser,server}=await driver.open(root,id);
 try{
  const peer=await browser.newPage();await peer.setViewport({width:1920,height:1080,deviceScaleFactor:2});await peer.goto(`http://localhost:8002/?case=${id}`);await peer.waitForSelector('#loading-finished');await peer.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(image=>image.decode().catch(()=>{})));});
  // Compare independent original function execution against the adapter, including scroll states.
  const commands=[{name:'showSplash'},{name:'goToNextSection'}];let checks=0,scrolls=0,sections=0;
  for(const command of commands){await driver.action(page,command);await peer.evaluate(command=>window[command.name](),command);}
  while(true){
   const result=await driver.action(page,{name:'nextTextBlock'});const expected=await peer.evaluate(()=>nextTextBlock());await peer.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(image=>image.decode().catch(()=>{})));});
   if(JSON.stringify(result)!==JSON.stringify(expected))throw Error('Original transition timing differs');
   if(checks<4||(result.frameInfo.length&&scrolls<4)||result.goToNextSection){const a=await page.screenshot(),b=await peer.screenshot();if(hash(a)!==hash(b)){fs.writeFileSync('/tmp/scotus-parity-adapter.png',a);fs.writeFileSync('/tmp/scotus-parity-reference.png',b);fs.writeFileSync('/tmp/scotus-parity-dom.json',JSON.stringify([await page.content(),await peer.content()]));throw Error('Original pixels differ at state '+checks);}checks++;}
   for(const [amount]of result.frameInfo){await driver.action(page,{name:'scrollTranscript',args:[amount]});await peer.evaluate(amount=>scrollTranscript(amount),amount);if(scrolls<4&&hash(await page.screenshot())!==hash(await peer.screenshot()))throw Error('Scroll frame differs');scrolls++;}
   if(result.goToNextSection){await driver.action(page,{name:'goToNextSection'});await peer.evaluate(()=>goToNextSection());sections++;}
   else if(result.lastTurn)break;
   if(checks>=8&&scrolls>=4&&sections>=1)break;
  }
  // Rebuild the same state from an operation log, as a new parallel chunk does.
  console.log(JSON.stringify({presentation_source_checks:true,pixel_checks:checks,scroll_checks:scrolls,section_transitions:sections}));
 }finally{await browser.close();server.close();fs.rmSync(root,{recursive:true,force:true});}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
