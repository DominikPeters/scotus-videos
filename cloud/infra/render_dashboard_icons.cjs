// Render the code-native logo source at each PWA icon size; no network assets.
const fs=require('fs'),path=require('path'),puppeteer=require('puppeteer');
(async()=>{
 const root=path.resolve(__dirname,'../dashboard');
 const svg=fs.readFileSync(path.join(root,'design/icon.svg'),'utf8');
 const browser=await puppeteer.launch({headless:'new',executablePath:process.env.PUPPETEER_EXECUTABLE_PATH||undefined});
 try{
  const page=await browser.newPage();
  for(const size of [180,192,512]){
   await page.setViewport({width:size,height:size,deviceScaleFactor:1});
   await page.setContent(`<style>html,body{margin:0}svg{display:block;width:100vw;height:100vh}</style>${svg}`);
   await page.screenshot({path:path.join(root,`public/icon-${size}.png`)});
  }
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
