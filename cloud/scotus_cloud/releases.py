"""The worker image owns its release ID and immutable source manifest."""
import json,re,sys,uuid
from datetime import datetime,timezone
from pathlib import Path

def image_release(root='/app'):
 path=Path(root)/'.workflow/release.json'
 return json.loads(path.read_text()) if path.is_file() else None

def image_source(root='/app'):
 path=Path(root)/'.workflow/source.json'
 if path.is_file():return json.loads(path.read_text())
 from .repair_policy import baseline_files
 return baseline_files(root)

def stamp(root,identity=None):
 from .repair_policy import baseline_files
 root=Path(root);identity=identity or ('worker-'+datetime.now(timezone.utc).strftime('%Y%m%d')+'-'+uuid.uuid4().hex[:8])
 if not re.fullmatch(r'worker-[a-zA-Z0-9-]{1,60}',identity):raise ValueError('Invalid worker release ID')
 source=baseline_files(root);folder=root/'.workflow';folder.mkdir(exist_ok=True)
 (folder/'source.json').write_text(json.dumps(source,ensure_ascii=False))
 record={'schema_version':1,'id':identity,'source_files':len(source)}
 (folder/'release.json').write_text(json.dumps(record));return record

def current(google,settings):
 """Only the controller reads this single deployment record."""
 uri=settings.get('worker_release_uri')
 if not uri:return None
 record=google.storage_json(uri,max_bytes=16384)
 if not isinstance(record,dict) or not re.fullmatch(r'worker-[a-zA-Z0-9-]{1,60}',record.get('id','')):raise ValueError('Worker deployment record unavailable')
 expected=f'gs://{settings["bucket"]}/releases/{record["id"]}/source.json'
 if record.get('source_uri')!=expected or '@sha256:' not in record.get('image',''):raise ValueError('Invalid worker deployment record')
 return record

def repair_source(google,settings):
 record=current(google,settings)
 if record:return google.storage_json(record['source_uri'],max_bytes=3145728),record['id']
 return google.storage_json(settings['recovery']['baseline_uri'],max_bytes=2097152),None

if __name__=='__main__':
 if sys.argv[1]!='stamp':raise ValueError('Unknown release command')
 root=Path(sys.argv[2]);name=root/'.workflow-release-id'
 print(json.dumps(stamp(root,name.read_text().strip() if name.is_file() else None)))
