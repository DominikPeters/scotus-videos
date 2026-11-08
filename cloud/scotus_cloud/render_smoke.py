"""A short cloud-only encoding check, with tiny fixture and bounded results."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from .google import Google

def main():
    if not os.environ.get('CLOUD_RUN_JOB'): raise SystemExit('This check runs inside Cloud Run.')
    cloud = Google(os.environ['SCOTUS_PROJECT']); prefix = os.environ['SCOTUS_SMOKE_PREFIX']
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); bundle = root / 'bundle'; shutil.copytree('/app/render', bundle)
        for name in ('manifest.json', 'plan.json'):
            cloud.storage_download(prefix + '/' + name, bundle / name)
        plan = json.loads((bundle / 'plan.json').read_text())
        parts = []
        for chunk in plan['chunks']:
            output = root / f'chunk-{chunk["index"]}.mp4'
            subprocess.run(['node', '/app/render/chunk.js', str(bundle), str(bundle / 'plan.json'), str(chunk['index']), str(output)], check=True)
            parts.append("file '" + output.name + "'")
        (root / 'parts.txt').write_text('\n'.join(parts) + '\n')
        output = root / 'cloud-test.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-y', '-hide_banner', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
                        '-i', str(root / 'parts.txt'), '-c', 'copy', str(output)], check=True)
        probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames',
                        '-show_entries', 'stream=nb_read_frames,width,height,r_frame_rate,duration', '-of', 'json', str(output)]))['streams'][0]
        if int(probe['nb_read_frames']) != plan['total_frames']: raise RuntimeError('Joined frame count differs')
        cloud.storage_upload(output, prefix + '/cloud-test.mp4', 'video/mp4')
        preview = root / 'chunk-0-preview.png'
        cloud.storage_upload(preview, prefix + '/preview.png', 'image/png')
        receipt = {'frames': int(probe['nb_read_frames']), 'stream': probe, 'cloud_job': os.environ['CLOUD_RUN_JOB'],
                   'video_bytes': output.stat().st_size, 'preview_bytes': preview.stat().st_size,
                   'chunks': len(plan['chunks']), 'large_transfers_inside_cloud': True}
        (root / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        cloud.storage_upload(root / 'receipt.json', prefix + '/receipt.json', 'application/json')
        print(json.dumps(receipt))

if __name__ == '__main__': main()
