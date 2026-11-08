"""Incremental statistics publication and evidence-backed opinion coding."""
import gzip,hashlib,json,os,re,subprocess,tempfile,time,uuid
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urljoin,urlsplit
import xml.etree.ElementTree as ET
import requests
import stats_core
from .google import Google
from .remote import Dashboard
from .codex_auth import run_codex
from .statistics_migrations import migrate
from stats_core import JUSTICES,apply_alignment,apply_coding,public_records,flatten

ROOT=Path('/app/statistics')
CODING_REVISION='2026-10-15-structured-decisions'
def fingerprint(value):return hashlib.sha256(value if isinstance(value,bytes) else json.dumps(value,sort_keys=True).encode()).hexdigest()

def owner_answers(claim):
    # PHP encodes an empty associative array as []; nonempty maps are objects.
    value=claim.get('answers') or {}
    if not isinstance(value,dict):raise ValueError('Invalid statistics answers map')
    return value

def retry_fixed_error(saved):
    """Revisit only known implementation failures corrected by this revision."""
    return (saved.get('status')=='needs_review' and saved.get('coding_revision')!=CODING_REVISION
        and saved.get('notes','').startswith(("AttributeError: 'list' object has no attribute 'get'",'ValueError: Invalid justice list')))

MAX_TECHNICAL_ATTEMPTS=3

def legacy_technical_failure(saved):
    # Older workers incorrectly turned caught implementation/transport exceptions
    # into owner questions. Model-authored substantive questions remain untouched.
    return saved.get('status')=='needs_review' and bool(re.match(
        r'^(?:RuntimeError|ValueError|AttributeError|TypeError|KeyError|Timeout|ReadTimeout|ConnectTimeout|ConnectionError|HTTPError|OSError|CalledProcessError): ',saved.get('notes','')))

def technical_failure(error,saved,now):
    attempts=saved.get('technical_attempts',0)+1
    return {'status':'retry_pending' if attempts<MAX_TECHNICAL_ATTEMPTS else 'failed',
            'notes':type(error).__name__+': '+str(error)[:350],
            'technical_attempts':attempts,'retry_after':now+min(1800,300*2**(attempts-1))}

def research_work(research,candidate_backlog,now):
    errors={key:{field:saved[field] for field in ('status','notes','technical_attempts','retry_after') if field in saved}
            for key,saved in research.items() if saved.get('status') in ('retry_pending','failed')}
    retries={key for key,saved in research.items() if saved.get('status')=='retry_pending'}
    pending=set(candidate_backlog)|retries
    delay=0 if set(candidate_backlog) else min((max(0,research[k]['retry_after']-now) for k in retries),default=0)
    return errors,len(pending),int(delay)

def official(url):
    if urlsplit(url).hostname not in ('www.supremecourt.gov','supremecourt.gov') or urlsplit(url).scheme!='https':raise ValueError('Official Court source required')
    r=requests.get(url,timeout=25)
    if r.status_code in (404,410):return None
    r.raise_for_status();return r.content

def opinion_links(html,base):
    from html.parser import HTMLParser
    class Rows(HTMLParser):
        def __init__(self):super().__init__();self.rows=[];self.text=[];self.links=[];self.inside=False
        def handle_starttag(self,tag,attrs):
            if tag=='tr':self.inside=True;self.text=[];self.links=[]
            if tag=='a' and self.inside:
                href=dict(attrs).get('href','')
                if '.pdf' in href.lower():self.links.append(urljoin(base,href))
        def handle_data(self,value):
            if self.inside:self.text.append(value)
        def handle_endtag(self,tag):
            if tag=='tr' and self.inside:self.rows.append((' '.join(self.text),self.links));self.inside=False
    p=Rows();p.feed(html);result={}
    for text,links in p.rows:
        for docket in re.findall(r'\b\d{2}-\d+\b',text):
            if links:result[docket]={'url':links[0],'signature':fingerprint(text)}
    return result

def schema(issues,provisions):
    justice={'type':'string','enum':sorted(JUSTICES)}
    nullable_justice={'type':['string','null'],'enum':[None,*sorted(JUSTICES)]}
    names={'type':'array','items':justice}
    props={k:names for k in ['majorityVoters','minorityVoters','abstainers','majorityJoiners','dissentingWriters']}
    props.update(type={'type':'string','enum':sorted(stats_core.DECISION_FORMS)},majorityWriter=nullable_justice,majoritySize={'type':['integer','null']},minoritySize={'type':['integer','null']},voteStatus={'type':'string','enum':['complete','mixed','unknown']})
    part_props={k:names for k in ['majorityVoters','minorityVoters','abstainers','majorityJoiners','dissentingWriters']}
    part_props.update(label={'type':'string'},evidence={'type':'string'},majoritySize={'type':'integer'},minoritySize={'type':'integer'})
    props['judgmentParts']={'type':'array','items':{'type':'object','properties':part_props,'required':list(part_props),'additionalProperties':False}}
    decision={'type':'object','properties':props,'required':list(props),'additionalProperties':False}
    opinion={'type':'object','properties':{'author':nullable_justice,'type':{'type':'string'},'joiners':names,'partialJoiners':{'type':'array','items':{'type':'object','properties':{'justice':justice,'parts':{'type':'string'}},'required':['justice','parts'],'additionalProperties':False}},'parts':{'type':'string'},'evidence':{'type':'string'}},'required':['author','type','joiners','partialJoiners','parts','evidence'],'additionalProperties':False}
    props={'issue_code':{'type':['string','null'],'enum':[None,*issues]},'legal_provision_code':{'type':['string','null'],'enum':[None,*provisions]},'decision':{'anyOf':[{'type':'null'},decision]},'opinion_details':{'type':'array','items':opinion},'evidence':{'type':'array','items':{'type':'string'}},'disposition':{'type':['string','null']},'decided_date':{'type':['string','null']},'lower_court':{'type':['string','null']},'needs_review':{'type':'boolean'},'notes':{'type':'string'}}
    return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}

def opinion_material(record,documents,links,folder,cloud=None,bucket=None):
    def archive(data,url,suffix):
        sha=fingerprint(data);previous=documents.get(url,{})
        if previous.get("sha256")==sha:return
        uri=f"gs://{bucket}/statistics/sources/{sha}.{suffix}"
        if cloud:
            path=folder/("source."+suffix);path.write_bytes(data)
            try:cloud.storage_upload(path,uri)
            except RuntimeError as error:
                if "412" not in str(error):raise
        documents[url]={"sha256":sha,"uri":uri}

    docket=record['docket_number'];url=f'https://www.supremecourt.gov/RSS/Cases/JSON/{docket}.json'
    raw=official(url)
    if raw is None:return None
    archive(raw,url,'json')
    docket_data=json.loads(raw);events=docket_data.get('ProceedingsandOrder') or []
    relevant=[e for e in events if any(s in e.get('Text','').lower() for s in ['delivered','per curiam','improvidently','affirmed','reversed','vacated','argued','judgment'])]
    material={'case':{k:record.get(k) for k in ['name','term','docket_number','argument_date']},'docket_url':url,'lower_court':docket_data.get('LowerCourt'),'events':relevant[-15:]}
    # XML carries separate opinion authors and countable text; the PDF is a fallback.
    xml_url=f'https://www.supremecourt.gov/xmls/archive/{docket}.xml';pdf_entry=links.get(docket);pdf=pdf_entry.get('url') if isinstance(pdf_entry,dict) else pdf_entry
    if pdf or any('delivered' in e.get('Text','').lower() or 'per curiam' in e.get('Text','').lower() for e in relevant):
        xml=official(xml_url)
        if xml is not None:
            try:
                root=ET.fromstring(xml);archive(xml,xml_url,'xml');texts=[];counts=[]
                for doc in root.findall('document'):
                    text=' '.join(' '.join(doc.itertext()).split());texts.append(text[:18000] if not doc.get('Chamber') else text[:1800])
                    if doc.get('Chamber'):
                        words=sum(len(''.join(p.itertext()).split()) for p in doc.findall('.//p[@style]') if any(s in p.get('style','') for s in ['Footnote','CASCT']))
                        counts.append({'author':doc.get('Chamber'),'disposition':doc.get('Disposition'),'word_count':words,'num_footnotes':len(doc.find('footnotes')) if doc.find('footnotes') is not None else 0})
                if texts:material['opinion_text']='\n'.join(texts);material['opinion_url']=xml_url;record['opinions']=counts
            except ET.ParseError:pass
        if not material.get('opinion_text') and pdf:
            data=official(pdf)
            if data:
                archive(data,pdf,'pdf')
                path=folder/'opinion.pdf';path.write_bytes(data)
                text=subprocess.run(['pdftotext','-layout',str(path),'-'],capture_output=True,text=True,check=True,timeout=30).stdout
                heads=[text[max(0,m.start()-100):m.start()+1000] for m in re.finditer(r'(?:Justice [A-Z][a-z]+[^\n]{0,100}(?:concurring|dissenting)|[A-Z]+, J\., (?:concurring|dissenting))',text)]
                material['opinion_text']=text[:20000]+'\n'+'\n'.join(heads[:15]);material['opinion_url']=pdf
    record['num_amicus_briefs']=sum(bool(re.match(r'(?:Supplemental )?Brief amic(?:us|i) curiae\b.*\bfiled\b',e.get('Text',''),re.I)) for e in events)
    # Oyez facts are useful for classification, independently of transcript availability.
    try:
        response=requests.get(f"https://api.oyez.org/cases/{record['term']}/{docket}",timeout=15)
        if response.ok:
            meta=response.json()
            if isinstance(meta,dict):material['facts']=meta.get('facts_of_the_case');material['question']=meta.get('question')
    except requests.RequestException:pass
    return material

def main():
    cloud=Google(os.environ['GOOGLE_CLOUD_PROJECT']);cfg=json.loads(cloud.secret('scotus-statistics-config'));dashboard=Dashboard(cfg['dashboard_url'],cfg['dashboard_key'],'stats')
    claim=dashboard.call('stats_start',token=os.environ['SCOTUS_STATS_TOKEN'])
    if not claim:return
    token=claim['token'];questions={};answered=[]
    def update(message,**extra):return dashboard.call('stats_update',token=token,message=message,**extra)
    with tempfile.TemporaryDirectory() as temp:
        folder=Path(temp);state={}
        try:
            cloud.storage_download(claim.get('data_uri') or cfg['seed_uri'],folder/'records.gz');state=json.loads(gzip.decompress((folder/'records.gz').read_bytes()));records=state['records'];research=state.setdefault('research',{})
            issues=json.loads((ROOT/'issues.json').read_text());provisions=json.loads((ROOT/'legal-provisions.json').read_text())
            migrate(state,issues,provisions)
            index=requests.get('https://scotusstats.com/podcast/alignment/index.json',timeout=20);index.raise_for_status();index=index.json()
            for entry in index.get('recordings',{}).values():
                previous=records.get(entry['term']+'/'+entry['docket'],{}).get('recordings',{}).get(entry['recording_id'],{})
                if previous.get('revision')==entry['revision']:continue
                url=entry['url'];parsed=urlsplit(url)
                if parsed.hostname!='scotusstats.com' or not parsed.path.startswith('/podcast/alignment/'):raise ValueError('Unexpected recording URL')
                response=requests.get(url,timeout=25);response.raise_for_status()
                if fingerprint(response.content)!=entry['revision']:raise ValueError('Transcript checksum differs')
                apply_alignment(records,entry,response.json());update('Argument statistics updated for '+entry['docket'])
            links=state.get('opinion_links',{})
            today=datetime.now(timezone.utc).date().isoformat()
            if state.get('opinion_check_date')!=today:
                update('Checking official opinion listings')
                year=datetime.now().year-(datetime.now().month<10)
                for term in range(max(2024,year-2),year+1):
                    url=f'https://www.supremecourt.gov/opinions/slipopinion/{str(term)[2:]}'
                    body=official(url)
                    if body:links.update(opinion_links(body.decode('utf-8',errors='replace'),url))
                state['opinion_links']=links;state['opinion_check_date']=today
            issues=json.loads((ROOT/'issues.json').read_text());provisions=json.loads((ROOT/'legal-provisions.json').read_text());processed=0
            answers=owner_answers(claim)
            for saved in research.values():
                if legacy_technical_failure(saved):
                    saved.update(status='retry_pending',technical_attempts=0,retry_after=0)
            candidates=[]
            for key,record in sorted(records.items(),reverse=True):
                if int(record['term'])<2024:continue
                saved=research.get(key,{})
                due=not record.get('issue') or not record.get('decision') or (links.get(record['docket_number']) and saved.get('opinion_url')!=links[record['docket_number']] and (record.get('decision') or {}).get('source')!='scdb')
                retry=retry_fixed_error(saved) or (saved.get('status')=='retry_pending' and saved.get('retry_after',0)<=time.time())
                if saved.get('status') in ('retry_pending','failed') and not retry and not answers.get(key):continue
                if saved.get('status')=='needs_review' and not answers.get(key) and not retry:continue
                if saved.get('checked_date')==today and not answers.get(key) and not retry:continue
                if due or answers.get(key) or retry:candidates.append((key,record))
            candidates.sort(key=lambda item:(item[0] not in answers,not retry_fixed_error(research.get(item[0],{}))))
            unfinished={key for key,_ in candidates}
            for key,record in candidates[:cfg.get('max_cases_per_run',4)]:
                unfinished.discard(key)
                update('Reading official material for '+record['docket_number'])
                result=None;saved=research.get(key,{})
                try:
                    material=opinion_material(record,state.setdefault('documents',{}),links,folder,cloud,cfg['bucket'])
                    if not material:research[key]={'checked_date':today,'status':'source_missing'};continue
                    if answers.get(key):material['owner_answer']=answers[key]
                    merits=any(any(word in e.get('Text','').lower() for word in ['delivered','per curiam','improvidently granted']) for e in material.get('events',[]))
                    if record.get('issue') and not material.get('opinion_text') and not merits and not answers.get(key):
                        research[key]={'checked_date':today,'status':'awaiting_opinion','opinion_url':None};continue
                    prompt=(ROOT/'opinion-prompt.md').read_text()
                    inputs={'input/case.json':json.dumps(material),'input/issues.json':json.dumps(issues),'input/legal-provisions.json':json.dumps(provisions),
                            'input/check_statistics.py':Path(__file__).with_name('statistics_check.py').read_text(),
                            'input/stats_core.py':Path(stats_core.__file__).read_text()}
                    inputs['input/reference/statistics-taxonomy.md']=(ROOT/'statistics-taxonomy.md').read_text()
                    update('Codex interpreting '+record['docket_number'])
                    result=run_codex(dashboard,cloud,cfg['codex_secret'],prompt,schema(issues,provisions),model=cfg['model'],inputs=inputs,timeout_seconds=180)
                    if key in answers:answered.append(key)
                    source=material.get('opinion_url') or material['docket_url']
                    if result.get('decided_date') and record.get('argument_date') and result['decided_date']<record['argument_date']:
                        result['decision']=None;result['decided_date']=None;result['needs_review']=True;result['notes']='Decision date predates argument; please check the disposition. '+result['notes']
                    apply_coding(record,result,issues,provisions,source)
                    research[key]={'checked_date':today,'status':'needs_review' if result['needs_review'] else 'complete','opinion_url':links.get(record['docket_number']),'evidence':result['evidence'],'notes':result['notes'],'coding_revision':CODING_REVISION,'result':result}
                    if result['needs_review']:questions[key]=result['notes']
                    processed+=1;update('Updated coding for '+record['docket_number'])
                except Exception as error:
                    if 'credential is already in use' in str(error):
                        unfinished.add(key);update('Waiting for the shared Codex credential');break
                    research[key]={'checked_date':today,'coding_revision':CODING_REVISION,'result':result,**technical_failure(error,saved,time.time())};update('Technical failure for '+record['docket_number']+'; '+('automatic retry queued' if research[key]['status']=='retry_pending' else 'retry limit reached'))
            errors,pending,retry_delay=research_work(research,unfinished,time.time())
            for saved_record in records.values():
                decision=saved_record.get('decision')
                if decision and decision.get('source')=='codex':
                    stats_core.validate_coding({'decision':decision,'evidence':['Retained canonical source evidence']},{},{})
                    saved_record['decision']=stats_core.normalized_decision(decision)
            state['updated_at']=datetime.now(timezone.utc).isoformat();raw=json.dumps(state,ensure_ascii=False,separators=(',',':')).encode();path=folder/'records.gz';path.write_bytes(gzip.compress(raw));uri=f'gs://{cfg["bucket"]}/statistics/records/{fingerprint(raw)}.json.gz';cloud.storage_upload(path,uri)
            output=json.dumps([flatten(r) for r in public_records(records)],ensure_ascii=False,separators=(',',':')).encode();compressed=__import__('base64').b64encode(gzip.compress(output)).decode()
            questions.update({k:v['notes'] for k,v in research.items() if v.get('status')=='needs_review'})
            message='Statistics published'
            if errors:message+='; '+str(len(errors))+' technical update(s) '+('need repair' if any(e['status']=='failed' for e in errors.values()) else 'queued for automatic retry')
            update(message,publish={'gzip_base64':compressed,'sha256':fingerprint(output),'count':len(records)},data_uri=uri,index_revision=fingerprint(index),questions=questions,technical_errors=errors,answered=answered,pending=pending,retry_after_seconds=retry_delay,finish=True)
        except Exception as error:
            update('Statistics update failed: '+type(error).__name__+': '+str(error)[:400],failed=True,finish=True)
            raise
if __name__=='__main__':main()
