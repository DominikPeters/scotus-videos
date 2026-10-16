// Check the actual stylesheet in both copies: outer quotation wrapper stays plain,
// while nested emphasis remains visible in excerpts, comparisons and map legends.
const fs=require('fs'),path=require('path'),puppeteer=require('puppeteer');
(async()=>{
 const browser=await puppeteer.launch({headless:'new',executablePath:process.env.PUPPETEER_EXECUTABLE_PATH||undefined});
 try{
  const page=await browser.newPage();
  for(const name of ['cloud/presentation/renderer/index.html','mockup-quotes/index.html'].filter(name=>fs.existsSync(path.resolve(__dirname,'../..',name)))){
   const html=fs.readFileSync(path.resolve(__dirname,'../..',name),'utf8');const css=[...html.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map(m=>m[1]).join('\n');
   await page.setContent(`<style>${css}</style><div class="quote-card"><div class="quote-body quote-only"><mark id="outer">Quoted <mark id="excerpt">phrase</mark></mark><div class="compare-text"><mark id="comparison">compared phrase</mark></div><div class="map-legend"><span><mark id="map">split</mark></span></div></div></div>`);
   const colors=await page.evaluate(()=>Object.fromEntries(['outer','excerpt','comparison','map'].map(id=>[id,getComputedStyle(document.getElementById(id)).backgroundColor])));
   if(colors.outer!=='rgba(0, 0, 0, 0)'||['excerpt','comparison','map'].some(id=>colors[id]==='rgba(0, 0, 0, 0)'))throw Error(name+': hidden highlights '+JSON.stringify(colors));
  }
  console.log('Passed visible inner highlights in both renderer stylesheets.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
