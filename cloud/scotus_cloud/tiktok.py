"""TikTok Studio transfers selected explicitly through clip controls."""
import json, os, subprocess, uuid
from pathlib import Path


def browser_mode(mode, state):
    if state.get('publish_pending') or state.get('published'): return 'reconcile_publish'
    if state.get('draft_pending'): return 'reconcile_draft'
    if state.get('saved') and mode == 'tiktok_draft': return 'reconcile_draft'
    return 'publish' if mode == 'tiktok_publish' else 'draft'


def transfer(job, clip, settings, cloud, lease, folder):
    token = lease.dashboard.call('auth_claim', name='tiktok')
    if not token: raise ValueError('TikTok is busy with another clip. Retry shortly.')
    lease.auth = ('tiktok', token)
    try:
        state = clip.get('tiktok_checkpoint') or {}
        mode = browser_mode(clip['mode'], state)
        session = folder/'tiktok-session.json'
        session.write_bytes(cloud.secret('scotus-video-tiktok-session')); session.chmod(0o600)
        caption = clip['tiktok']['caption']
        (folder/'caption.txt').write_text(caption)
        existing = bool(clip.get('tiktok', {}).get('saved') or state.get('saved'))
        video = folder/'video.mp4'
        if not existing and not mode.startswith('reconcile_'):
            cloud.storage_download(clip['result']['video_uri'], video, expected_sha256=clip['result']['sha256'])
        result_path = folder/'tiktok-result.json'
        args = ['node', '/app/render/tiktok-draft.cjs', str(session), str(video), str(folder/'caption.txt'), str(result_path), caption if existing else '', mode]
        env = dict(os.environ, SCOTUS_TIKTOK_CHECKPOINTS='1')
        with subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env) as process:
            try:
                for line in process.stdout:
                    message = json.loads(line)
                    if 'checkpoint' in message:
                        lease.check(); lease.dashboard.call('auth_check', name='tiktok', token=token)
                        lease.call('checkpoint', checkpoint=message['checkpoint'])
                        process.stdin.write('ok\n'); process.stdin.flush()
                process.wait(timeout=30)
            except BaseException:
                process.kill(); process.wait(); raise
        session.unlink(missing_ok=True)
        prefix = f"gs://{settings['bucket']}/clips/{job['id']}/{clip['id']}/tiktok/{uuid.uuid4().hex}"
        if Path(str(result_path)+'.png').exists():
            cloud.storage_upload(Path(str(result_path)+'.png'), prefix+'/preview.png', 'image/png')
        if result_path.exists():
            cloud.storage_upload(result_path, prefix+'/result.json', 'application/json')
        result = json.loads(result_path.read_text()) if result_path.exists() else {}
        if process.returncode or not (result.get('saved') or result.get('published')):
            pending = result.get('step') in ('publish', 'save_draft', 'reconcile')
            raise ValueError('TikTok '+str(result.get('step', 'browser'))+' needs review. '+
                ('Retry will reconcile the existing transfer before taking further action.' if pending else 'The session may need refreshing, or TikTok may be showing a verification prompt.'))
        return {key: result[key] for key in ('saved', 'published', 'url') if key in result} | {'caption': caption, 'preview_uri': prefix+'/preview.png'}
    finally:
        lease.auth = None
        lease.dashboard.call('auth_release', name='tiktok', token=token)
