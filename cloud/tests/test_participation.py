import copy,json,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from scotus_cloud.participation import validate_participation,apply_participation
from scotus_cloud.case_descriptions import generate_case_description

class ParticipationTests(unittest.TestCase):
 def setUp(self):
  self.case={'docket':'25-170','case_name':'Suncor','argument_date':'2026-10-05'}
  self.finding={**{k:self.case[k] for k in ('docket','argument_date')},'justices':[{'identifier':'samuel_a_alito_jr','status':'recused','explanation':'Clerk says Alito will not continue participating in this case.','evidence':[{'date':'2026-09-28','url':'https://www.supremecourt.gov/RSS/Cases/JSON/25-170.json','excerpt':'Justice Alito will not continue to participate in this case.'}]}],'private_notes':[]}
 def test_confirmed_recusal_requires_identity_and_official_evidence(self):
  validate_participation(self.finding,self.case)
  wrong=copy.deepcopy(self.finding);wrong['docket']='22-1219'
  with self.assertRaisesRegex(ValueError,'identity'):validate_participation(wrong,self.case)
  wrong=copy.deepcopy(self.finding);wrong['justices'][0]['evidence']=[]
  with self.assertRaisesRegex(ValueError,'evidence'):validate_participation(wrong,self.case)
 def test_restore_recused_seat_without_shifting_other_justices(self):
  catalog=json.loads((Path(__file__).resolve().parents[1]/'speaker-catalog.json').read_text())
  members=[copy.deepcopy(p) for p in sorted(catalog.values(),key=lambda p:p.get('seniority',99)) if p.get('seniority') is not None and p['identifier']!='samuel_a_alito_jr']
  data={'heard_by':[{'members':members}]};apply_participation(data,self.finding,catalog)
  self.assertEqual(len(members),8)
  members=data['heard_by'][0]['members']
  self.assertEqual(len(members),9);self.assertEqual(members[2]['identifier'],'samuel_a_alito_jr');self.assertTrue(members[2]['recused'])
  self.assertFalse(members[1]['recused'])
  self.finding['justices'][0]['status']='uncertain';apply_participation(data,self.finding,catalog)
  self.assertFalse(any(p['recused'] for p in data['heard_by'][0]['members']))
 @patch('scotus_cloud.case_descriptions.run_codex')
 def test_short_oyez_still_checks_docket_once_without_rewriting(self,runner):
  runner.return_value={'sources':[{'id':'docket','title':'Court docket','url':'https://www.supremecourt.gov/RSS/Cases/JSON/25-170.json','kind':'docket','document_date':None,'locator':'ProceedingsandOrder','relevant_passage':'Justice Alito will not continue to participate in this case.'}], 'background':[],'issues':[],'private_caveats':[],'participation':self.finding}
  oyez={'facts_of_the_case':'<p>Existing facts.</p>','question':'<p>Existing question?</p>'}
  result=generate_case_description(Mock(),Mock(),'secret',self.case,oyez=oyez,materials=[{'id':'docket','text':'Court docket'},{'id':'transcript','text':'Long transcript not needed here'}],check_participation=True)
  runner.assert_called_once();self.assertEqual(result['fields'],oyez);self.assertEqual(result['participation'],self.finding)
  inputs=runner.call_args.kwargs['inputs'];request=json.loads(inputs['input/request.json']);self.assertTrue(request['participation_only'])
  self.assertEqual([m['id'] for m in json.loads(inputs['input/materials.json'])],['docket'])
