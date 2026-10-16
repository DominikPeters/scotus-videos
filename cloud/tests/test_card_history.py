import json,tempfile,unittest
from pathlib import Path
from scotus_cloud.card_history import CardHistory

class Cloud:
 def __init__(self):self.objects={}
 def storage_upload(self,path,uri,content_type):self.objects[uri]=Path(path).read_bytes()
 def storage_json(self,uri,**kwargs):return json.loads(self.objects[uri])
 def storage_bytes(self,uri,**kwargs):return self.objects[uri]
 def request(self,method,url,params):return {'items':[{'name':uri.split('/',3)[3]} for uri in self.objects if params['prefix'] in uri]}
class Tools:
 def __init__(self):self.sources={};self.previews={};self.proposals={};self.assets={}
class HistoryTests(unittest.TestCase):
 def test_research_and_previews_survive_a_new_worker(self):
  with tempfile.TemporaryDirectory() as folder:
   cloud=Cloud();job={'id':'case'};settings={'bucket':'private-bucket','worker_key':'private-session-token'};transcript={'paragraphs':[]}
   history=CardHistory(job,transcript,settings,cloud,folder);tools=Tools()
   tools.sources['s']={'url':'https://court.example/document','sha256':'sha','pages':[{'text':'Source passage','page':1}]}
   tools.previews['p']={'card_uri':'gs://bucket/card.jpg'};tools.proposals['map']={'id':'map'};tools.assets['image']=b'image'
   history.plan={'phase':'sources','opportunities':[{'id':'map'}],'decisions':[]};history.event({'text':'Useful passage private-session-token'});first=history.save(tools)
   history.plan['phase']='design';history.save(tools)
   resumed=CardHistory(job,transcript,settings,cloud,folder);restored=Tools();resumed.load(restored)
   self.assertEqual(resumed.plan['phase'],'design');self.assertEqual(restored.proposals,tools.proposals);self.assertEqual(restored.previews,tools.previews);self.assertEqual(restored.sources,tools.sources);self.assertEqual(restored.assets,tools.assets)
   self.assertNotIn('private-session-token',json.dumps(resumed.events));self.assertIn('[redacted]',json.dumps(resumed.events))
   # Source indexes and images are saved once, not recopied with every checkpoint.
   self.assertEqual(sum('/sources/' in uri for uri in cloud.objects),1);self.assertEqual(sum('/exhibits/' in uri for uri in cloud.objects),1)
if __name__=='__main__':unittest.main()
