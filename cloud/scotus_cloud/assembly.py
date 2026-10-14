"""Cheap MP4 header checks for our frame plan and mux arguments."""
from fractions import Fraction
import json,subprocess


def verify_final_video(path,expected_frames,expected_stream):
    probe=json.loads(subprocess.check_output([
        'ffprobe','-v','error','-show_entries',
        'stream=codec_type,codec_name,nb_frames,width,height,r_frame_rate,time_base,profile,duration',
        '-of','json',str(path)],timeout=120))['streams']
    videos=[stream for stream in probe if stream['codec_type']=='video']
    if len(videos)!=1 or not any(stream['codec_type']=='audio' for stream in probe):
        raise ValueError('Final video or audio stream differs')
    video=videos[0]
    # Check our selected inputs/arguments, rather than rechecking FFmpeg's codec.
    if video.get('codec_name')!='h264' or int(video.get('nb_frames',-1))!=expected_frames:
        raise ValueError('Final MP4 frame metadata differs')
    if any(video.get(key)!=value for key,value in expected_stream.items()):
        raise ValueError('Final video stream parameters differ')
    fps=float(Fraction(video['r_frame_rate']))
    if fps<=0 or abs(float(video['duration'])-expected_frames/fps)>1/fps:
        raise ValueError('Final video duration differs')
    return {'frames':expected_frames,'verification':'mp4_header'}
