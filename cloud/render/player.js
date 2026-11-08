'use strict';
const $=id=>document.getElementById(id);
let manifest,plan;
const isJustice=p=>p.kind==='justice'||(!p.kind&&['Justice','Chief Justice'].includes(p.role));
function image(person){
  if(person.image){const img=document.createElement('img');img.src=person.image;img.alt=person.name;return img;}
  const d=document.createElement('div');d.className='initials';d.textContent=person.name.split(/\s+/).filter(w=>w.length>1).slice(0,2).map(w=>w[0]).join('');return d;
}
function blockAt(time){const frame=Math.floor(time*plan.fps+1e-6);let low=0,high=plan.events.length;while(low<high){const mid=(low+high)>>1;if(plan.events[mid].frame<=frame)low=mid+1;else high=mid;}return low?plan.events[low-1].paragraph:-1;}
window.renderAt=async time=>{
  const index=blockAt(time),active=manifest.paragraphs[index];
  $('transcript').replaceChildren();
  if(!active){$('portrait').replaceChildren();$('speaker-name').textContent='';$('speaker-role').textContent='';$('section').textContent='';return {paragraph:-1};}
  for(let i=Math.max(0,index-7);i<=index;i++){
    const row=manifest.paragraphs[i],person=manifest.speakers[row.speaker],d=document.createElement('div'),label=document.createElement('div'),p=document.createElement('p');
    d.className='speech'+(i===index?' current':'')+(isJustice(person)?' justice':'');label.className='label';label.textContent=person.name;p.textContent=row.text;d.append(label,p);$('transcript').append(d);
  }
  const person=manifest.speakers[active.speaker];$('portrait').replaceChildren(image(person));$('speaker-name').textContent=person.name;$('speaker-role').textContent=person.role||'';
  $('section').textContent=active.section.toLowerCase().replace(/^./,c=>c.toUpperCase());
  document.querySelectorAll('#bench .justice').forEach(j=>j.classList.toggle('active',j.dataset.id===active.speaker));
  const current=$('transcript').lastElementChild;
  // Complete state is reconstructed after every seek, including chunk starts.
  $('transcript').scrollTop=Math.max(0,current.offsetTop+Math.min(current.offsetHeight,$('transcript').clientHeight)-$('transcript').offsetTop-$('transcript').clientHeight+16);
  await Promise.all([...document.images].map(img=>img.complete?Promise.resolve():new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=()=>reject(Error('Portrait could not be loaded'));})));
  return {paragraph:index,speaker:active.speaker,scroll:$('transcript').scrollTop};
};
window.ready=(async()=>{
  const responses=await Promise.all([fetch('manifest.json'),fetch('plan.json')]);if(responses.some(r=>!r.ok))throw Error('Render inputs unavailable');[manifest,plan]=await Promise.all(responses.map(r=>r.json()));
  $('case-name').textContent=`[${manifest.docket}] ${manifest.case_name}`;$('subtitle').textContent=`Oral argument · ${manifest.argument_date}`;
  const justices=Object.values(manifest.speakers).filter(isJustice).sort((a,b)=>(a.seniority??99)-(b.seniority??99));
  const chief=justices.find(p=>p.role==='Chief Justice'),ordered=chief?[chief]:[];
  justices.filter(p=>p!==chief).forEach((p,i)=>i%2===0?ordered.unshift(p):ordered.push(p));
  for(const p of ordered){const d=document.createElement('div'),label=document.createElement('p');d.className='justice';d.dataset.id=p.identifier;label.textContent=p.last_name||p.name.split(' ').at(-1);d.append(image(p),label);$('bench').append(d);}
  await document.fonts.ready;return true;
})();
