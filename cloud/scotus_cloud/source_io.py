"""Official media transfer for the preparation worker, separate from account access."""
from pathlib import Path
import shutil
from urllib.request import Request,urlopen
from urllib.parse import urlsplit


def download_official(url,path):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname not in ('www.supremecourt.gov','supremecourt.gov') or parsed.username or parsed.password:
        raise ValueError('Source URL must be on the Court website')
    with urlopen(Request(url,headers={'User-Agent':'Scotus video source worker'}),timeout=60) as response,Path(path).open('wb') as out:
        if urlsplit(response.url).hostname not in ('www.supremecourt.gov','supremecourt.gov'):raise ValueError('Unexpected media redirect')
        shutil.copyfileobj(response,out,1024*1024)
