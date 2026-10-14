import json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.assembly import verify_final_video


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg is required')
class AssemblyTests(unittest.TestCase):
    def test_stream_copy_header_check_matches_decoded_count_and_rejects_bad_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            def run(args):subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error',*args],check=True,timeout=30)
            for index,color in enumerate(('white','black')):
                run(['-f','lavfi','-i',f'color={color}:s=64x36:r=20:d=1','-an','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(root/f'{index}.mp4')])
            (root/'chunks.txt').write_text("file '0.mp4'\nfile '1.mp4'\n")
            run(['-f','concat','-safe','0','-i',str(root/'chunks.txt'),'-f','lavfi','-i','sine=duration=2','-c:v','copy','-c:a','aac','-movflags','+faststart',str(root/'final.mp4')])
            stream={'codec_name':'h264','width':64,'height':36,'r_frame_rate':'20/1'}
            self.assertEqual(verify_final_video(root/'final.mp4',40,stream)['frames'],40)
            decoded=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-select_streams','v:0','-show_entries','stream=nb_read_frames','-of','json',str(root/'final.mp4')]))
            self.assertEqual(int(decoded['streams'][0]['nb_read_frames']),40)
            with self.assertRaises(ValueError):verify_final_video(root/'final.mp4',39,stream)
            with self.assertRaises(ValueError):verify_final_video(root/'final.mp4',40,{**stream,'width':128})
            with self.assertRaises(ValueError):verify_final_video(root/'0.mp4',20,stream)


if __name__=='__main__':unittest.main()
