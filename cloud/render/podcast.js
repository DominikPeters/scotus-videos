'use strict';
// Square episode artwork from the approved podcast mockup; no video layout changes.
const fs=require('fs'),path=require('path'),{pathToFileURL}=require('url'),puppeteer=require('puppeteer');
const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const url=p=>pathToFileURL(p).href;
async function render(bundle,id,out,existingBrowser=null){
 const metadata=JSON.parse(fs.readFileSync(path.join(bundle,'json',id+'.json')));
 const advocates=metadata.advocates.map(a=>a.advocate);
 if(!advocates.length)throw Error('No advocates for episode artwork');
 const court=metadata.heard_by?.[0]?.members||[];
 const expected=['john_g_roberts_jr','clarence_thomas','samuel_a_alito_jr','sonia_sotomayor','elena_kagan','neil_gorsuch','brett_m_kavanaugh','amy_coney_barrett','ketanji_brown_jackson'];
 // Match the complete Court to an approved seating-order template.
 const matches=ids=>court.length===ids.length&&ids.every(id=>court.some(p=>p.identifier===id));
 const breyer=expected.map(id=>id==='ketanji_brown_jackson'?'stephen_g_breyer':id);
 const bench=matches(expected)?'bench.jpg':matches(breyer)?'bench-breyer.jpg':null;
 if(!bench)throw Error('Podcast bench does not match this Court');
 const assets=path.resolve(__dirname,'../presentation/podcast');
 const title=metadata.name.split(' v. ').map(escape).join('<br>v. ');
 const n=advocates.length,columns=n===4?2:n>4?3:n;
 const html=`<!doctype html><meta charset="utf-8"><style>
 *{box-sizing:border-box}body{margin:0} @font-face{font-family:myriad;src:url('${url(path.join(bundle,'myriadpro/MYRIADPRO-SEMIBOLD.OTF'))}');font-weight:600}
 .art{width:600px;height:600px;position:relative;overflow:hidden;background:hsl(43,45%,99%);display:flex;flex-direction:column;font-family:myriad,sans-serif;color:black}
 .bench{width:600px;height:171px;flex-shrink:0}.seal{position:absolute;top:7px;right:17px;width:70px;height:70px}
 .case-wrap{height:140px;margin:0 23px;flex-shrink:0;display:flex;align-items:center;justify-content:center}
 .case{font-size:76px;font-weight:600;line-height:1.01;text-align:center;letter-spacing:-1.25px;width:100%}
 .photos{flex:1;min-height:0;display:flex;justify-content:center;align-items:center;padding:12px 24px 20px}
 .advocates{display:grid;grid-template-columns:repeat(${columns},var(--portrait));gap:${n>=4?10:12}px}
 .advocates img{width:var(--portrait);height:var(--portrait);object-fit:cover;display:block}
 </style><div class="art"><img class="bench" src="${url(path.join(assets,bench))}"><img class="seal" src="${url(path.join(bundle,'seal.svg'))}"><div class="case-wrap"><div class="case">${title}</div></div><div class="photos"><div class="advocates">${advocates.map(a=>`<img alt="${escape(a.name)}" src="${url(path.join(bundle,'advocates',a.identifier+'.jpg'))}">`).join('')}</div></div></div>`;
 const browser=existingBrowser||await puppeteer.launch({headless:'new',executablePath:process.env.PUPPETEER_EXECUTABLE_PATH||undefined,args:process.env.CLOUD_RUN_JOB?['--no-sandbox','--disable-dev-shm-usage']:[]});
 const page=await browser.newPage();
 try{const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.setViewport({width:600,height:600,deviceScaleFactor:2.5});
 // Use a local document so Chrome can read the frozen local assets.
 const document=path.join(bundle,'podcast-artwork.html');fs.writeFileSync(document,html);await page.goto(url(document));
 await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()));});
 const layout=await page.evaluate(({n,columns})=>{const title=document.querySelector('.case');let size=76;while((title.scrollWidth>554||title.scrollHeight>140)&&size>28)title.style.fontSize=(--size)+'px';const area=document.querySelector('.photos');const rows=Math.ceil(n/columns);const portrait=Math.floor(Math.min((area.clientHeight-32-(rows-1)*10)/rows,(552-(columns-1)*12)/columns,n===1?216:n===2?216:n===3?174:145));document.querySelector('.advocates').style.setProperty('--portrait',portrait+'px');return {overflow:title.scrollHeight>140||title.scrollWidth>554,portrait};},{n,columns});
 if(errors.length||layout.overflow||layout.portrait<60)throw Error('Episode artwork does not fit');
 for(const quality of [90,80,70]){await page.screenshot({path:out,type:'jpeg',quality});if(fs.statSync(out).size<=350000)return;}
 throw Error('Episode artwork exceeds transfer limit');
 }finally{await page.close();if(!existingBrowser)await browser.close();}
}
if(require.main===module)render(path.resolve(process.argv[2]),process.argv[3],process.argv[4]).catch(e=>{console.error(e);process.exitCode=1});
module.exports={render};
