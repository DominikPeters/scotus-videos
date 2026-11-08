import io,json,math,tempfile,wave,array,unittest
from pathlib import Path
from unittest.mock import Mock
from PIL import Image
from scotus_cloud.recovery_evidence import media_locator
from scotus_cloud.recovery_media import inspect_media

class RecoveryMediaTests(unittest.TestCase):
 def test_only_this_recordings_known_media_and_bounded_intervals_are_selected(self):
  cfg={'recovery':{'bucket':'owned'}};job={'id':'case','stages':{'prepare':{'result':{'audio_uri':'gs://owned/scratch/case/audio.mp3'}}}}
  self.assertEqual(media_locator({'kind':'audio','start':20,'duration':10},{'job':job},cfg)['start'],20)
  for args in ({'kind':'audio','start':-1},{'kind':'audio','duration':61},{'kind':'audio','duration':math.inf},{'kind':'card','card_id':'unknown'}):
   with self.assertRaises(ValueError):media_locator(args,{'job':job},cfg)
  job['stages']['prepare']['result']['audio_uri']='gs://owned/other-case/audio.mp3'
  with self.assertRaises(ValueError):media_locator({'kind':'audio'},{'job':job},cfg)
 def test_image_is_exported_and_returned_as_a_native_image(self):
  data=io.BytesIO();Image.new('RGB',(1920,1080),'beige').save(data,'PNG');cloud=Mock();cloud.request.return_value={'size':len(data.getvalue())}
  cloud.storage_download.side_effect=lambda uri,p:Path(p).write_bytes(data.getvalue())
  with tempfile.TemporaryDirectory() as folder:
   result=inspect_media({'kind':'frame','uri':'gs://owned/scratch/case/preview.png'},cloud,folder)
   self.assertEqual(result['contentItems'][1]['type'],'inputImage');self.assertTrue((Path(folder)/'input/media/preview.jpg').is_file())
 def test_bounded_audio_excerpt_has_exact_duration_and_signal_diagnostics(self):
  raw=io.BytesIO()
  with wave.open(raw,'wb') as audio:
   audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(array.array('h',[1200,-1200]*16000).tobytes())
  cloud=Mock();cloud.request.return_value={'size':len(raw.getvalue())};cloud.storage_download.side_effect=lambda uri,p:Path(p).write_bytes(raw.getvalue())
  with tempfile.TemporaryDirectory() as folder:
   result=inspect_media({'kind':'audio','uri':'gs://owned/scratch/case/audio.mp3','start':.5,'duration':1},cloud,folder)
   info=json.loads(result['contentItems'][0]['text']);self.assertEqual(info['duration_seconds'],1);self.assertEqual(info['rms'],1200)
   self.assertTrue((Path(folder)/info['file']).is_file());self.assertIn('waveform',info['note'])
