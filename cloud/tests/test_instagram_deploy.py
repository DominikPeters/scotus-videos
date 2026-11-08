import importlib.util,json,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('instagram_deploy',Path(__file__).resolve().parents[1]/'infra/deploy_instagram_clips.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class InstagramDeployTests(unittest.TestCase):
 def test_secret_response_wrapper_is_rejected(self):
  with self.assertRaisesRegex(ValueError,'Incomplete controller'):
   module.controller_configuration(json.dumps({'name':'projects/p/secrets/s/versions/1','payload':{'data':'e30='}}))
 def test_existing_controller_settings_are_preserved(self):
  cfg={'project':'p','dashboard_url':'url','dispatcher_key':'private','control_key':'private','clip_job':'clips','jobs':{'align':'align'}}
  result=module.controller_configuration(json.dumps(cfg))
  self.assertEqual({k:v for k,v in result.items() if k!='instagram_clip_job'},cfg)
  self.assertEqual(result['instagram_clip_job'],'scotus-video-instagram-clips')
