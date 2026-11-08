import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.annotation_cards import clean,cue_for,CardTools,normalized,preview_fingerprint
from scotus_cloud.model import digest_json
class CardTests(unittest.TestCase):
 def card(self):return {'id':'case-one','start_block':1,'end_block':2,'cue_json':json.dumps({'kind':'Excerpt','quote':'A source passage','heading':'Source passage','source':'Official source','highlight':['source passage']}),'evidence':[{'source_id':'source','page':1,'quote':'A source passage','claim':'Supports this text'}],'recommended':False,'reason':'Optional context','preview_id':'','visual_checked':False}
 def test_block_timing_and_markup(self):
  transcript={'paragraphs':[{'start':0,'text':''},{'start':12,'text':'source passage'},{'start':21,'text':''}],'audio':{'duration_seconds':30}}
  self.assertEqual(cue_for(self.card(),transcript)['start'],12);self.assertEqual(cue_for(self.card(),transcript)['end'],21)
  for value in ('<script>alert(1)</script>','<img src=x>','<mark onclick=x>hi</mark>'):
   with self.assertRaises(ValueError):clean(value)
  self.assertEqual(clean('<mark>for cause</mark>'),'<mark>for cause</mark>')
 def test_evidence_and_final_preview_are_bound_to_card_content(self):
  with tempfile.TemporaryDirectory() as folder:
   tools=CardTools({'id':'job'}, {},{}, {},Mock(),Mock(),folder);tools.sources['source']={'url':'https://court.example/doc','sha256':'sha','pages':[{'page':1,'text':'A source passage in context'}]}
   card=self.card();tools.verify(card['evidence']);bad=self.card();bad['evidence'][0]['quote']='Invented text'
   with self.assertRaises(ValueError):tools.verify(bad['evidence'])
   identifier=preview_fingerprint(card);tools.previews[identifier]={'start':12,'end':21,'cue':{'kind':'Excerpt'},'frame_uri':'frame','card_uri':'card'}
   card.update(preview_id=identifier,visual_checked=True);self.assertFalse(tools.finish({'cards':[card],'private_notes':[]})['cards'][0]['recommended'])
   card['reason']='Changed after rendering'
   with self.assertRaises(ValueError):tools.finish({'cards':[card],'private_notes':[]})
 def test_validator_reports_actionable_errors_without_uploading(self):
  with tempfile.TemporaryDirectory() as folder:
   cloud=Mock();tools=CardTools({'id':'job'}, {},{}, {},cloud,Mock(),folder)
   tools.sources['source']={'url':'https://court.example/doc','sha256':'sha','pages':[{'page':1,'text':'A source passage in context'}]}
   card=self.card();result={'cards':[card],'private_notes':[]}
   self.assertIn('visual_checked',tools.invoke('cards_validate',result)['errors'][0]['error'])
   card['visual_checked']=True
   self.assertIn('No production preview',tools.validate(result)['errors'][0]['error'])
   identifier=preview_fingerprint(card)
   tools.previews[identifier]={'start':12,'end':21,'cue':{'kind':'Excerpt'},'frame_uri':'frame','card_uri':'card'}
   self.assertIn(identifier,tools.validate(result)['errors'][0]['error'])
   card['preview_id']=identifier;self.assertTrue(tools.validate(result)['valid'])
   result['cards'].append(dict(card));self.assertIn('Duplicate',tools.validate(result)['errors'][0]['error'])
   cloud.storage_upload.assert_not_called()
 def test_card_duration_labels_and_repeated_marks_are_rejected(self):
  transcript={'paragraphs':[{'start':0,'text':'consumer consumer consumer'},{'start':12,'text':'source passage'},{'start':80,'text':''}],'audio':{'duration_seconds':90}}
  with self.assertRaisesRegex(ValueError,'60 seconds'):cue_for(self.card(),transcript)
  transcript['paragraphs'][2]['start']=40
  card=self.card();cue=json.loads(card['cue_json']);cue['label']='A teaser';card['cue_json']=json.dumps(cue)
  with self.assertRaisesRegex(ValueError,'label'):cue_for(card,transcript)
  cue.pop('label');cue['highlight']=['consumer'];card['cue_json']=json.dumps(cue)
  with self.assertRaisesRegex(ValueError,'occurs 3 times'):cue_for(card,transcript)
 def test_comparison_columns_require_citations(self):
  from scotus_cloud.annotation_cards import validate_template
  cue={'kind':'Comparison','heading':'Compare provisions','source':'Code','compare':[{'title':'First','text':'Text'},{'title':'Second','cite':'Section two','text':'Text'}]}
  with self.assertRaisesRegex(ValueError,'cite'):validate_template(cue)
 def test_quotes_normalize_typography_without_inventing_words(self):
  self.assertEqual(normalized('“for cause”'),normalized('"for cause"'))
  self.assertNotEqual(normalized('may remove'),normalized('must remove'))
  for marked,plain in [('<mark>party</mark>—is','party—is'),('word—<i>next</i>','word—next'),('for<mark>feit</mark>ure','forfeiture'),('a<br>b','a b')]:
   self.assertEqual(normalized(marked),normalized(plain))
  self.assertNotEqual(normalized('may <mark>remove</mark>'),normalized('may retain'))
 def test_pdf_double_quote_typography(self):
  self.assertEqual(normalized('The term ‘‘consumer’’ means any renter.'),normalized('The term “consumer” means any renter.'))
  self.assertEqual(normalized('any <mark>person</mark>, in commerce'),normalized('any person, in commerce'))
  self.assertNotEqual(normalized('The term consumer includes buyers.'),normalized('The term consumer excludes buyers.'))
 def test_pending_sourced_drafts_block_empty_success(self):
  with tempfile.TemporaryDirectory() as folder:
   tools=CardTools({'id':'job'}, {},{}, {},Mock(),Mock(),folder)
   tools.history=Mock();tools.history.plan={'decisions':[{'id':'split','status':'pending','draft':self.card()}]}
   with self.assertRaisesRegex(ValueError,'remains pending'):tools.finish({'cards':[],'private_notes':[]})
   tools.history.plan['decisions'][0]['status']='omitted'
   self.assertEqual(tools.finish({'cards':[],'private_notes':[]})['cards'],[])
 def test_preview_excludes_previous_unapproved_cards(self):
  with tempfile.TemporaryDirectory() as folder:
   tools=CardTools({'id':'job'}, {},{'photos':{},'annotations':{'cards':[self.card()]}}, {},Mock(),Mock(),folder)
   tools.aligned={'paragraphs':[{'start':0,'text':''},{'start':12,'text':'source passage'},{'start':21,'text':''}],'audio':{'duration_seconds':30},'speakers':{}}
   tools.sources['source']={'url':'https://court.example/doc','pages':[{'page':1,'text':'A source passage'}]}
   error=__import__('subprocess').CalledProcessError(1,['node'],stderr=b'Renderer diagnostic')
   def bundle(folder,job,aligned,enrichment,cloud):
    self.assertEqual(enrichment['annotations'],{})
    (folder/'json').mkdir(parents=True)
   with patch('scotus_cloud.bundle.make_bundle',side_effect=bundle),patch('scotus_cloud.annotation_cards.subprocess.run',side_effect=error):
    with self.assertRaisesRegex(ValueError,'Renderer diagnostic'):tools.render(self.card())
 def test_coordinator_respects_auth_timeout_contract(self):
  from scotus_cloud.annotation_cards import generate_cards
  with tempfile.TemporaryDirectory() as folder,patch('scotus_cloud.codex_auth.run_codex',return_value={'cards':[],'private_notes':[]}) as run:
   generate_cards({'id':'job','docket':'1','case_name':'Case','argument_date':'2026-10-14','pdf_url':'https://court.example'}, {'paragraphs':[]},{},{'codex_secret':'secret'},Mock(),Mock(),folder)
   self.assertLessEqual(run.call_args.kwargs['timeout_seconds'],900)
 def test_hyphen_comparison_is_symmetric_and_keeps_words(self):
  self.assertEqual(normalized('open- reel'),normalized('open-reel'))
  self.assertEqual(normalized('mate- rials'),normalized('materials'))
  self.assertNotEqual(normalized('must include'),normalized('may include'))
  self.assertNotEqual(normalized('2019'),normalized('2020'))
 def test_highlight_scope_excludes_earlier_repetitions(self):
  card=self.card();cue=json.loads(card['cue_json']);cue['highlight']=['includes'];card['cue_json']=json.dumps(cue)
  transcript={'paragraphs':[{'start':0,'text':'includes includes includes'},{'start':12,'text':'includes'},{'start':30,'text':''}],'audio':{'duration_seconds':40}}
  with self.assertRaisesRegex(ValueError,'occurs 4 times'):cue_for(card,transcript)
  cue['highlight_from']=12;card['cue_json']=json.dumps(cue)
  self.assertEqual(cue_for(card,transcript)['highlight_from'],12)
  cue['highlight_from']=13;card['cue_json']=json.dumps(cue)
  with self.assertRaisesRegex(ValueError,'highlight_from'):cue_for(card,transcript)
 def test_preview_fingerprint_includes_renderer_revision(self):
  card=self.card();old=preview_fingerprint(card)
  with patch('scotus_cloud.annotation_cards.json.loads',return_value={'renderer/index.html':{'sha256':'new stylesheet'}}):
   self.assertNotEqual(preview_fingerprint(card),old)
 def test_transcript_highlights_are_plain_text_and_must_match(self):
  card=self.card();cue=json.loads(card['cue_json']);cue['highlight']=['uses "includes"'];card['cue_json']=json.dumps(cue)
  transcript={'paragraphs':[{'start':0,'text':''},{'start':12,'text':'The definition uses "includes" rather than "means."'},{'start':30,'text':''}],'audio':{'duration_seconds':40}}
  self.assertEqual(cue_for(card,transcript)['highlight'],['uses "includes"'])
  cue['highlight']=['not spoken'];card['cue_json']=json.dumps(cue)
  with self.assertRaisesRegex(ValueError,'not present'):cue_for(card,transcript)
 def test_review_renderer_uses_production_frame_protocol(self):
  script=(Path(__file__).resolve().parents[1]/'presentation/renderer/script.js').read_text();driver=(Path(__file__).resolve().parents[1]/'render/original.js').read_text()
  self.assertIn('QUOTE_FRAME_DURATION = 0.05',script);self.assertIn('QUOTE_TRANSITION_FRAMES = 24',script);self.assertNotIn('setUpPreviewControls',script);self.assertIn("op('setQuoteProgress',[quote])",driver)
if __name__=='__main__':unittest.main()

class CardLessonsTests(unittest.TestCase):
 def test_excerpt_labels_and_empty_noncase_labels(self):
  from scotus_cloud.annotation_cards import validate_template
  cue={'kind':'Excerpt','heading':'Opinion','source':'Court','quote':'Words'}
  for label in ('Opinion excerpt','Complaint excerpt','Brief excerpt','Record excerpt','Transcript excerpt'):
   validate_template({**cue,'label':label})
  for label in ('','A helpful correction'):
   with self.assertRaises(ValueError):validate_template({**cue,'label':label})
 def test_timelines_limit_five_events(self):
  from scotus_cloud.annotation_cards import validate_template
  cue={'kind':'Timeline','heading':'History','source':'Docket','timeline':{'events':[{'date':str(n),'label':'Event'} for n in range(5)]}}
  validate_template(cue)
  cue['timeline']['events'].append({'date':'6','label':'Event'})
  with self.assertRaisesRegex(ValueError,'five'):validate_template(cue)
 def test_pdf_wrapping_and_markup_punctuation(self):
  self.assertEqual(normalized('open-\nreel'),normalized('open-reel'))
  self.assertEqual(normalized('emis\u00ad sions'),normalized('emissions'))
  self.assertEqual(normalized('<i>Hall</i> , 440'),normalized('Hall, 440'))
 def test_displayed_quote_must_match_cited_page(self):
  with tempfile.TemporaryDirectory() as folder:
   tools=CardTools({'id':'job'},{},{},{},Mock(),Mock(),folder)
   tools.sources['s']={'pages':[{'page':1,'text':'The Court may review the judgment.'}]}
   evidence=[{'source_id':'s','page':1}]
   tools.verify_display({'kind':'Excerpt','quote':'The Court may … the judgment.'},evidence)
   with self.assertRaisesRegex(ValueError,'Displayed'):tools.verify_display({'kind':'Excerpt','quote':'The Court must review the judgment.'},evidence)

 def test_json_source_decodes_escaped_quotes_and_unicode(self):
  with tempfile.TemporaryDirectory() as folder:
   tools=CardTools({'id':'job'},{},{},{},Mock(),Mock(),folder)
   data=json.dumps({'opinion':{'text':'The Court said “state’s law”.'}}).encode()
   with patch('scotus_cloud.enrichment.fetch',return_value=data):
    source=tools.source('https://static.case.law/example.json','',0)
   tools.verify([{'source_id':source['source_id'],'page':1,'quote':'The Court said “state’s law”.'}])

 def test_every_prompt_example_uses_a_valid_template(self):
  from scotus_cloud.annotation_cards import validate_template,ROOT
  for cue in json.loads((ROOT/'prompts/card-examples.json').read_text())['examples']:
   with self.subTest(kind=cue['kind']):validate_template(cue)
 def test_preview_upload_resumes_without_overwriting_existing_images(self):
  with tempfile.TemporaryDirectory() as folder:
   cloud=Mock();tools=CardTools({'id':'job'},{},{},{},cloud,Mock(),folder)
   cloud.storage_upload.side_effect=RuntimeError('Object upload failed: HTTP 412');cloud.storage_bytes.return_value=b'same'
   uri='gs://bucket/reviews/job/cards/id/card.jpg'
   self.assertEqual(tools.upload_preview('file',uri,b'same'),uri)
   cloud.storage_upload.side_effect=[RuntimeError('Object upload failed: HTTP 412'),None];cloud.storage_bytes.return_value=b'older'
   alternate=tools.upload_preview('file',uri,b'new')
   self.assertNotEqual(alternate,uri);self.assertTrue(alternate.endswith('/card.jpg'))
   cloud.storage_upload.side_effect=RuntimeError('Object upload failed: HTTP 500')
   with self.assertRaisesRegex(RuntimeError,'500'):tools.upload_preview('file',uri,b'new')
