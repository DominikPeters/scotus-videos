"""PHP transport boundaries for the statistics worker."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
# The core is copied into the statistics build context from scotusstats.
try:
    import stats_core
except ModuleNotFoundError:
    stats_core = Mock()
    sys.modules['stats_core'] = stats_core
from scotus_cloud.statistics_worker import CODING_REVISION,main,owner_answers,opinion_material,schema,retry_fixed_error,legacy_technical_failure,technical_failure,research_work

class StatisticsWorkerTests(unittest.TestCase):
    def test_transport_failures_are_not_owner_questions_and_have_bounded_retries(self):
        old={'status':'needs_review','notes':'RuntimeError: Object upload failed: HTTP 408','coding_revision':CODING_REVISION}
        self.assertTrue(legacy_technical_failure(old))
        self.assertFalse(legacy_technical_failure({'status':'needs_review','notes':'Which opinion controls Part II?'}))
        saved={}
        for attempt in (1,2,3):
            saved=technical_failure(RuntimeError('Object upload failed: HTTP 408'),saved,1000)
            self.assertEqual(saved['technical_attempts'],attempt)
            self.assertEqual(saved['status'],'failed' if attempt==3 else 'retry_pending')
        self.assertFalse(legacy_technical_failure(saved))

    def test_retry_schedule_deduplicates_backlog_and_preserves_real_questions(self):
        research={'a':{'status':'retry_pending','retry_after':1300,'notes':'Timeout'},
                  'b':{'status':'failed','notes':'Invalid output'},
                  'c':{'status':'needs_review','notes':'Which opinion controls?'}}
        errors,pending,delay=research_work(research,[],1000)
        self.assertEqual(set(errors),{'a','b'});self.assertEqual(pending,1);self.assertEqual(delay,300)
        self.assertEqual(research_work(research,['a','d'],1000)[1:],(2,0))

    @unittest.skipUnless(isinstance(getattr(stats_core,'__file__',None),str),'Shared core required')
    def test_old_upload_error_is_revisited_without_recoding_intact_pending_case(self):
        import gzip,json,tempfile
        from datetime import datetime,timezone
        from contextlib import ExitStack
        today=datetime.now(timezone.utc).date().isoformat();key='2026/25-498'
        record={'objectID':key,'term':'2026','docket_number':'25-498','name':'Anderson','issue':{'lvl0':'Economic Activity'}}
        original={'records':{key:record},'research':{key:{'status':'needs_review','checked_date':today,'notes':'RuntimeError: Object upload failed: HTTP 408','coding_revision':CODING_REVISION}},'opinion_check_date':today}
        cloud=Mock();cloud.secret.return_value=json.dumps({'dashboard_url':'https://example.test','dashboard_key':'key','seed_uri':'gs://bucket/seed','bucket':'bucket'})
        cloud.storage_download.side_effect=lambda uri,path:path.write_bytes(gzip.compress(json.dumps(original).encode()))
        dashboard=Mock();dashboard.call.side_effect=lambda op,**kw:{'token':'token'} if op=='stats_start' else True
        captured={};reader=Mock(return_value={'events':[]});model=Mock()
        cloud.storage_upload.side_effect=lambda path,uri:captured.update(state=json.loads(gzip.decompress(path.read_bytes())))
        response=Mock();response.json.return_value={'recordings':{}}
        with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
            root=Path(folder)
            for name in ('issues.json','legal-provisions.json'):(root/name).write_text('{}')
            for name,value in [('Google',Mock(return_value=cloud)),('Dashboard',Mock(return_value=dashboard)),('migrate',Mock()),('ROOT',root),('run_codex',model),('opinion_material',reader)]:
                stack.enter_context(patch('scotus_cloud.statistics_worker.'+name,value))
            stack.enter_context(patch('scotus_cloud.statistics_worker.requests.get',return_value=response))
            stack.enter_context(patch.dict('os.environ',{'GOOGLE_CLOUD_PROJECT':'test','SCOTUS_STATS_TOKEN':'token'}))
            main()
            self.assertEqual(captured['state']['research'][key]['status'],'awaiting_opinion')
            success=dashboard.call.call_args.kwargs
            self.assertEqual(success['questions'],{});self.assertEqual(success['technical_errors'],{});self.assertEqual(success['pending'],0)
            reader.side_effect=RuntimeError('Object upload failed: HTTP 408')
            main()
        model.assert_not_called()
        self.assertEqual(captured['state']['research'][key]['status'],'retry_pending')
        self.assertEqual(captured['state']['records'][key],record)
        final=dashboard.call.call_args.kwargs
        self.assertEqual(final['questions'],{});self.assertEqual(final['technical_errors'][key]['status'],'retry_pending');self.assertEqual(final['pending'],1);self.assertGreater(final['retry_after_seconds'],295)

    @unittest.skipUnless(isinstance(getattr(stats_core,'__file__',None),str),'Shared core is supplied by the dedicated statistics build')
    def test_model_checker_runs_real_publication_checks(self):
        import json,shutil,subprocess,tempfile
        import scotus_cloud.statistics_check as checker
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);inputs=root/'input';inputs.mkdir()
            shutil.copy2(checker.__file__,inputs/'check_statistics.py');shutil.copy2(stats_core.__file__,inputs/'stats_core.py')
            (root/'schema.json').write_text(json.dumps(schema({},{})))
            for name,value in [('issues.json',{}),('legal-provisions.json',{}),('case.json',{'case':{'argument_date':'2026-10-05'},'docket_url':'https://www.supremecourt.gov/RSS/Cases/JSON/25-1.json'})]:
                (inputs/name).write_text(json.dumps(value))
            draft={'issue_code':None,'legal_provision_code':None,'decision':None,'opinion_details':[],'evidence':[],'disposition':None,'decided_date':None,'lower_court':None,'needs_review':False,'notes':''}
            def run(value):return subprocess.run([sys.executable,str(inputs/'check_statistics.py')],input=json.dumps(value),capture_output=True,text=True)
            self.assertEqual(run(draft).returncode,0)
            bad=run(draft|{'decided_date':'2026-01-01'})
            self.assertNotEqual(bad.returncode,0);self.assertIn('predates',bad.stderr)
            names=['Roberts','Thomas','Alito','Sotomayor','Kagan','Gorsuch','Kavanaugh','Barrett','Jackson']
            decision={'type':'majority','voteStatus':'complete','judgmentParts':[],'majorityVoters':names,'minorityVoters':[],'abstainers':[],'majorityJoiners':names,'dissentingWriters':[],'majorityWriter':'Roberts','majoritySize':8,'minoritySize':0}
            bad=run(draft|{'decision':decision,'evidence':['Official joining passage']})
            self.assertNotEqual(bad.returncode,0);self.assertIn('Vote count differs',bad.stderr)

    @unittest.skipUnless(isinstance(getattr(stats_core,'__file__',None),str),'Shared core required')
    def test_schema_requires_canonical_justice_names(self):
        from jsonschema import validate,ValidationError
        with patch('scotus_cloud.statistics_worker.JUSTICES',{'Roberts','Kagan'}):
            output=schema({},{})
        names=output['properties']['decision']['anyOf'][1]['properties']['majorityVoters']
        validate(['Kagan'],names)
        with self.assertRaises(ValidationError):validate(['Elena Kagan'],names)
        author=output['properties']['opinion_details']['items']['properties']['author']
        validate(None,author)
        with self.assertRaises(ValidationError):validate('Chief Justice Roberts',author)

    @unittest.skipUnless(isinstance(getattr(stats_core,'__file__',None),str),'Shared core required')
    def test_reviewed_batch_migration_is_idempotent_and_preserves_originals(self):
        import copy
        from scotus_cloud.statistics_migrations import migrate,REVISION
        names=['Roberts','Thomas','Alito','Sotomayor','Kagan','Gorsuch','Kavanaugh','Barrett','Jackson']
        decision=dict(type='unanimous',source='codex',majorityWriter='Kagan',majoritySize=9,minoritySize=0,majorityVoters=names,minorityVoters=[],abstainers=[],majorityJoiners=names,dissentingWriters=[])
        record={'name':'Test','decision':decision,'provenance':{},'opinionDetails':[]}
        historical={'decision':dict(type='9-0',source='scdb')}
        state={'records':{'2025/example':record,'2024/example':historical},'research':{'2025/example':{'evidence':['Official source']}}}
        before=copy.deepcopy(state)
        self.assertEqual(migrate(state,{},{}),['2025/example'])
        self.assertEqual(state['records']['2025/example']['decision']['type'],'9-0')
        self.assertEqual(state['records']['2024/example'],before['records']['2024/example'])
        self.assertEqual(state['migrations'][REVISION]['originals']['2025/example']['record'],before['records']['2025/example'])
        self.assertEqual(migrate(state,{},{}),[])

    def test_only_known_fixed_failures_retry_once(self):
        saved={'status':'needs_review','notes':'ValueError: Invalid justice list'}
        self.assertTrue(retry_fixed_error(saved))
        self.assertFalse(retry_fixed_error(saved|{'coding_revision':CODING_REVISION}))
        self.assertFalse(retry_fixed_error({'status':'needs_review','notes':'Which opinion controls Part II?'}))

    def test_empty_php_maps(self):
        for value in (None,[],{}):
            self.assertEqual(owner_answers({'answers':value}),{})
        self.assertEqual(owner_answers({'answers':{'2026/25-1':'Use the opinion'}}),{'2026/25-1':'Use the opinion'})
        with self.assertRaises(ValueError):owner_answers({'answers':['unexpected']})

    def test_worker_uses_stats_role_and_private_key(self):
        cloud=Mock();cloud.secret.return_value=b'{"dashboard_url":"https://example.test/youtube","dashboard_key":"private-key"}'
        dashboard=Mock();dashboard.call.return_value=None
        with patch('scotus_cloud.statistics_worker.Google',return_value=cloud),patch('scotus_cloud.statistics_worker.Dashboard',return_value=dashboard) as constructor,patch.dict('os.environ',{'GOOGLE_CLOUD_PROJECT':'test','SCOTUS_STATS_TOKEN':'claim'}):
            main()
        constructor.assert_called_once_with('https://example.test/youtube','private-key','stats')
        dashboard.call.assert_called_once_with('stats_start',token='claim')

    def test_empty_oyez_response_keeps_official_material(self):
        import tempfile
        response=Mock(ok=True);response.json.return_value=[]
        with tempfile.TemporaryDirectory() as folder,patch('scotus_cloud.statistics_worker.official',return_value=b'{"ProceedingsandOrder":[]}'),patch('scotus_cloud.statistics_worker.requests.get',return_value=response):
            material=opinion_material({'docket_number':'25-498','term':'2026'},{},{},Path(folder))
        self.assertIn('/25-498.json',material['docket_url'])
        self.assertNotIn('facts',material)

if __name__=='__main__':unittest.main()
