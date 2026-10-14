import copy,sys,unittest
from datetime import datetime,timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.presentation_data import case_metadata,presentation_audio
from scotus_cloud.formatters import format_interactions
from scotus_cloud.presentation_data import recording_timeline
from scotus_cloud.repair_policy import baseline_files,validate_changes


class PresentationDataTests(unittest.TestCase):
    def test_granted_only_timeline_reaches_original_formatter(self):
        job={'id':'fixture','case_name':'Johnson v. United States Congress','docket':'25-735','argument_date':'2026-10-05'}
        speaker={'identifier':'john_g_roberts_jr','name':'John G. Roberts, Jr.','last_name':'Roberts','kind':'justice','role':'Chief Justice'}
        advocate={'identifier':'advocate','name':'Jane Doe','last_name':'Doe','kind':'advocate','role':'for the petitioner'}
        transcript={'speakers':{'chief':speaker,'advocate':advocate},'audio':{'duration_seconds':5},'paragraphs':[
            {'speaker':'chief','section':0,'turn':0,'start':0,'text':'We will hear argument.'},
            {'speaker':'advocate','section':0,'turn':1,'start':1,'text':'Mr. Chief Justice, and may it please the Court.'}]}
        source={'timeline':[{'event':'Granted','dates':[1769472000],'href':'existing grant'}],'heard_by':[None]}
        original=copy.deepcopy(source)
        metadata=case_metadata(job,transcript,{'case_metadata':source})
        expected=int(datetime(2026,10,5,tzinfo=timezone.utc).timestamp())
        self.assertEqual(metadata['timeline'],original['timeline']+[{'event':'Argued','dates':[expected]}])
        self.assertEqual(source,original)
        result=format_interactions(metadata,presentation_audio(transcript),5)
        self.assertEqual(result['dates'],'Argued on Oct 5, 2026.')
        self.assertIn('Oct 5, 2026',result['youtube_description'])

    def test_usable_events_preserved_without_duplicate_argument(self):
        events=[{'event':'Granted','dates':[1700000000]},{'event':'Argued','dates':[1800000000],'note':'retained'},
                {'event':'Decided','dates':[1900000000]}]
        before=copy.deepcopy(events)
        self.assertEqual(recording_timeline(events,1800000001),before)
        self.assertEqual(events,before)

    def test_missing_or_invalid_argument_dates_are_repaired(self):
        for events in (None,[],{},[None],
                       [{'event':'Granted','dates':[1700000000]}]):
            with self.subTest(events=events):
                result=recording_timeline(events,1791158400)
                self.assertEqual([event for event in result if event['event']=='Argued'],[{'event':'Argued','dates':[1791158400]}])
        for dates in (None,[],['2026-10-05'],[True],[float('nan')],[float('inf')],[10**20]):
            event={'event':'Argued','dates':dates,'href':'existing event'}
            with self.subTest(dates=dates):
                self.assertEqual(recording_timeline([event],1791158400),[{**event,'dates':[1791158400]}])

    def test_recovery_can_edit_data_adapter_but_not_public_formatters(self):
        self.assertEqual(case_metadata.__module__,'scotus_cloud.presentation_data')
        self.assertEqual(presentation_audio.__module__,'scotus_cloud.presentation_data')
        root=Path(__file__).resolve().parents[1];baseline=baseline_files(root)
        allowed='scotus_cloud/presentation_data.py'
        self.assertEqual(validate_changes(baseline,{allowed:baseline[allowed]+'\n'})['stages'],['plan'])
        for name in ('scotus_cloud/formatters.py','presentation/renderer/index.html','presentation/renderer/script.js'):
            with self.subTest(path=name),self.assertRaises(ValueError):
                validate_changes(baseline,{name:baseline[name]+'\n'})


if __name__=='__main__':unittest.main()
