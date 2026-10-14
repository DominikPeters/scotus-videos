"""Read-only LinkedIn profile fallback; cookies never enter the model workspace."""
import json,re
from html.parser import HTMLParser
from urllib.parse import urlsplit
import requests


def profile_url(url):
    p=urlsplit(url)
    if (p.scheme!='https' or p.hostname not in ('linkedin.com','www.linkedin.com') or
        p.username or p.password or p.port not in (None,443) or
        not re.fullmatch(r'/in/[A-Za-z0-9_-]{1,150}/?',p.path)):
        raise ValueError('Only LinkedIn profile pages are supported')
    return 'https://www.linkedin.com'+p.path.rstrip('/')+'/'


def image_url(url):
    try:
        p=urlsplit(url)
        return p.scheme=='https' and p.hostname=='media.licdn.com' and not p.username and not p.password and p.port in (None,443)
    except ValueError:return False


class Profile(HTMLParser):
    def __init__(self):super().__init__();self.meta={};self.images=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='meta' and a.get('property',a.get('name')) in ('og:title','og:description','description','og:image'):
            self.meta[a.get('property',a.get('name'))]=a.get('content','')[:2000]
        if tag=='img' and re.search(r'profile|portrait',a.get('alt',''),re.I):
            for k in ('src','data-delayed-url'):
                if image_url(a.get(k,'')):self.images.append(a[k])


class PhotoAccess:
    def __init__(self,cloud,settings):self.cloud=cloud;self.secret=settings.get('linkedin_secret');self.calls=0
    def definitions(self):
        if not self.secret:return []
        return [{'type':'function','name':'photo_fetch_authenticated',
            'description':'Fallback after native web search: fetch a known LinkedIn /in/ profile using owner-provided cookies. Returns only profile evidence and portrait URLs, never cookies. Read-only; maximum four fetches per task.',
            'inputSchema':{'type':'object','properties':{'url':{'type':'string'}},'required':['url'],'additionalProperties':False}}]
    def invoke(self,name,args):
        if name!='photo_fetch_authenticated':raise ValueError('Unknown photo tool')
        url=profile_url(args['url'])
        if self.calls>=4: return {'error':'Authenticated profile fetch limit reached'}
        self.calls+=1
        credential=json.loads(self.cloud.secret(self.secret))
        cookies=credential['cookies']
        if not isinstance(cookies,dict) or not cookies.get('li_at'):raise ValueError('LinkedIn session unavailable')
        allowed=('li_at','JSESSIONID','bcookie','bscookie','liap','lang')
        cookies={k:v for k,v in cookies.items() if k in allowed and isinstance(v,str) and not any(c in v for c in '\r\n')}
        # No redirects: a challenge/login page must never forward the session.
        with requests.get(url,cookies=cookies,headers={'User-Agent':credential.get('user_agent','Mozilla/5.0'),
            'Accept':'text/html','Accept-Language':'en-US,en;q=0.9'},timeout=20,stream=True,allow_redirects=False) as response:
            if response.status_code!=200:
                return {'profile_url':url,'error':'LinkedIn session was not accepted or the profile is blocked','http_status':response.status_code}
            if 'text/html' not in response.headers.get('Content-Type',''):
                return {'profile_url':url,'error':'Profile HTML unavailable'}
            data=bytearray()
            for block in response.iter_content(16384):
                data.extend(block)
                if len(data)>2097152:return {'profile_url':url,'error':'Profile response exceeds the small-transfer limit'}
        page=Profile();page.feed(data.decode('utf-8',errors='replace'))
        portraits=page.images
        if image_url(page.meta.get('og:image','')):portraits.insert(0,page.meta['og:image'])
        result={'profile_url':url,'title':page.meta.get('og:title',''),'description':page.meta.get('og:description',page.meta.get('description','')),
                'portrait_urls':list(dict.fromkeys(portraits))[:8],'untrusted_source_data':True}
        if not result['portrait_urls']:result['private_note']='No portrait URL was exposed; a login/challenge page may have been returned. Continue with another source.'
        # Defense against a site echoing a cookie into metadata; never return raw HTML.
        text=json.dumps(result)
        for value in cookies.values():
            if len(value)>7:text=text.replace(value,'[redacted]')
        return json.loads(text)
