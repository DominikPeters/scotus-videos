"""Bounded private failure evidence, with credentials removed before storage."""
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import traceback


class Redactor:
    def __init__(self, *values):
        self.secrets = set()
        for value in values: self._collect(value)

    def _collect(self, value, key=''):
        if isinstance(value, dict):
            for name, item in value.items(): self._collect(item, name)
        elif isinstance(value, (list, tuple)):
            for item in value: self._collect(item, key)
        elif isinstance(value, str) and len(value)>7 and re.search(r'key|token|password|secret|authorization|session_url',key,re.I):
            self.secrets.add(value)

    def text(self, value, limit=16000):
        text = str(value)
        for secret in sorted(self.secrets,key=len,reverse=True): text=text.replace(secret,'[redacted]')
        text=re.sub(r'(?i)(Bearer\s+)[^\s\"\']+',r'\1[redacted]',text)
        text=re.sub(r'\b(?:eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|gh[psu]_[A-Za-z0-9]+|sk-[A-Za-z0-9_-]+|ya29\.[A-Za-z0-9_-]+)', '[redacted]',text)
        text=re.sub(r'(?i)((?:refresh_token|access_token|client_secret|private_key|password)[\"\']?\s*[:=]\s*[\"\']?)[^\s,\"\']+',r'\1[redacted]',text)
        text=re.sub(r'(https?://[^\s?\"\']+)\?[^\s\"\']+',r'\1?[query redacted]',text)
        return text[-limit:]

    def value(self, value):
        if isinstance(value, dict):
            return {key: ('[redacted]' if re.search(r'key|token|password|secret|authorization|session_url',key,re.I)
                         else self.value(item)) for key,item in value.items()}
        if isinstance(value, list): return [self.value(item) for item in value]
        return self.text(value) if isinstance(value,str) else value


class CommandFailure(RuntimeError):
    def __init__(self, command, returncode, stderr):
        super().__init__('Workflow command failed')
        self.cmd,self.returncode,self.stderr=command,returncode,stderr


def run_command(command, *, cwd=None, on_line=None, timeout=1800):
    """Capture a stderr tail without storing an unbounded encoder/browser log."""
    process=subprocess.Popen(command,cwd=cwd,stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE if on_line else subprocess.DEVNULL,
                             stderr=subprocess.PIPE,text=True,start_new_session=True)
    tail=deque(maxlen=32)
    def consume():
        for block in iter(lambda:process.stderr.read(1024),''): tail.append(block)
    thread=threading.Thread(target=consume,daemon=True);thread.start()
    def terminate():
        try: os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError: pass
    timer=threading.Timer(timeout,terminate);timer.daemon=True;timer.start()
    try:
        if on_line:
            for line in process.stdout: on_line(line)
        result=process.wait();thread.join(timeout=3)
        if result: raise CommandFailure(command,result,''.join(tail)[-16000:])
    except BaseException:
        terminate();process.wait();thread.join(timeout=3)
        raise
    finally:
        timer.cancel()
        if process.stdout: process.stdout.close()
        process.stderr.close()


def failure_report(error, job, stage, task, category, *sensitive):
    redact=Redactor(*sensitive)
    message=redact.text(error,4000)
    command=redact.value(getattr(error,'cmd',None))
    stable=re.sub(r'/tmp/[^\s/]+','/tmp/workspace',message)
    fingerprint=hashlib.sha256(json.dumps([type(error).__name__,stable,category],sort_keys=True).encode()).hexdigest()
    frames=[{'file':Path(frame.filename).name,'line':frame.lineno,'function':frame.name}
            for frame in traceback.extract_tb(error.__traceback__)[-24:]]
    return {'schema_version':1,'fingerprint':fingerprint,'recording':job['id'],'stage':stage,'task':task,
            'attempt':job['stages'][stage]['attempt'],'category':category,
            'exception':type(error).__name__,'message':message,'frames':frames,
            'command':command,'returncode':getattr(error,'returncode',None),
            'stderr':redact.text(getattr(error,'stderr','') or '',16000),
            'execution':os.environ.get('CLOUD_RUN_EXECUTION'), 'cloud_job':os.environ.get('CLOUD_RUN_JOB'),
            'inputs':redact.value({'pdf_url':job.get('pdf_url'),'audio_url':job.get('audio_url'),
                                  'prior_results':{name:entry.get('result') for name,entry in job['stages'].items() if entry['status']=='complete'}})}
