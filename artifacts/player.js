(() => {
  const params = new URLSearchParams(location.search);
  const caseID = params.get('case') || '25A312';
  const manifestURL = params.get('manifest') || `/artifacts/output/${caseID}/manifest.json`;
  const audio = document.getElementById('audio');
  const el = id => document.getElementById(id);
  let manifest, rows, metadata, currentIndex = -1, currentCueID = '', speakers = {};
  let images = new Map();
  const time = seconds => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
  const getJSON = async url => {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Could not load ${url} (${response.status})`);
    return response.json();
  };
  function resize() {
    if (params.has('render')) return;
    const width = Math.min(1920, window.innerWidth - 32);
    el('viewport').style.width = `${width}px`;
    el('viewport').style.height = `${width * 1080 / 1920}px`;
    el('frame').style.transform = `scale(${width / 1920})`;
  }
  function blockAt(seconds) {
    let lo = 0, hi = rows.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (rows[mid].start <= seconds) lo = mid + 1; else hi = mid; }
    return lo - 1;
  }
  function renderTranscript(index) {
    el('transcript').replaceChildren();
    if (index < 0) return;
    // Keep enough prior context to fill the frame, including on backward seeks.
    for (let i = Math.max(0, index - 5); i <= index; i++) {
      const row = rows[i];
      const div = document.createElement('div');
      div.className = 'speech' + (i === index ? ' current' : '');
      const label = document.createElement('div'); label.className = 'speaker'; label.textContent = row.speaker.name;
      const p = document.createElement('p'); p.textContent = row.text;
      div.append(label, p); el('transcript').append(div);
    }
    const active = el('transcript').lastElementChild;
    el('transcript').scrollTop = Math.max(0, active.offsetTop + active.offsetHeight - el('transcript').offsetTop - el('transcript').clientHeight + 8);
    const speaker = speakers[rows[index].speaker.identifier] || rows[index].speaker;
    el('speaker-image').src = speaker.image || '';
    el('speaker-image').hidden = !speaker.image;
    el('speaker-name').textContent = speaker.name;
    el('speaker-role').textContent = speaker.role || '';
    document.querySelectorAll('.justice').forEach(j => j.classList.toggle('active', j.dataset.id === rows[index].speaker.identifier));
  }
  async function renderAt(seconds) {
    const index = blockAt(seconds);
    if (index !== currentIndex) { renderTranscript(index); currentIndex = index; }
    el('clock').textContent = time(seconds);
    const cue = manifest.cues.find(c => c.start <= seconds && seconds < c.end);
    if ((cue?.id || '') !== currentCueID) {
      currentCueID = cue?.id || '';
      el('excerpt').hidden = !cue; el('speaker-card').hidden = !!cue;
      if (cue) {
        el('artifact-kind').textContent = {amicus:'Amicus brief',statute:'Statutory text',brief:'Party filing',record:'Case record',opinion:'Court opinion'}[cue.kind] || 'Source document';
        el('artifact-title').textContent = cue.title;
        el('document-image').src = cue.image;
        el('document-image-link').href = cue.full_page_image;
        el('source-title').textContent = cue.source_title.replace(/ filed\.$/,'').replace(/, submitted to The Chief Justice\.$/,'');
        el('source-link').textContent = `${cue.printed_page ? `p. ${cue.printed_page} · ` : ''}PDF page ${cue.pdf_page} · ${cue.source_date} · supremecourt.gov`;
        el('source-link').href = cue.source_url;
      }
    }
    // Rendering callers await the actual displayed image, not just preloads.
    if (cue && !el('document-image').complete) await new Promise((resolve,reject) => { el('document-image').onload=resolve; el('document-image').onerror=reject; });
    return {block: index,cue:cue?.id || null};
  }
  function buildReview() {
    el('status').textContent = `${manifest.cues.length} source excerpts · ${manifest.unresolved.length} unresolved`;
    el('review-note').textContent = `Detected by ${manifest.origin}. Exact quotations checked against source PDFs. Review source identity and timing before publishing.`;
    const add = (cue, target, resolved) => {
      const row = document.createElement('div'); row.className='cue-row';
      const button = document.createElement('button'); button.textContent=time(cue.start); button.onclick=()=> {audio.currentTime=cue.start; renderAt(cue.start);};
      const text = document.createElement('div'); const title=document.createElement('strong'); title.textContent=cue.title;
      const p=document.createElement('p'); p.textContent=cue.evidence;
      const note=document.createElement('p'); note.textContent=cue.reason;
      text.append(title,p,note);
      if (resolved) { const a=document.createElement('a'); a.href=cue.source_url; a.target='_blank'; a.rel='noopener'; a.textContent=`Open source · PDF page ${cue.pdf_page}`; text.append(a); }
      row.append(button,text); el(target).append(row);
    };
    manifest.cues.forEach(c=>add(c,'cue-list',true));
    manifest.unresolved.forEach(c=>add(c,'unresolved-list',false));
    el('unresolved-heading').textContent=manifest.unresolved.length ? 'Unresolved references' : '';
  }
  window.artifactReady = (async () => {
    if (params.has('render')) document.body.classList.add('render');
    manifest = await getJSON(manifestURL);
    [metadata, rows] = await Promise.all([getJSON(manifest.metadata),getJSON(manifest.transcript)]);
    rows = rows.transcript.sections.flatMap((s,si)=>s.turns.flatMap((t,ti)=>t.text_blocks.map((b,bi)=>({...b,speaker:t.speaker,id:`s${si}t${ti}b${bi}`}))));
    const members=metadata.heard_by[0].members;
    const ordered=[members[0]];
    members.slice(1).forEach((j,i)=>(i%2===0?ordered.unshift(j):ordered.push(j)));
    for (const j of ordered) {
      const image=`/justices/${j.thumbnail.href.split('/').pop()}`;
      speakers[j.identifier]={...j,image,role:j.roles[0].role_title};
      const div=document.createElement('div'); div.className='justice'; div.dataset.id=j.identifier;
      const img=document.createElement('img'); img.src=image; img.alt=j.name;
      const caption=document.createElement('span'); caption.textContent=`${j.identifier===members[0].identifier?'Chief Justice':'Justice'} ${j.last_name}`;
      div.append(img,caption); el('bench').append(div);
    }
    metadata.advocates.forEach(a=> {const adv=a.advocate;speakers[adv.identifier]={...adv,image:`/advocates/${adv.identifier}.jpg`,role:a.advocate_description || adv.description || 'Advocate'};});
    Object.values(speakers).forEach(s=> {const img=new Image();img.src=s.image;img.onerror=()=>{s.image='';};});
    el('case-name').textContent=metadata.name;
    const argument=metadata.timeline.find(t=>t.event==='Argued');
    const date=argument ? new Date(argument.dates[0]*1000).toLocaleDateString('en-US',{year:'numeric',month:'long',day:'numeric',timeZone:'America/New_York'}) : '';
    el('case-subtitle').textContent=`No. ${metadata.docket_number} · Oral argument · ${date}`;
    el('footer-case').textContent=`No. ${metadata.docket_number}`;
    manifest.cues.forEach(c=> {if(!images.has(c.image)) images.set(c.image,new Promise((resolve,reject)=>{const img=new Image();img.onload=resolve;img.onerror=()=>reject(new Error(`Missing excerpt ${c.image}`));img.src=c.image;}));});
    await Promise.all([...images.values()]);
    audio.src=manifest.audio;
    buildReview(); resize();
    window.artifactRenderAt=renderAt;
    window.artifactData={manifest,rows};
    const initial=Number(params.get('t') || manifest.cues[0]?.start || 0);
    audio.currentTime=initial;
    await renderAt(initial);
    audio.addEventListener('timeupdate',()=>renderAt(audio.currentTime));
    audio.addEventListener('seeking',()=>renderAt(audio.currentTime));
    document.addEventListener('keydown',e=>{if(e.code==='Space' && e.target.tagName!=='BUTTON'){e.preventDefault();audio.paused?audio.play():audio.pause();}});
    el('toggle-review').onclick=()=>{el('review').hidden=!el('review').hidden;};
    return true;
  })().catch(error=>{el('error').hidden=false;el('error').textContent=error.message;el('status').textContent='Preview unavailable';throw error;});
  window.addEventListener('resize',resize);
})();
