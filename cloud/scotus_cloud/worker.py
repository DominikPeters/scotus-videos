"""One Cloud Run stage/task; HTTP leases fence retries and overlapping jobs."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen
from urllib.parse import urlsplit
import uuid
import tarfile

from .alignment import align_recording, AlignmentReview
from .secret_store import runtime_settings
from .google import Google
from .model import plan_video, digest_json
from .prepare import prepare_transcript, audio_duration, sha256
from .remote import Dashboard, DashboardTransportError
from .diagnostics import failure_report, run_command


def save_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


from .source_io import download_official


class Lease:
    def __init__(self, dashboard, job, stage, dispatch_token, task):
        self.dashboard = dashboard
        self.data = {'job': job, 'stage': stage, 'dispatch_token': dispatch_token, 'task': task}
        self.progress, self.stopped, self.error = 0, threading.Event(), None
        self.auth = None
        self.last_heartbeat = time.monotonic()
        self.transport_error = None

    def call(self, op, **extra):
        return self.dashboard.call(op, **self.data, **extra)

    def update(self, value):
        self.check(); self.progress = min(1, max(self.progress, value))

    def claim(self):
        # A lost reply can follow a committed claim; reuse its identity on retry.
        identity=uuid.uuid4().hex
        for attempt in range(3):
            try:return self.call('claim',claim_id=identity)
            except (URLError,TimeoutError):
                if attempt==2:raise
                time.sleep(2**attempt)

    def check(self):
        if self.error:
            raise RuntimeError('Worker cancelled or lease lost') from self.error
        if self.transport_error and time.monotonic()-self.last_heartbeat >= 150:
            raise RuntimeError('Dashboard unavailable; lease renewal could not be confirmed') from self.transport_error

    def run(self):
        while not self.stopped.wait(30):
            try:
                result = self.call('heartbeat', progress=self.progress)
                if result.get('cancelled'):
                    raise RuntimeError('Cancelled')
                self.last_heartbeat = time.monotonic()
                self.transport_error = None
                if self.auth:
                    self.dashboard.call('auth_check', name=self.auth[0], token=self.auth[1])
            except DashboardTransportError as error:
                self.transport_error = error
                if time.monotonic()-self.last_heartbeat >= 150:
                    self.error = error
                    break
            except Exception as error:
                self.error = error
                break


def stage_run(stage, job, settings, cloud, lease, folder, task, local_video=None, local_transcript=None):
    prefix = f"gs://{settings['bucket']}/scratch/{job['id']}/{stage}/attempt-{job['stages'][stage]['attempt']}/{uuid.uuid4().hex}"

    def output(name, value=None):
        local = folder / name
        if value is not None:
            save_json(local, value)
        lease.check()
        uri = prefix + '/' + name
        cloud.storage_upload(local, uri, 'application/json' if name.endswith('.json') else 'application/octet-stream')
        return uri

    def load(uri, name,expected_sha256=None):
        target = folder / name
        if expected_sha256:cloud.storage_download(uri,target,expected_sha256=expected_sha256)
        else:cloud.storage_download(uri,target)
        return target

    if stage == 'prepare':
        pdf, audio = folder / 'transcript.pdf', folder / 'audio.mp3'
        download_official(job['pdf_url'], pdf); lease.update(.2)
        download_official(job['audio_url'], audio); lease.update(.6)
        catalog_path = Path(settings.get('speaker_catalog', '/app/speaker-catalog.json'))
        catalog = json.loads(catalog_path.read_text()) if catalog_path.is_file() else {}
        transcript = prepare_transcript(pdf, catalog, docket=job['docket'])
        transcript['audio'] = {'duration_seconds': audio_duration(audio), 'sha256': sha256(audio)}
        transcript['inputs'] = {'pdf_url': job['pdf_url'], 'audio_url': job['audio_url'], 'pdf_sha256': sha256(pdf)}
        return {'transcript_uri': output('transcript.json', transcript),
                'audio_uri': output('audio.mp3'), 'pdf_uri': output('transcript.pdf'),
                'duration_seconds':transcript['audio']['duration_seconds']}
    if stage == 'align':
        source = job['stages']['prepare']['result']
        transcript = json.loads(load(source['transcript_uri'], 'transcript.json').read_text())
        audio = load(source['audio_uri'], 'audio.mp3',transcript['audio']['sha256'])
        aligned = align_recording(audio, transcript, settings.get('model_path', '/opt/english-model'), lease.update,
                                  cpu_threads=int(os.environ.get('SCOTUS_ALIGN_THREADS','4')))
        transcript['paragraphs'] = aligned['paragraphs']
        transcript['alignment'] = {k: aligned[k] for k in ('configuration', 'coarse_audit', 'warnings', 'seams')}
        transcript['audio']['uri'] = source['audio_uri']
        return {'transcript_uri': output('aligned.json', transcript),
                'words_uri': output('words.json', aligned['words']), 'warnings': len(aligned['warnings'])}
    if stage=='enrich':
        from .enrichment import enrich
        source=job['stages']['prepare']['result']
        transcript=json.loads((local_transcript or load(source['transcript_uri'],'transcript.json')).read_text())
        return enrich(job,transcript,settings,cloud,lease,folder)
    if stage == 'plan':
        from .bundle import make_bundle
        source = job['stages']['align']['result']
        transcript = json.loads(load(source['transcript_uri'], 'aligned.json').read_text())
        enrichment=cloud.storage_json(job['stages']['enrich']['result']['enrichment_uri'],max_bytes=1048576)
        bundle=folder/'bundle';interactions=make_bundle(bundle,job,transcript,enrichment,cloud)
        plan_path=folder/'plan.json'
        run_command(['node','/app/render/original.js','plan',str(bundle),job['id'],str(plan_path)])
        plan=json.loads(plan_path.read_text())
        archive=folder/'bundle.tar.gz'
        with tarfile.open(archive,'w:gz') as out:out.add(bundle,arcname='bundle',filter=lambda member:None if member.name=='bundle/thumbnail.png' else member)
        from PIL import Image
        image=Image.open(bundle/'thumbnail.png');thumbnail=image.resize((1280,720)).convert('RGB')
        for quality in (90,80,60):
            thumbnail.save(folder/'thumbnail.jpg',quality=quality,optimize=True)
            if (folder/'thumbnail.jpg').stat().st_size<=2097152:break
        else:raise ValueError('Thumbnail too large')
        image.resize((960,540)).convert('RGB').save(folder/'thumbnail-preview.jpg',quality=65,optimize=True)
        run_command(['node','/app/render/podcast.js',str(bundle),job['id'],str(folder/'podcast-artwork.jpg')])
        return {'bundle_uri':output('bundle.tar.gz'),'plan_uri':output('plan.json',plan),'chunks':len(plan['chunks']),
                'manifest_sha256':digest_json(plan),'frames':plan['total_frames'],
                'thumbnail_uri':output('thumbnail.jpg'),'thumbnail_preview_uri':output('thumbnail-preview.jpg'),
                'podcast_artwork_uri':output('podcast-artwork.jpg'),'podcast_artwork_sha256':sha256(folder/'podcast-artwork.jpg'),
                'interactions_uri':output('interactions.json',interactions),'audio_uri':transcript['audio']['uri'],'audio_sha256':transcript['audio']['sha256']}
    if stage == 'render':
        source = job['stages']['plan']['result']
        if source.get('bundle_uri'):
            archive=load(source['bundle_uri'],'bundle.tar.gz')
            with tarfile.open(archive) as data:data.extractall(folder,filter='data')
            plan_path=load(source['plan_uri'],'plan.json');plan=json.loads(plan_path.read_text());movie=folder/'chunk.mp4'
            if digest_json(plan)!=source['manifest_sha256']:raise ValueError('Frozen render plan changed')
            run_command(['node','/app/render/original.js','chunk',str(folder/'bundle'),str(plan_path),str(task),str(movie)],on_line=lambda line:lease.update(.9*json.loads(line)['progress']))
            receipt=json.loads(Path(str(movie)+'.receipt.json').read_text())
            return {'video_uri':output('chunk.mp4'),'sha256':sha256(movie),'frames':receipt['frames'],
                    'manifest_sha256':source['manifest_sha256'],'chunk_index':task,'first_frame':receipt['first_frame'],
                    'end_frame':receipt['end_frame'],'stream':receipt['stream'],'preview_uri':output('chunk-preview.png') if task==0 else None}
        raise ValueError('An original presentation bundle is required')
    if stage == 'assemble':
        from .assembly import verify_final_video
        timing_start=time.monotonic();timings={}
        source = job['stages']['plan']['result']
        manifest = json.loads(load(source['manifest_uri'], 'manifest.json').read_text()) if source.get('manifest_uri') else {'audio':{'uri':source['audio_uri'],'sha256':source['audio_sha256']}}
        plan = json.loads(load(source['plan_uri'], 'plan.json').read_text())
        files, fingerprints = [], []
        for index, completed in enumerate(job['stages']['render']['tasks']):
            result = completed['result']
            if result['manifest_sha256'] != source['manifest_sha256']:
                raise ValueError('A chunk uses a different manifest')
            path = load(result['video_uri'], f'chunk-{index:04d}.mp4',result['sha256'])
            chunk=plan['chunks'][index]
            if result['frames'] != chunk['end_frame']-chunk['first_frame'] or ('chunk_index' in result and
                (result['chunk_index']!=index or result['first_frame']!=chunk['first_frame'] or result['end_frame']!=chunk['end_frame'])):
                raise ValueError('Chunk hash or frame range differs')
            probe = result.get('stream') or json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                'stream=codec_name,width,height,time_base,r_frame_rate,profile', '-of', 'json', str(path)]))['streams'][0]
            fingerprints.append(probe); files.append("file '" + path.name + "'")
            lease.update(.6 * (index + 1) / len(job['stages']['render']['tasks']))
        if any(p != fingerprints[0] for p in fingerprints):
            raise ValueError('Chunk stream parameters differ')
        timings['chunks']=round(time.monotonic()-timing_start,2);timing_start=time.monotonic()
        audio = load(manifest['audio']['uri'], 'audio.mp3',manifest['audio'].get('sha256'))
        (folder / 'chunks.txt').write_text('\n'.join(files) + '\n')
        target = folder / 'video.mp4'
        # One continuous Court recording: preserve its MP3 packets directly.
        timings['audio']=round(time.monotonic()-timing_start,2);timing_start=time.monotonic()
        run_command(['ffmpeg', '-nostdin', '-y', '-hide_banner', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
                        '-i', str(folder / 'chunks.txt'), '-i', str(audio), '-map', '0:v:0', '-map', '1:a:0',
                        '-c:v', 'copy', '-c:a', 'copy',
                        '-movflags', '+faststart', str(target)])
        timings['mux']=round(time.monotonic()-timing_start,2);timing_start=time.monotonic()
        verified=verify_final_video(target,plan['total_frames'],fingerprints[0])
        timings['check']=round(time.monotonic()-timing_start,2);timing_start=time.monotonic()
        fingerprint=sha256(target);uri=output('video.mp4');timings['save']=round(time.monotonic()-timing_start,2)
        return {'video_uri':uri,'sha256':fingerprint,'manifest_uri':source.get('manifest_uri'),
                **verified,'timings_seconds':timings}
    if stage == 'upload':
        from .youtube import upload_video
        if job['stages']['upload'].get('checkpoint',{}).get('video_id'):
            return upload_video(None,job,settings,cloud,lease)
        source = job['stages']['assemble']['result']
        video = local_video if local_video is not None else load(source['video_uri'], 'video.mp4',source['sha256'])
        return upload_video(video, job, settings, cloud, lease)
    raise ValueError('Unknown stage')


def main():
    if not os.environ.get('CLOUD_RUN_JOB'):
        raise SystemExit('Cloud media workers run on Cloud Run; local media transfers are disabled.')
    if os.environ.get('SCOTUS_CARD_IMPORT_ID'):
        from .card_import_worker import main as import_cards
        import_cards();return
    settings = runtime_settings('/secrets/worker/config.json')
    stage = os.environ['SCOTUS_STAGE']; task = int(os.environ.get('CLOUD_RUN_TASK_INDEX', 0))
    if stage=='render' and os.environ.get('SCOTUS_RENDER_TASKS'):task=json.loads(os.environ['SCOTUS_RENDER_TASKS'])[task]
    if stage=='enrich':os.environ['SCOTUS_PRIVATE_CODEX_WORKER']='1'
    dashboard = Dashboard(settings['dashboard_url'], settings['worker_key'], stage)
    cloud = Google(settings['project'])
    if os.environ.get('SCOTUS_UPLOAD_AUDIT'):
        from .upload_audit import main as audit
        audit();return
    if os.environ.get('SCOTUS_VIDEO_ACTION'):
        from .youtube import video_action
        action_id=os.environ['SCOTUS_VIDEO_ACTION']
        claim=dashboard.call('video_action_claim',job=os.environ['SCOTUS_JOB_ID'],action_id=action_id,dispatch_token=os.environ['SCOTUS_ACTION_TOKEN'])
        if not claim:return
        success=False
        try:
            video_action(claim['job'],claim['action'],settings,cloud,dashboard);success=True
        finally:
            dashboard.call('video_action_finish',job=os.environ['SCOTUS_JOB_ID'],action_id=action_id,lease=claim['action']['lease'],success=success)
        return
    lease = Lease(dashboard, os.environ['SCOTUS_JOB_ID'], stage, os.environ['SCOTUS_DISPATCH_TOKEN'], task)
    claimed = lease.claim()
    if not claimed or claimed.get('complete') or claimed.get('cancelled'):return
    run_sequence(stage,claimed,settings,cloud,lease,task)


def run_sequence(stage,claimed,settings,cloud,lease,task=0):
    local_video=None;local_transcript=None;thread=None
    card_deadline=time.monotonic()+2400
    try:
        with tempfile.TemporaryDirectory(prefix='scotus-') as directory:
            folder=Path(directory)
            while True:
                lease.card_deadline=card_deadline
                lease.data['lease']=claimed['lease'];lease.last_heartbeat=time.monotonic()
                thread=threading.Thread(target=lease.run,daemon=True);thread.start()
                if stage=='enrich':os.environ['SCOTUS_PRIVATE_CODEX_WORKER']='1'
                result=stage_run(stage,claimed['job'],settings,cloud,lease,folder,task,local_video=local_video,local_transcript=local_transcript)
                if result is None:return
                lease.check();lease.stopped.set();thread.join(timeout=5)
                extra={}
                if stage=='assemble' and os.environ.get('SCOTUS_CONTINUE_UPLOAD')=='1' and settings.get('upload_worker_key') and not os.environ.get('SCOTUS_WORKFLOW_RELEASE_URI'):
                    extra={'continue_upload':True,'handoff_id':uuid.uuid4().hex,'release_id':(__import__('scotus_cloud.releases',fromlist=['image_release']).image_release('/app') or {}).get('id',settings.get('workflow_baseline_sha256',''))}
                if stage=='prepare' and os.environ.get('SCOTUS_CONTINUE_ENRICH')=='1' and settings.get('enrich_worker_key') and not os.environ.get('SCOTUS_WORKFLOW_RELEASE_URI'):
                    extra={'continue_enrich':True,'handoff_id':uuid.uuid4().hex,'release_id':(__import__('scotus_cloud.releases',fromlist=['image_release']).image_release('/app') or {}).get('id',settings.get('workflow_baseline_sha256',''))}
                finished=lease.call('finish',result=result,**extra)
                if not isinstance(finished,dict) or not finished.get('next'):return
                following=finished['next'];stage=following.get('stage','upload')
                local_video=folder/'video.mp4' if stage=='upload' else None
                local_transcript=folder/'transcript.json' if stage=='enrich' else None
                dashboard=Dashboard(settings['dashboard_url'],settings[stage+'_worker_key'],stage)
                lease=Lease(dashboard,following['job']['id'],stage,following['dispatch_token'],0)
                claimed=lease.claim()
                if not claimed or claimed.get('complete') or claimed.get('cancelled'):return
    except Exception as error:
        from .research_errors import ResearchUnavailable
        if isinstance(error,ResearchUnavailable) and stage=='enrich':
            lease.call('research_defer',kind=error.kind,message=str(error),retry_after=error.retry_after,phase=error.phase)
            return
        category = 'alignment_review' if isinstance(error, AlignmentReview) else 'worker_failed'
        if isinstance(error, ValueError) and not isinstance(error, AlignmentReview): category = 'invalid_inputs'
        if getattr(error, 'category', None):category=error.category
        from .remote import DashboardTransportError
        chain=error
        while chain:
            if isinstance(chain,(DashboardTransportError,TimeoutError,URLError)):category='transport';break
            chain=chain.__cause__
        try:
            diagnostic=failure_report(error,claimed['job'],stage,task,category,settings,lease.data,
                                      claimed['job']['stages'].get('upload',{}).get('checkpoint',{}))
            lease.call('fail',error=category,diagnostic=diagnostic)
        except Exception:pass
        raise SystemExit(category) from None
    finally:
        lease.stopped.set()
        if thread:thread.join(timeout=5)


if __name__ == '__main__':
    main()
