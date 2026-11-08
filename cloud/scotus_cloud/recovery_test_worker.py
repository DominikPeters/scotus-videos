"""Run trusted regression tests in a separate job with no account credentials."""
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile

from .google import Google
from .model import digest_json
from .repair_policy import baseline_files,verify_release
from .releases import image_source,image_release
from .diagnostics import Redactor


def run_probe(baseline,probe,folder,google):
    folder=Path(folder)
    for name,text in baseline.items():
        p=folder/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    inputs=folder/'input';inputs.mkdir(exist_ok=True)
    (inputs/'context.json').write_text(json.dumps(probe['context']))
    total=0
    for name,uri in probe.get('artifacts',{}).items():
        value=google.storage_json(uri,max_bytes=2097152);text=json.dumps(value);total+=len(text)
        if total>4194304:break
        (inputs/(name+'.json')).write_text(text)
    script=folder/'probe.py';script.write_text(probe['script'])
    clean={'PATH':os.environ.get('PATH','/usr/local/bin:/usr/bin:/bin'),'PYTHONPATH':str(folder),
           'PYTHONUNBUFFERED':'1','PYTHONDONTWRITEBYTECODE':'1'}
    def limits():
        import resource
        resource.setrlimit(resource.RLIMIT_FSIZE,(65536,65536))
    try:
        with (folder/'probe-output.txt').open('wb') as output:
            result=subprocess.run(['python',str(script)],cwd=folder,env=clean,stdin=subprocess.DEVNULL,
                stdout=output,stderr=subprocess.STDOUT,timeout=120,preexec_fn=limits)
        passed=result.returncode==0
    except subprocess.TimeoutExpired:passed=False
    output=(folder/'probe-output.txt').read_text(errors='replace')[-20000:]
    return {'schema_version':1,'kind':'probe','passed':passed,'output':Redactor(probe['context']).text(output,20000)}


def test_release(baseline,release,folder,release_id=None):
    verify_release(baseline,release,release_id)
    folder=Path(folder)
    # Regression tests import deployment helpers by path. These are immutable
    # support code from the image, outside the stage-editable workflow baseline.
    support=Path(__file__).resolve().parents[1]/'infra'
    if support.is_dir():
        (folder/'infra').mkdir(parents=True,exist_ok=True)
        for source in support.glob('*.py'):shutil.copy2(source,folder/'infra'/source.name)
    for name,text in {**baseline,**release['files']}.items():
        target=folder/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text)
    clean={'PATH':os.environ.get('PATH','/usr/local/bin:/usr/bin:/bin'),'PYTHONPATH':str(folder),
           'PYTHONDONTWRITEBYTECODE':'1','PYTHONUNBUFFERED':'1'}
    commands=[['python','-m','unittest','discover','-s','tests','-v']]
    for name in release['files']:
        if name.endswith(('.js','.cjs')): commands.append(['node','--check',name])
    reports=[]
    for command in commands:
        result=subprocess.run(command,cwd=folder,env=clean,capture_output=True,text=True,timeout=120)
        reports.append({'check':' '.join(command),'passed':result.returncode==0,
                        'output':(result.stdout+result.stderr)[-16000:]})
    return {'schema_version':1,'release_sha256':digest_json(release),'passed':all(r['passed'] for r in reports),'checks':reports}


def main():
    if not os.environ.get('CLOUD_RUN_JOB'): raise RuntimeError('Cloud test jobs only')
    google=Google(os.environ['SCOTUS_PROJECT'])
    uri=os.environ.get('SCOTUS_TEST_SOURCE_URI');out=os.environ['SCOTUS_TEST_RESULT_URI']
    baseline_uri=os.environ.get('SCOTUS_TEST_BASELINE_URI')
    record=image_release('/app')
    baseline=google.storage_json(baseline_uri,max_bytes=2097152) if baseline_uri else image_source('/app')
    probe_uri=os.environ.get('SCOTUS_PROBE_URI')
    release=google.storage_json(uri,max_bytes=262144) if uri else None
    with tempfile.TemporaryDirectory(prefix='repair-tests-') as folder:
        try:
            if probe_uri:report=run_probe(baseline,google.storage_json(probe_uri,max_bytes=262144),folder,google)
            else:report=test_release(baseline,release,folder,record['id'] if record else None)
        except Exception as error: report={'schema_version':1,'release_sha256':digest_json(release),'passed':False,'checks':[{'passed':False,'output':type(error).__name__+': '+str(error)[:1000]}]}
        path=Path(folder)/'result.json';path.write_text(json.dumps(report))
        google.storage_upload(path,out,'application/json')
    print(json.dumps({'passed':report['passed']}))


if __name__=='__main__': main()
