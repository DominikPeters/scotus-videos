import unittest
from unittest.mock import Mock,patch
from urllib.error import HTTPError
from scotus_cloud.discovery import watched_recording,poll_watches

WATCH={'docket':'25-5343','case_name':'Beaird v. United States','argument_date':'2026-10-13',
       'source_page':'https://www.supremecourt.gov/oral_arguments/audio/2026/25-5343'}
AUDIO='<a href="/media/audio/mp3files/25-5343.mp3">Audio</a>'
PDF='<a href="/oral_arguments/argument_transcripts/2026/25-5343_test.pdf">Transcript</a>'

class SourceWatchTests(unittest.TestCase):
    def test_requires_both_case_sources(self):
        self.assertIsNone(watched_recording(WATCH,lambda _:AUDIO))
        self.assertIsNone(watched_recording(WATCH,lambda _:PDF))
        self.assertIsNone(watched_recording(WATCH,lambda _:AUDIO+PDF.replace('25-5343','25-170')))
        record=watched_recording(WATCH,lambda _:AUDIO+PDF)
        self.assertEqual(record['argument_date'],'2026-10-13')
        self.assertEqual(record['audio_url'],'https://www.supremecourt.gov/media/audio/mp3files/25-5343.mp3')

    def test_unpublished_detail_page_is_not_a_failure(self):
        def fetch(_):raise HTTPError(WATCH['source_page'],404,'Missing',{},None)
        self.assertIsNone(watched_recording(WATCH,fetch))

    def test_closed_window_or_already_found_performs_no_fetch(self):
        dashboard=Mock();dashboard.call.return_value=False
        with patch('scotus_cloud.discovery.watched_recording') as fetch:
            self.assertEqual(poll_watches(dashboard,{'source_watch_ids':['one']}),[])
            fetch.assert_not_called()

    def test_found_recording_is_saved_for_automatic_start(self):
        dashboard=Mock();dashboard.call.side_effect=[WATCH,{'found':True,'job':'beaird'}]
        record=watched_recording(WATCH,lambda _:AUDIO+PDF)
        with patch('scotus_cloud.discovery.watched_recording',return_value=record):
            self.assertEqual(poll_watches(dashboard,{'source_watch_ids':['one']}),[{'found':True,'job':'beaird'}])
        self.assertEqual(dashboard.call.call_args.kwargs['recording'],record)
