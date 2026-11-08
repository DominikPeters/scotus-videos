"""Routine source refreshes, before spending a code-repair turn."""
import hashlib,re,time
from urllib.parse import urljoin,urlsplit
from urllib.request import Request,urlopen
from .discovery import recordings,official,Rows

def current_sources(job,fetch=official):
 term=int(job['argument_date'][:4])-(int(job['argument_date'][5:7])<10)
 matches=[r for r in recordings(term,fetch=fetch) if r['docket']==job['docket'] and r['argument_date']==job['argument_date']]
 if len(matches)!=1:raise ValueError('The official recording identity is ambiguous or unavailable')
 record=matches[0]
 # The transcript index can be updated before the audio detail page.
 page=f'https://www.supremecourt.gov/oral_arguments/argument_transcript/{term}'
 parser=Rows();parser.feed(fetch(page));candidates=[]
 from datetime import datetime
 for row in parser.rows:
  text=' '.join(' '.join(row['text']).split())
  if not re.search(r'(?<![0-9-])'+re.escape(job['docket'])+r'(?![0-9-])',text):continue
  dates=re.findall(r'\b\d{2}/\d{2}/(?:\d{4}|\d{2})\b',text)
  if not any(datetime.strptime(d,'%m/%d/%Y' if len(d)==10 else '%m/%d/%y').date().isoformat()==job['argument_date'] for d in dates):continue
  candidates.extend(urljoin(page,u) for u in row['links'] if '/argument_transcripts/' in u and urlsplit(u).path.endswith('.pdf'))
 if len(set(candidates))==1:record['pdf_url']=candidates[0]
 return record

def pdf_digest(url):
 parsed=urlsplit(url)
 if parsed.scheme!='https' or parsed.hostname not in ('supremecourt.gov','www.supremecourt.gov'):raise ValueError('Official Court source required')
 with urlopen(Request(url,headers={'User-Agent':'Scotus source refresh'}),timeout=20) as response:
  if urlsplit(response.url).hostname not in ('supremecourt.gov','www.supremecourt.gov'):raise ValueError('Unexpected source redirect')
  data=response.read(4194305)
 if len(data)>4194304 or not data.startswith(b'%PDF'):raise ValueError('Unexpected transcript PDF')
 return hashlib.sha256(data).hexdigest()

def audio_digest(url):
 # Only called for a claimed source refresh, never normal recording-index polling.
 parsed=urlsplit(url)
 if parsed.scheme!='https' or parsed.hostname not in ('supremecourt.gov','www.supremecourt.gov'):raise ValueError('Official Court source required')
 digest=hashlib.sha256();size=0;started=time.monotonic()
 with urlopen(Request(url,headers={'User-Agent':'Scotus source refresh'}),timeout=20) as response:
  final=urlsplit(response.url)
  if final.scheme!='https' or final.hostname not in ('supremecourt.gov','www.supremecourt.gov'):raise ValueError('Unexpected source redirect')
  while True:
   data=response.read(1048576)
   if not data:break
   size+=len(data)
   if size>268435456 or time.monotonic()-started>90:raise ValueError('Official audio check exceeded its download limit')
   digest.update(data)
 if not size:raise ValueError('Empty official audio')
 return digest.hexdigest()

def refresh(dashboard,google,settings,job_id,manual=False,keep_recovery=None,lease=None):
 job=dashboard.call('source_refresh_claim',job=job_id,manual=manual)
 if not job:return {'status':'checked_recently'}
 if 'stages' not in job:return job
 try:
  record=current_sources(job);sha=pdf_digest(record['pdf_url'])
  prepared=job['stages']['prepare'].get('result',{});old=google.storage_json(prepared['transcript_uri'],max_bytes=2097152) if prepared.get('transcript_uri') else None
  expected=(old or {}).get('inputs',{}).get('pdf_sha256')
  expected_audio=(old or {}).get('audio',{}).get('sha256')
  audio_changed=audio_digest(record['audio_url'])!=expected_audio if expected_audio else record['audio_url']!=job['audio_url']
  changed=(expected!=sha if expected else record['pdf_url']!=job['pdf_url']) or audio_changed
  return dashboard.call('source_refresh_apply',job=job_id,expected_pdf=job['pdf_url'],expected_audio=job['audio_url'],expected_prepared_uri=prepared.get('transcript_uri'),pdf_url=record['pdf_url'],audio_url=record['audio_url'],pdf_sha256=sha,changed=changed,keep_recovery=keep_recovery,lease=lease)
 except Exception:
  dashboard.call('source_refresh_wait',job=job_id);return {'status':'waiting_for_source','message':'The official source check will retry automatically.'}

def maintain(dashboard,google,settings,snapshot):
 for job in (snapshot.get('jobs') or {}).values():
  needs=job.get('maintenance',{}).get('status')=='waiting'
  source_failure=job['status']=='failed' and any(job['stages'][s]['status']=='failed' for s in ('prepare','align'))
  if needs or source_failure:refresh(dashboard,google,settings,job['id'])
