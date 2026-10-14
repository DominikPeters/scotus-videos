import copy,json,tempfile,unittest
from pathlib import Path
import sys
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.discovery import recordings
from scotus_cloud.presentation_data import case_metadata,presentation_audio
from scotus_cloud.formatters import format_interactions,timestamp_comment
from scotus_cloud.presentation_sources import verified_source
from scotus_cloud.youtube import postprocess,UploadError
from scotus_cloud.repair_policy import baseline_files,validate_changes
from scotus_cloud.repair_bootstrap import apply_release
from scotus_cloud.recovery_worker import seed_workspace
from scotus_cloud.model import digest_json


class IntegrationTests(unittest.TestCase):
    def test_official_discovery_pairs_sources_and_preserves_dates(self):
        listing='<table><tr><td><a href="../audio/2026/25-735">25-735</a> Johnson v. United States Congress</td><td>10/05/26</td></tr><tr><td><a href="../audio/2026/25-170">25-170</a> Other v. Case</td><td>10/05/26</td></tr></table>'
        def fetch(url):
            if 'argument_audio' in url:return listing
            return '<a href="/media/audio/mp3files/25-735.mp3">Download</a>'+('<a href="/oral_arguments/argument_transcripts/2026/25-735_test.pdf">Transcript</a>' if url.endswith('25-735') else '')
        records=recordings(2026,fetch)
        self.assertEqual(len(records),1);self.assertEqual(records[0]['argument_date'],'2026-10-05')
        self.assertEqual(records[0]['case_name'],'Johnson v. United States Congress')

    def fixture(self):
        people={'john_g_roberts_jr':{'identifier':'john_g_roberts_jr','name':'John G. Roberts, Jr.','last_name':'Roberts','kind':'justice','role':'Chief Justice'},
                'a':{'identifier':'a','name':'Jane A. Doe','last_name':'Doe','kind':'advocate','role':'for the petitioner'}}
        transcript={'speakers':people,'audio':{'duration_seconds':12},'paragraphs':[
            {'speaker':'john_g_roberts_jr','section':0,'turn':0,'start':0,'text':'We will hear argument.'},
            {'speaker':'a','section':0,'turn':1,'start':1,'text':'Mr. Chief Justice, and may it please the Court.'}]}
        job={'id':'fixture','case_name':'Example v. Case','argument_date':'2026-10-05','docket':'25-735'}
        enrichment={'description':{'fields':{'facts_of_the_case':'<p>A short statement of facts.</p>','question':'<p>Is this permitted?</p>'}}}
        metadata=case_metadata(job,transcript,enrichment)
        return metadata,presentation_audio(transcript)

    def test_original_formatter_and_comment_credit_only_used_content(self):
        metadata,audio=self.fixture()
        result=format_interactions(metadata,audio,12,oyez_content_used=False)
        self.assertNotIn('from oyez.org',result['youtube_description'])
        self.assertNotIn('transcripts on oyez.org',result['youtube_description'])
        self.assertIn('Jane A. Doe',timestamp_comment(result))
        metadata['href']='https://www.oyez.org/cases/2026/25-735'
        used=format_interactions(metadata,audio,12,oyez_content_used=True)
        self.assertIn('Case information based on oyez.org',used['youtube_description'])
        self.assertEqual(result['term'],'2026')

    def test_postprocess_resume_reconciles_existing_playlist_and_comment(self):
        interactions={'term':'2026','youtube_description':'existing description','youtube_title':'existing title'}
        saved={'video_id':'video','thumbnail_done':True}
        job={'stages':{'plan':{'result':{'interactions_uri':'gs://private/interactions'}}}}
        cloud=Mock();cloud.storage_json.return_value=interactions;lease=Mock();session=Mock()
        def request(session,method,resource,**kwargs):
            if resource=='channels':return {'items':[{'id':'channel'}]}
            if resource=='videos':return {'items':[{'id':'video','snippet':{'channelId':'channel'}}]}
            self.fail('Duplicate external insert: '+resource)
        def page(session,resource,params):
            if resource=='playlistItems':return iter([{'id':'membership'}])
            return iter([{'id':'comment','snippet':{'topLevelComment':{'snippet':{'authorChannelId':{'value':'channel'},'textOriginal':'same comment'}}}}])
        with patch('scotus_cloud.youtube.api',side_effect=request),patch('scotus_cloud.youtube.pages',side_effect=page),patch('scotus_cloud.formatters.timestamp_comment',return_value='same comment'):
            result=postprocess(session,'video',job,{'youtube_channel_id':'channel','playlists':{'2026':'playlist'}},cloud,lease,saved)
        self.assertTrue(result['postprocessing_complete']);cloud.storage_bytes.assert_not_called()
        self.assertEqual(saved['comment_id'],'comment')

    def test_release_cannot_apply_to_a_different_source_baseline(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'scotus_cloud/prepare.py';p.parent.mkdir();p.write_text('value=1\n')
            baseline=baseline_files(root);release=validate_changes(baseline,{'scotus_cloud/prepare.py':'value=2\n'})
            p.write_text('value=3\n')
            with self.assertRaises(ValueError):apply_release(release,root,'prepare')
            self.assertEqual(p.read_text(),'value=3\n')

    def test_next_repair_starts_with_previously_applied_fix(self):
        baseline={'scotus_cloud/alignment.py':'value=1\n'}
        release=validate_changes(baseline,{'scotus_cloud/alignment.py':'value=2\n'})
        cloud=Mock();cloud.storage_json.return_value=release
        job={'stages':{'align':{'workflow_release':{'uri':'gs://private/fix.json','sha256':digest_json(release)}}}}
        with tempfile.TemporaryDirectory() as folder:
            seed_workspace(Path(folder),baseline,job,'align',cloud)
            self.assertEqual((Path(folder)/'scotus_cloud/alignment.py').read_text(),'value=2\n')

if __name__=='__main__':unittest.main()
