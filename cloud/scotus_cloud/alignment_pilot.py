"""Bounded CPU scaling comparison using an existing cloud recording excerpt."""
import json,os,subprocess,tempfile,time
from pathlib import Path
from .alignment import align_recording
from .google import Google


def main():
    if not os.environ.get('CLOUD_RUN_JOB'):raise RuntimeError('Cloud-only pilot')
    cloud=Google(os.environ['SCOTUS_PROJECT']);threads=int(os.environ['SCOTUS_PILOT_THREADS'])
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);cloud.storage_download(os.environ['SCOTUS_PILOT_TRANSCRIPT'],root/'transcript.json')
        transcript=json.loads((root/'transcript.json').read_text());cloud.storage_download(transcript['audio']['uri'],root/'original.mp3')
        paragraphs=transcript['paragraphs'];stop=next(i for i,p in enumerate(paragraphs) if p['start']>=180)
        end=paragraphs[stop]['start'];kept=paragraphs[:stop]
        transcript['text']=transcript['text'][:kept[-1]['end_offset']];transcript['paragraphs']=kept
        subprocess.run(['ffmpeg','-nostdin','-y','-hide_banner','-loglevel','error','-i',str(root/'original.mp3'),
                        '-t',str(end),'-ac','1','-ar','16000',str(root/'excerpt.wav')],check=True,timeout=30)
        phases={};began=time.monotonic()
        def progress(value):
            if value in (.02,.65):phases[str(value)]=time.monotonic()-began
        result=align_recording(root/'excerpt.wav',transcript,'/opt/english-model',progress,cpu_threads=threads)
        total=time.monotonic()-began
        report={'cpu_threads':threads,'excerpt_seconds':end,'alignment_seconds':total,
                'load_seconds':phases['0.02'],'emissions_seconds':phases['0.65']-phases['0.02'],
                'fine_alignment_seconds':total-phases['0.65'],'paragraph_starts':[p['start'] for p in result['paragraphs']],
                'warnings':len(result['warnings']),'audio_download_excluded':True,'cpu_only':True}
        (root/'report.json').write_text(json.dumps(report));cloud.storage_upload(root/'report.json',os.environ['SCOTUS_PILOT_REPORT'],'application/json')
        print(json.dumps(report),flush=True)


if __name__=='__main__':main()
