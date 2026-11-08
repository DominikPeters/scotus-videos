"""Atomically replace only dashboard source files over SSH. Preserve all state."""
import argparse
import hashlib
import io
from pathlib import Path
import shlex
import subprocess
import tarfile


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--ssh', default='kas')
    cli.add_argument('--ui-only',action='store_true',help='Replace only frontend files, preserving the deployed backend')
    cli.add_argument('--include',action='append',help='Deploy only these source paths, in order')
    cli.add_argument('--check-baseline',type=Path,help='Reject a concurrent source change relative to this checkout snapshot')
    args = cli.parse_args()
    source = Path(__file__).resolve().parents[1] / 'dashboard'
    ui = ['public/index.php', 'public/privacy.html', 'public/app.css', 'public/main.js', 'public/api.js', 'public/dom.js', 'public/model.js', 'public/ui.js',
          'public/push.js', 'public/view-list.js', 'public/view-clips.js', 'public/view-case.js', 'public/view-settings.js', 'public/sw.js',
          'public/brand-icons.svg', 'public/bootstrap-icons-LICENSE.txt', 'public/manifest.webmanifest', 'public/icon-180.png', 'public/icon-192.png', 'public/icon-512.png']
    files = ['private/research.php','private/attempts.php','private/maintenance.php','private/card_import.php','private/deployment.php','private/kick.php','private/photos.php','private/podcast.php','private/cleanup.php','private/spotify.php','private/clips.php', 'private/state.php', 'private/recovery.php', 'private/reviews.php', 'private/connections.php', 'private/push.php',
             'private/statistics.php', 'public/api.php', 'public/oauth-callback.php', 'public/instagram-callback.php', 'public/.htaccess', *ui]
    if args.ui_only: files = ui
    if args.include:
        if set(args.include)-set(files):raise ValueError('Unexpected source paths')
        files=args.include
    expected={name:(hashlib.sha256((args.check_baseline/name).read_bytes()).hexdigest() if (args.check_baseline/name).exists() else None) for name in files} if args.check_baseline else {}
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        for name in files: archive.add(source / name, arcname=name)
    payload = buffer.getvalue()
    if len(payload) > 128 * 1024: raise ValueError('Dashboard source exceeds small-transfer limit')
    remote = '''import hashlib,io,json,os,pathlib,sys,tarfile,tempfile,subprocess,fcntl,atexit
private=pathlib.Path('/www/htdocs/w008ef9a/.scotus-youtube-private')
public=pathlib.Path('/www/htdocs/w008ef9a/scotusstats/youtube')
lock=open(private/'.source-deploy.lock','a');fcntl.flock(lock,fcntl.LOCK_EX)
protected=['credentials.json','config.php']
before={name:hashlib.sha256((private/name).read_bytes()).hexdigest() for name in protected}
files=tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read(131073)),mode='r:gz')
allowed=set(%s)
expected=%s
ready=[]
if set(files.getnames())!=allowed: raise RuntimeError('Unexpected deployment files')
for name in %s:
    root=private if name.startswith('private/') else public
    path=root/pathlib.PurePosixPath(name).name
    data=files.extractfile(name).read(131073)
    if len(data)>131072: raise RuntimeError('Source is too large')
    digest=hashlib.sha256(data).hexdigest()
    current=hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    if name in expected and current not in (expected[name],digest):raise RuntimeError('Source changed concurrently: '+name)
    descriptor,tmp=tempfile.mkstemp(prefix='.deploy-',dir=root)
    atexit.register(lambda name=tmp:os.path.exists(name) and os.unlink(name))
    with os.fdopen(descriptor,'wb') as stream: stream.write(data)
    os.chmod(tmp,0o640 if root==private else 0o644)
    if name.endswith('.php'):subprocess.run(['php','-l',tmp],check=True,capture_output=True)
    ready.append((tmp,path))
for tmp,path in ready:os.replace(tmp,path)
after={name:hashlib.sha256((private/name).read_bytes()).hexdigest() for name in protected}
if before!=after: raise RuntimeError('Protected files changed')
for name in ('dashboard.js','dashboard.css'):
    (public/name).unlink(missing_ok=True)  # Replaced by the module app.
print(json.dumps({'source_files':len(allowed),'passkeys_preserved':True,'configuration_preserved':True}))
''' % (repr(files), repr(expected), repr(files))
    result = subprocess.run(['ssh', args.ssh, 'python3 -c ' + shlex.quote(remote)], input=payload,
                            capture_output=True, timeout=60)
    if result.returncode: raise RuntimeError('SSH source deployment failed: ' + result.stderr.decode()[-1500:])
    print(result.stdout.decode().strip()); print('Uploaded source bytes:', len(payload))


if __name__ == '__main__': main()
