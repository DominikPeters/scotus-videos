import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.annotation_cards import clean,cue_for,CardTools,normalized
from scotus_cloud.model import digest_json
class CardTests(unittest.TestCase):
 def card(self):return {'id':'case-one','start_block':1,'end_block':2,'cue_json':json.dumps({'kind':'Excerpt','quote':'A source passage','highlight':['source passage']}),'evidence':[{'source_id':'source','page':1,'quote':'A source passage','claim':'Supports this text'}],'recommended':False,'reason':'Optional context','preview_id':'','visual_checked':False}
 def test_block_timing_and_markup(self):
  transcript={'paragraphs':[{'start':0},{'start':12},{'start':21}],'audio':{'duration_seconds':30}}
  self.assertEqual(cue_for(self.card(),transcript)['start'],12);self.assertEqual(cue_for(self.card(),transcript)['end'],21)
  for value in ('<script>alert(1)</script>','<img src=x>','<mark onclick=x>hi</mark>'):
   with self.assertRaises(ValueError):clean(value)
  self.assertEqual(clean('<mark>for cause</mark>'),'<mark>for cause</mark>')
 def test_evidence_and_final_preview_are_bound_to_card_content(self):
  with tempfile.TemporaryDirectory() as folder:
   tools=CardTools({'id':'job'}, {},{}, {},Mock(),Mock(),folder);tools.sources['source']={'url':'https://court.example/doc','sha256':'sha','pages':[{'page':1,'text':'A source passage in context'}]}
   card=self.card();tools.verify(card['evidence']);bad=self.card();bad['evidence'][0]['quote']='Invented text'
   with self.assertRaises(ValueError):tools.verify(bad['evidence'])
   identifier=digest_json({k:v for k,v in card.items() if k not in ('preview_id','visual_checked')});tools.previews[identifier]={'start':12,'end':21,'cue':{'kind':'Excerpt'},'frame_uri':'frame','card_uri':'card'}
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
   identifier=digest_json({k:v for k,v in card.items() if k not in ('preview_id','visual_checked')})
   tools.previews[identifier]={'start':12,'end':21,'cue':{'kind':'Excerpt'},'frame_uri':'frame','card_uri':'card'}
   self.assertIn(identifier,tools.validate(result)['errors'][0]['error'])
   card['preview_id']=identifier;self.assertTrue(tools.validate(result)['valid'])
   result['cards'].append(dict(card));self.assertIn('Duplicate',tools.validate(result)['errors'][0]['error'])
   cloud.storage_upload.assert_not_called()
 def test_quotes_normalize_typography_without_inventing_words(self):
  self.assertEqual(normalized('“for cause”'),normalized('"for cause"'))
  self.assertNotEqual(normalized('may remove'),normalized('must remove'))
 def test_review_renderer_uses_production_frame_protocol(self):
  script=(Path(__file__).resolve().parents[1]/'presentation/renderer/script.js').read_text();driver=(Path(__file__).resolve().parents[1]/'render/original.js').read_text()
  self.assertIn('QUOTE_FRAME_DURATION = 0.05',script);self.assertIn('QUOTE_TRANSITION_FRAMES = 24',script);self.assertNotIn('setUpPreviewControls',script);self.assertIn("op('setQuoteProgress',[quote])",driver)
if __name__=='__main__':unittest.main()
