import unittest
from scotus_cloud.podcast import recording_export

class PodcastExportTests(unittest.TestCase):
    def test_public_export_has_exact_audio_identity_and_no_private_fields(self):
        job={'id':'2026-10-05-25-170-argument-1','docket':'25-170','case_name':'Case','argument_date':'2026-10-05','audio_url':'https://www.supremecourt.gov/audio.mp3','pdf_url':'https://www.supremecourt.gov/transcript.pdf','approved_photos':{'secret':'private'}}
        transcript={'audio':{'duration_seconds':10,'sha256':'a'*64,'uri':'gs://private/audio'},
            'speakers':{'justice':{'name':'Justice Doe','last_name':'Doe','kind':'justice','private_note':'never publish'},'advocate':{'name':'Jane Smith','last_name':'Smith','kind':'advocate'}},
            'paragraphs':[{'start':.3,'speaker':'justice','turn':0,'section':0,'text':'Opening'}, {'start':2,'speaker':'advocate','turn':1,'section':0,'text':'Answer'}]}
        exported=recording_export(job,transcript)
        self.assertEqual(exported['term'],'2026');self.assertEqual(exported['audio']['sha256'],'a'*64)
        self.assertEqual(exported['sections'][0]['turns'][1]['start'],2)
        self.assertNotIn('uri',exported['audio']);self.assertNotIn('private_note',exported['sections'][0]['turns'][0]['speaker'])
        transcript['paragraphs'][1]['speaker']='justice'
        with self.assertRaisesRegex(ValueError,'no advocate'):recording_export(job,transcript)
