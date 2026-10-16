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

    def test_export_runs_before_plan_and_without_artwork(self):
        from scotus_cloud.podcast import publish_alignments
        from unittest.mock import Mock,patch
        job={'id':'case','status':'needs_review','docket':'25-170','argument_date':'2026-10-05','case_name':'Case','audio_url':'https://www.supremecourt.gov/a.mp3','pdf_url':'https://www.supremecourt.gov/t.pdf',
             'stages':{'align':{'status':'complete','result':{'transcript_uri':'gs://aligned'}},'plan':{'status':'pending'}}}
        dashboard,google=Mock(),Mock()
        google.storage_json.return_value={'audio':{'duration_seconds':10,'sha256':'a'*64},'speakers':{'a':{'name':'Jane Doe','kind':'advocate'}},'paragraphs':[{'start':0,'speaker':'a','section':0,'turn':0,'text':'Hello'}]}
        dashboard.call.return_value={'revision':'b'*64}
        with patch('scotus_cloud.podcast.dispatch_podcast') as dispatch:publish_alignments(dashboard,google,{'podcast_enabled':True},{'case':job})
        self.assertEqual(dashboard.call.call_args_list[0].args,('transcript_export',))
        google.storage_download.assert_not_called();dispatch.assert_called_once()

    def test_plan_export_includes_artwork_and_separate_alignment_revision(self):
        from scotus_cloud.podcast import publish_alignments
        from unittest.mock import Mock,patch
        import hashlib,json
        job={'id':'case','status':'running','docket':'25-170','argument_date':'2026-10-05','case_name':'Case','audio_url':'https://www.supremecourt.gov/a.mp3','pdf_url':'https://www.supremecourt.gov/t.pdf',
             'stages':{'align':{'status':'complete','result':{'transcript_uri':'gs://aligned'}},'plan':{'status':'complete','result':{'podcast_artwork_uri':'gs://art','podcast_artwork_sha256':hashlib.sha256(b'image').hexdigest()}}}}
        transcript={'audio':{'duration_seconds':10,'sha256':'a'*64},'speakers':{'a':{'name':'Jane Doe','kind':'advocate'}},'paragraphs':[{'start':0,'speaker':'a','section':0,'turn':0,'text':'Hello'}]}
        dashboard,google=Mock(),Mock();google.storage_json.return_value=transcript
        google.storage_download.side_effect=lambda uri,p,**kw:p.write_bytes(b'image')
        dashboard.call.return_value={'revision':'b'*64}
        with patch('scotus_cloud.podcast.dispatch_podcast') as dispatch:publish_alignments(dashboard,google,{'podcast_enabled':True},{'case':job})
        exported=dashboard.call.call_args_list[0].kwargs
        self.assertEqual(exported['source_uri'],'gs://aligned')
        artwork_call=dashboard.call.call_args_list[1]
        self.assertEqual(artwork_call.args,('podcast_artwork',));self.assertEqual(artwork_call.kwargs['artwork_base64'],'aW1hZ2U=')
        recording=json.loads(exported['payload']);self.assertNotIn('artwork',recording)
        self.assertNotEqual(recording['alignment_revision'],exported['revision']);dispatch.assert_called_once()
