import json,tempfile,unittest
from pathlib import Path
from scotus_cloud.card_history import CardHistory

class Cloud:
 def __init__(self):self.objects={};self.current={'version':0,'checkpoint':None}
 def call(self,op,**data):
  if op=='research_load':return json.loads(json.dumps(self.current))
  if data['version']!=self.current['version']:raise RuntimeError('Newer checkpoint exists')
  self.current={'version':self.current['version']+1,'checkpoint':json.loads(json.dumps(data['checkpoint']))};return {'version':self.current['version']}
 def storage_upload(self,path,uri,content_type):self.objects[uri]=Path(path).read_bytes()
 def storage_json(self,uri,**kwargs):return json.loads(self.objects[uri])
 def storage_bytes(self,uri,**kwargs):return self.objects[uri]
 def request(self,method,url,params):return {'items':[{'name':uri.split('/',3)[3]} for uri in self.objects if params['prefix'] in uri]}
class Tools:
 def __init__(self):self.sources={};self.previews={};self.proposals={};self.assets={}
class HistoryTests(unittest.TestCase):
 def test_metadata_changes_keep_case_research_and_one_current_checkpoint(self):
  with tempfile.TemporaryDirectory() as folder:
   cloud=Cloud();job={'id':'case'};settings={'bucket':'private-bucket'};tools=Tools()
   first=CardHistory(job,{'paragraphs':[{'speaker':'a','text':'Words'}],'inputs':{'pdf_url':'old'}},settings,cloud,folder,store=cloud)
   tools.sources={'s':{'url':'https://court.example','pages':[]}};first.plan['phase']='design';first.save(tools)
   resumed=CardHistory(job,{'paragraphs':[{'speaker':'a','text':'Words'}],'inputs':{'pdf_url':'new'}},settings,cloud,folder,store=cloud);restored=Tools();resumed.load(restored)
   self.assertEqual(restored.sources,tools.sources);self.assertEqual(resumed.plan['phase'],'design')
   for n in range(110):resumed.event({'n':n});resumed.save(restored)
   self.assertEqual(len(cloud.current['checkpoint']['events']),100)
   self.assertFalse(any('/checkpoints/' in uri for uri in cloud.objects));self.assertEqual(len(cloud.objects),1)
 def test_changed_transcript_rebinds_unchanged_blocks_and_retains_sources(self):
  with tempfile.TemporaryDirectory() as folder:
   cloud=Cloud();job={'id':'case'};settings={'bucket':'private-bucket'};old={'paragraphs':[{'speaker':'a','text':'Keep'},{'speaker':'a','text':'Replace'}]}
   tools=Tools();tools.sources={'s':{'url':'https://court.example','pages':[]}};tools.proposals={'keep':{'id':'keep','start_block':0,'end_block':1,'visual_checked':True},'replace':{'id':'replace','start_block':1,'end_block':2,'visual_checked':True}}
   CardHistory(job,old,settings,cloud,folder,store=cloud).save(tools)
   new={'paragraphs':[{'speaker':'b','text':'Inserted'},old['paragraphs'][0],{'speaker':'a','text':'Changed'}]};restored=Tools();history=CardHistory(job,new,settings,cloud,folder,store=cloud);history.load(restored)
   self.assertEqual(restored.proposals['keep']['start_block'],1);self.assertNotIn('replace',restored.proposals)
   self.assertFalse(restored.proposals['keep']['visual_checked']);self.assertEqual(history.plan['decisions'][0]['status'],'pending');self.assertEqual(restored.sources,tools.sources)
 def test_realignment_keeps_research_but_discards_visual_approval(self):
  with tempfile.TemporaryDirectory() as folder:
   cloud=Cloud();settings={'bucket':'private-bucket'};transcript={'paragraphs':[]}
   job={'id':'case','stages':{'align':{'result':{'transcript_uri':'gs://bucket/old.json'}}}}
   tools=Tools();tools.previews={'p':{'start':12}};tools.proposals={'p':{'id':'p','visual_checked':True,'preview_id':'old'}}
   tools.sources={'s':{'url':'https://court.example','pages':[]}}
   history=CardHistory(job,transcript,settings,cloud,folder,store=cloud)
   history.plan={'phase':'design','opportunities':[{'id':'p'}],'decisions':[{'id':'p','draft':dict(tools.proposals['p'])}]};history.save(tools)
   job['stages']['align']['result']['transcript_uri']='gs://bucket/new.json'
   resumed=CardHistory(job,transcript,settings,cloud,folder,store=cloud);restored=Tools();resumed.load(restored)
   self.assertEqual(restored.sources,tools.sources);self.assertEqual(resumed.plan['phase'],'design')
   self.assertFalse(restored.previews);self.assertFalse(restored.proposals['p']['visual_checked'])
   self.assertEqual(restored.proposals['p']['preview_id'],'');self.assertFalse(resumed.plan['decisions'][0]['draft']['visual_checked'])
   restored.previews={'fresh':{'start':20}};resumed.save(restored)
   again=Tools();CardHistory(job,transcript,settings,cloud,folder,store=cloud).load(again)
   self.assertEqual(again.previews,restored.previews)
 def test_research_and_previews_survive_a_new_worker(self):
  with tempfile.TemporaryDirectory() as folder:
   cloud=Cloud();job={'id':'case'};settings={'bucket':'private-bucket','worker_key':'private-session-token'};transcript={'paragraphs':[]}
   history=CardHistory(job,transcript,settings,cloud,folder,store=cloud);tools=Tools()
   tools.sources['s']={'url':'https://court.example/document','sha256':'sha','pages':[{'text':'Source passage','page':1}]}
   tools.previews['p']={'card_uri':'gs://bucket/card.jpg'};tools.proposals['map']={'id':'map'};tools.assets['image']=b'image'
   history.plan={'phase':'sources','opportunities':[{'id':'map'}],'decisions':[]};history.event({'text':'Useful passage private-session-token'});first=history.save(tools)
   history.plan['phase']='design';history.save(tools)
   resumed=CardHistory(job,transcript,settings,cloud,folder,store=cloud);restored=Tools();resumed.load(restored)
   self.assertEqual(resumed.plan['phase'],'design');self.assertEqual(restored.proposals,tools.proposals);self.assertEqual(restored.previews,tools.previews);self.assertEqual(restored.sources,tools.sources);self.assertEqual(restored.assets,tools.assets)
   self.assertNotIn('private-session-token',json.dumps(resumed.events));self.assertIn('[redacted]',json.dumps(resumed.events))
   # Source indexes and images are saved once, not recopied with every checkpoint.
   self.assertEqual(sum('/sources/' in uri for uri in cloud.objects),1);self.assertEqual(sum('/exhibits/' in uri for uri in cloud.objects),1)
if __name__=='__main__':unittest.main()
