"""Save owner-provided LinkedIn cookies privately; grant only photo/enrich access."""
import argparse,json,subprocess,tempfile
from pathlib import Path


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--credentials',type=Path,required=True);cli.add_argument('--config',type=Path,required=True)
    cli.add_argument('--gcloud',default='gcloud');args=cli.parse_args()
    credential=json.loads(args.credentials.read_text())
    if not isinstance(credential.get('cookies'),dict) or not credential['cookies'].get('li_at'):
        raise ValueError('Supply a private JSON cookie bundle containing li_at')
    if args.credentials.stat().st_mode&0o077:raise ValueError('Cookie file must be private (chmod 600)')
    cfg=json.loads(args.config.read_text());project=cfg['project'];secret='scotus-video-linkedin'
    def call(*a,optional=False):
        r=subprocess.run([args.gcloud,*a,'--project='+project,'--quiet'],capture_output=True,text=True,timeout=90)
        if r.returncode and not optional:raise RuntimeError('Photo credential setup failed')
        return r.stdout if not r.returncode else None
    if call('secrets','describe',secret,optional=True) is None:
        call('secrets','create',secret,'--replication-policy=automatic')
    call('secrets','versions','add',secret,'--data-file='+str(args.credentials.resolve()))
    call('secrets','add-iam-policy-binding',secret,'--member=serviceAccount:scotus-video-enrich@'+project+'.iam.gserviceaccount.com',
         '--role=roles/secretmanager.secretAccessor')
    current=json.loads(call('secrets','versions','access','latest','--secret=scotus-video-enrich-config'))
    current['linkedin_secret']=secret
    with tempfile.NamedTemporaryFile(mode='w') as f:
        json.dump(current,f);f.flush();call('secrets','versions','add','scotus-video-enrich-config','--data-file='+f.name)
    cfg['linkedin_secret']=secret;args.config.write_text(json.dumps(cfg));args.config.chmod(0o600)
    profile=args.config.parent/'worker-profile.json'
    if profile.exists():
        p=json.loads(profile.read_text());p['linkedin_secret']=secret;profile.write_text(json.dumps(p));profile.chmod(0o600)
    print('LinkedIn session stored privately; only the enrichment/photo account can read it.')

if __name__=='__main__':main()
