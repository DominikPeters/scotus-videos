"""Small official-page polling; audio and PDFs remain cloud worker inputs."""
from datetime import date,datetime,timezone,timedelta
from zoneinfo import ZoneInfo
from calendar import month_name
import io
from html.parser import HTMLParser
import re
from urllib.parse import urljoin,urlsplit
from urllib.request import Request,urlopen
from urllib.error import HTTPError


class Rows(HTMLParser):
    def __init__(self):super().__init__();self.rows=[];self.row=None;self.links=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='tr':self.row={'text':[],'links':[]}
        if tag=='a' and attrs.get('href'):
            self.links.append(attrs['href'])
            if self.row is not None:self.row['links'].append(attrs['href'])
    def handle_data(self,data):
        if self.row is not None:self.row['text'].append(data)
    def handle_endtag(self,tag):
        if tag=='tr' and self.row is not None:self.rows.append(self.row);self.row=None


def official(url):
    p=urlsplit(url)
    if p.scheme!='https' or p.hostname not in ('supremecourt.gov','www.supremecourt.gov') or p.username:raise ValueError('Official Court URL required')
    with urlopen(Request(url,headers={'User-Agent':'Scotus video source monitor'}),timeout=15) as response:
        if urlsplit(response.url).hostname not in ('supremecourt.gov','www.supremecourt.gov'):raise ValueError('Unexpected source redirect')
        data=response.read(524289)
        if len(data)>524288:raise ValueError('Source listing too large')
    return data.decode('utf-8-sig')


def recordings(term, fetch=official, known=()):
    listing=f'https://www.supremecourt.gov/oral_arguments/argument_audio/{term}'
    parser=Rows();parser.feed(fetch(listing));records=[]
    for row in parser.rows:
        text=' '.join(' '.join(row['text']).split())
        match=re.search(r'\b(\d{2}(?:-\d+|[A-Z]\d+))\b\s*(.*?)\s*(\d{2}/\d{2}/\d{2,4})\b',text)
        details=next((absolute for url in row['links'] if '/oral_arguments/audio/' in (absolute:=urljoin(listing,url)).lower()),None)
        if not match or not details:continue
        raw=match[3];argued=datetime.strptime(raw,'%m/%d/%y' if len(raw)==8 else '%m/%d/%Y').date().isoformat()
        if argued+'-'+match[1] in known:continue
        detail=Rows();detail.feed(fetch(details));links=[urljoin(details,url) for url in detail.links]
        audio=next((url for url in links if urlsplit(url).path.lower().endswith('.mp3')),None)
        pdf=next((url for url in links if '/argument_transcripts/' in url.lower() and urlsplit(url).path.lower().endswith('.pdf')),None)
        if audio and pdf:records.append({'docket':match[1],'case_name':match[2],'argument_date':argued,'audio_url':audio,'pdf_url':pdf,'title':match[2],'source_page':details})
    return records


def calendar_groups(text, year):
    """Keep consolidated dockets together as one scheduled argument."""
    heading=re.compile(r'(?:Monday|Tuesday|Wednesday|Thursday|Friday),\s+([A-Za-z]+)\s+(\d{1,2})(?:,\s*\d{4})?')
    dates=list(heading.finditer(text));result={}
    for index,match in enumerate(dates):
        month=list(month_name).index(match[1].capitalize());day=date(year,month,int(match[2])).isoformat()
        body=text[match.end():dates[index+1].start() if index+1<len(dates) else len(text)]
        blocks=re.split(r'\(\d+\)',body);groups=[]
        for block in blocks:
            dockets=sorted(set(re.findall(r'\b\d{2}(?:-\d+|[A-Z]\d+)\b',block)))
            if dockets:groups.append(dockets)
        result[day]=groups
    if not dates:raise ValueError('Argument calendar has no date headings')
    return result


def official_pdf(url):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname!='www.supremecourt.gov' or not parsed.path.startswith('/oral_arguments/argument_calendars/') or not parsed.path.lower().endswith('.pdf'):
        raise ValueError('Official argument calendar required')
    with urlopen(Request(url,headers={'User-Agent':'Scotus video source monitor'}),timeout=15) as response:
        if urlsplit(response.url).hostname!='www.supremecourt.gov':raise ValueError('Unexpected calendar redirect')
        data=response.read(524289)
    if len(data)>524288 or not data.startswith(b'%PDF'):raise ValueError('Invalid calendar PDF')
    from pypdf import PdfReader
    reader=PdfReader(io.BytesIO(data))
    if len(reader.pages)>4:raise ValueError('Unexpected calendar length')
    return '\n'.join(page.extract_text() for page in reader.pages)


def argument_calendar(today,fetch=official,pdf_text=official_pdf):
    listing='https://www.supremecourt.gov/oral_arguments/calendarsandlists.aspx'
    parser=Rows();parser.feed(fetch(listing));groups=[];sources=[]
    # A December session can begin in November, and similarly across other months.
    following=(today.replace(day=28)+timedelta(days=4)).replace(day=1)
    previous=today.replace(day=1)-timedelta(days=1)
    months=[month_name[d.month]+str(d.year) for d in (previous,today,following)]
    for link in dict.fromkeys(parser.links):
        url=urljoin(listing,link)
        if '/argument_calendars/MonthlyArgumentCal' not in url or not any(m in url for m in months):continue
        year=int(re.search(r'(\d{4})\.pdf$',url,re.I)[1])
        entries=calendar_groups(pdf_text(url),year);groups.extend(entries.get(today.isoformat(),[]));sources.append(url)
    return {'date':today.isoformat(),'groups':groups,'sources':sources}


def argument_window(now,groups,jobs):
    local=now.astimezone(ZoneInfo('America/New_York'))
    if not (13<=local.hour<18 or (local.hour==18 and local.minute==0)) or not groups:return False
    found={job['docket'] for job in jobs.values() if job.get('argument_date')==local.date().isoformat() and job.get('audio_url') and job.get('pdf_url')}
    return any(not found.intersection(group) for group in groups)


def discover(dashboard, settings, now=None):
    profile=settings.get('discovery',{})
    if not profile.get('enabled'):return 0
    now=now or datetime.now(timezone.utc);today=now.astimezone(ZoneInfo('America/New_York')).date()
    context=dashboard.call('discovery_context')
    if context['paused']:return 0
    cached=context.get('calendar',{})
    if cached.get('date')!=today.isoformat() and context.get('calendar_retry_after',0)<=now.timestamp():
        try:
            cached=argument_calendar(today)
            dashboard.call('discovery_calendar',calendar=cached)
        except Exception as error:
            dashboard.call('discovery_calendar',error=type(error).__name__)
    groups=cached.get('groups',[]) if cached.get('date')==today.isoformat() else []
    fast=profile.get('argument_window_enabled',True) and argument_window(now,groups,context.get('jobs',{}))
    seconds=600 if fast else profile.get('interval_seconds',1800)
    # Callback-triggered controller runs share this durable rate limit.
    if not dashboard.call('discovery_claim',seconds=seconds,mode='argument_window' if fast else 'normal'):return 0
    term=today.year-(today.month<10)
    known={job['argument_date']+'-'+job['docket'] for job in context.get('jobs',{}).values() if job.get('audio_url') and job.get('pdf_url')}
    known.update(settings.get('uploaded_recordings',[]))
    records=recordings(term,known=known)
    return dashboard.call('discovery_add',records=records,uploaded=settings.get('uploaded_recordings',[]))['added']


def watched_recording(watch, fetch=official):
    """Read only this case's HTML listing; never download media while polling."""
    page=watch['source_page']
    try:html=fetch(page)
    except HTTPError as error:
        if error.code==404:return None
        raise
    parser=Rows();parser.feed(html)
    links=[urljoin(page,link) for link in parser.links]
    docket=watch['docket']
    audio=next((url for url in links if urlsplit(url).path.lower().endswith('/'+docket+'.mp3')),None)
    pdf=next((url for url in links if '/argument_transcripts/' in url.lower() and
              urlsplit(url).path.rsplit('/',1)[-1].startswith(docket+'_') and urlsplit(url).path.lower().endswith('.pdf')),None)
    if not audio or not pdf:return None
    return {key:watch[key] for key in ('docket','case_name','argument_date','source_page')} | {'title':watch['case_name'],'audio_url':audio,'pdf_url':pdf}


def poll_watches(dashboard,settings):
    results=[]
    for identity in settings.get('source_watch_ids',[]):
        watch=dashboard.call('source_watch_claim',watch=identity)
        if not watch:continue
        try:
            recording=watched_recording(watch)
            results.append(dashboard.call('source_watch_result',watch=identity,recording=recording))
        except Exception as error:
            # Preserve a small diagnostic without URLs, headers or account data.
            results.append(dashboard.call('source_watch_result',watch=identity,error=type(error).__name__))
    return results
