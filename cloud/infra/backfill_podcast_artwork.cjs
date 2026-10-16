'use strict';
// Local-only batch. Reads existing metadata/portraits; never fetches or uploads.
const fs=require('fs'),path=require('path'),os=require('os'),puppeteer=require('puppeteer');
const {render}=require('../render/podcast');
const root=path.resolve(__dirname,'../..');
const podcast=path.resolve(process.argv[2]||path.join(root,'../scotus-podcast/data/case_data.json'));
const output=path.resolve(process.argv[3]||path.join(root,'artifacts/output/podcast-artwork-backfill'));
const normalize=s=>s.normalize('NFKD').replace(/[^a-z0-9]/gi,'').toLowerCase();
const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function main(){
 fs.mkdirSync(output,{recursive:true});
 const episodes=JSON.parse(fs.readFileSync(podcast));
 const metadata=new Map();
 for(const file of fs.readdirSync(path.join(root,'json')).filter(f=>/^\d+\.json$/.test(f))){
  const data=JSON.parse(fs.readFileSync(path.join(root,'json',file)));
  if(data.term&&data.docket_number)metadata.set(data.term+':'+data.docket_number,data);
 }
 const cached=path.resolve(root,'../scotusstats/data-pipeline/oyez');
 const metadataSources=new Map([...metadata.keys()].map(k=>[k,'video case metadata']));
 if(fs.existsSync(cached))for(const term of Object.keys(episodes)){
  const folder=path.join(cached,term);if(!fs.existsSync(folder))continue;
  for(const file of fs.readdirSync(folder).filter(f=>f.endsWith('.json')&&!f.endsWith('_transcript.json'))){
   const data=JSON.parse(fs.readFileSync(path.join(folder,file)));if(!data||!data.docket_number)continue;
   const key=term+':'+data.docket_number;
   if(!metadata.has(key)){metadata.set(key,data);metadataSources.set(key,'scotusstats cached Oyez metadata');}
  }
 }
 const decode=s=>s.replace(/&#(x[0-9a-f]+|[0-9]+);/gi,(_,n)=>String.fromCodePoint(n[0].toLowerCase()==='x'?parseInt(n.slice(1),16):+n)).replace(/&(amp|quot|apos|nbsp|lt|gt);/g,(_,n)=>({amp:'&',quot:'"',apos:"'",nbsp:' ',lt:'<',gt:'>'}[n]));
 const descriptionNames=description=>{
  const list=description.match(/Advocates:\s*<ul>([\s\S]*?)<\/ul>/i);if(!list)return [];
  return [...list[1].matchAll(/<li[^>]*>([\s\S]*?)<\/li>/gi)].map(m=>decode(m[1].replace(/<[^>]*>/g,'')).split(' (')[0].trim()).filter(Boolean);
 };
 const portraits=new Map();
 for(const file of fs.readdirSync(path.join(root,'advocates')).filter(f=>f.endsWith('.jpg'))){
  const id=file.slice(0,-4),key=normalize(id);portraits.set(key,[...(portraits.get(key)||[]),id]);
 }
 const catalog=JSON.parse(fs.readFileSync(path.join(root,'cloud/speaker-catalog.json')));
 const court=Object.values(catalog).filter(p=>Number.isInteger(p.seniority));
 const previousPath=path.join(output,'manifest.json');
 const previous=fs.existsSync(previousPath)?JSON.parse(fs.readFileSync(previousPath)).generated:[];
 const existing=new Map(previous.map(e=>[e.term+':'+e.docket,e]));
 const report={generated:[],skipped:[],failed:[]};
 const bundle=fs.mkdtempSync(path.join(os.tmpdir(),'podcast-artwork-backfill-'));
 fs.mkdirSync(path.join(bundle,'json'));for(const item of ['advocates','myriadpro','seal.svg'])fs.symlinkSync(path.join(root,item),path.join(bundle,item));
 const browser=await puppeteer.launch({headless:'new',executablePath:process.env.PUPPETEER_EXECUTABLE_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 try{
  for(const term of Object.keys(episodes).sort().reverse())for(const [docket,episode] of Object.entries(episodes[term])){
   const entry={term,docket,name:episode.name};let data=metadata.get(term+':'+docket),source=metadataSources.get(term+':'+docket);
   if(!data){
    if(Number(term)<2022){report.skipped.push({...entry,reason:'Historical bench and local case metadata unavailable'});continue;}
    const fromDescription=descriptionNames(episode.description||'');
    const names=[...new Set(fromDescription.length?fromDescription:(episode.chapters||[]).filter(c=>c.title.includes(' (')).map(c=>c.title.split(' (')[0]))];
    if(!names.length){report.skipped.push({...entry,reason:'No local advocate metadata or chapter names'});continue;}
    const advocates=[];let missing=[];
    for(const name of names){const ids=portraits.get(normalize(name))||[];if(ids.length!==1)missing.push(name);else advocates.push({advocate:{identifier:ids[0],name}});}
    if(missing.length){report.skipped.push({...entry,reason:'Missing or ambiguous portrait match',advocates:missing});continue;}
    data={name:episode.name,advocates,heard_by:[{members:court}]};source=fromDescription.length?'podcast description advocate list':'podcast chapter names';
   }
   const missing=(data.advocates||[]).filter(a=>!a.advocate?.identifier||!fs.existsSync(path.join(root,'advocates',a.advocate.identifier+'.jpg')));
   if(missing.length){report.skipped.push({...entry,reason:'Missing advocate portrait',advocates:missing.map(a=>a.advocate?.name)});continue;}
   if(!(data.advocates||[]).length){report.skipped.push({...entry,reason:'No advocate list in local metadata'});continue;}
   const members=data.heard_by?.[0]?.members||[];
   const isJackson=members.some(p=>p.identifier==='ketanji_brown_jackson');
   const isBreyer=members.some(p=>p.identifier==='stephen_g_breyer')&&members.some(p=>p.identifier==='amy_coney_barrett');
   if(!isJackson&&!isBreyer){report.skipped.push({...entry,reason:Number(term)<2022?'Historical bench requires matching template':'Court panel requires a matching bench template'});continue;}
   const saved=existing.get(term+':'+docket);
   if(saved&&fs.existsSync(path.join(output,saved.file))&&fs.statSync(path.join(output,saved.file)).size===saved.bytes){report.generated.push({...saved,bench:isBreyer?'breyer':'jackson'});continue;}
   const id=term+'-'+docket,folder=path.join(output,term);fs.mkdirSync(folder,{recursive:true});
   fs.writeFileSync(path.join(bundle,'json',id+'.json'),JSON.stringify({...data,name:episode.name}));
   const filename=path.join(folder,docket+'.jpg');
   try{await render(bundle,id,filename,browser);report.generated.push({...entry,file:path.relative(output,filename),metadata_source:source,bench:isBreyer?'breyer':'jackson',bytes:fs.statSync(filename).size});}
   catch(error){fs.rmSync(filename,{force:true});if(error.message==='Podcast bench does not match this Court')report.skipped.push({...entry,reason:'Court panel requires a matching bench template'});else report.failed.push({...entry,reason:error.message});}
   fs.writeFileSync(path.join(output,'manifest.json'),JSON.stringify(report,null,2)+'\n');
   if(report.generated.length%20===0)console.log(JSON.stringify({generated:report.generated.length,skipped:report.skipped.length,failed:report.failed.length}));
  }
 }finally{await browser.close();fs.rmSync(bundle,{recursive:true,force:true});}
 fs.writeFileSync(path.join(output,'manifest.json'),JSON.stringify(report,null,2)+'\n');
 fs.writeFileSync(path.join(output,'index.html'),`<!doctype html><meta charset="utf-8"><title>Podcast artwork backfill</title><style>body{margin:24px;font:16px system-ui;background:#eee;color:#222}main{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:20px}figure{margin:0}img{width:100%;display:block}figcaption{padding:8px 0}small{color:#666}</style><h1>Podcast artwork backfill</h1><p>${report.generated.length} images · ${report.skipped.length} skipped · ${report.failed.length} failed. Local files only.</p><main>${report.generated.map(e=>`<figure><img loading="lazy" src="${escape(e.file)}"><figcaption>${escape(e.name)}<br><small>${e.term} · ${e.docket}</small></figcaption></figure>`).join('')}</main>`);
 console.log(JSON.stringify({generated:report.generated.length,skipped:report.skipped.length,failed:report.failed.length,total_bytes:report.generated.reduce((n,e)=>n+e.bytes,0),output}));
}
main().catch(e=>{console.error(e);process.exitCode=1});
