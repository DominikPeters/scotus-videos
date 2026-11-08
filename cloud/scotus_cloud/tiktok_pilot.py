"""Explicit draft-only TikTok pilot, isolated from normal recording processing."""
import json, os, subprocess, tempfile
from pathlib import Path
from .google import Google, split_gs


def main():
    if os.environ.get('SCOTUS_RUNTIME_CONFIG'):
        from .secret_store import runtime_settings
        settings=runtime_settings('/secrets/worker/config.json')
        project=settings['project']
    else:
        project = os.environ['SCOTUS_PROJECT']
    source = os.environ['SCOTUS_TIKTOK_SOURCE']
    output = os.environ['SCOTUS_TIKTOK_OUTPUT']
    bucket, _ = split_gs(source)
    if bucket != project + '-scotus-video-media' or split_gs(output)[0] != bucket:
        raise ValueError('Use this project media bucket')
    cloud = Google(project)
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        session = folder/'session.json'
        session.write_bytes(cloud.secret('scotus-video-tiktok-session'))
        session.chmod(0o600)
        video = folder/'video.mp4'
        cloud.storage_download(source, video)
        caption = folder/'caption.txt'
        caption.write_text(os.environ['SCOTUS_TIKTOK_CAPTION'])
        result = folder/'result.json'
        command = ['node', '/app/render/tiktok-draft.cjs', str(session), str(video), str(caption), str(result)]
        if os.environ.get('SCOTUS_TIKTOK_EDIT_DRAFT'):
            command.append(os.environ['SCOTUS_TIKTOK_EDIT_DRAFT'])
        run = subprocess.run(command, timeout=300)
        session.unlink(missing_ok=True)
        if result.exists():
            cloud.storage_upload(result, output+'/result.json', 'application/json')
        if Path(str(result)+'.png').exists():
            cloud.storage_upload(Path(str(result)+'.png'), output+'/preview.png', 'image/png')
        print(json.dumps({'tiktok_pilot': 'draft_saved' if run.returncode == 0 else 'needs_review', 'output': output}))
        if run.returncode: raise SystemExit(1)


if __name__ == '__main__': main()
