import base64,io,json,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from PIL import Image
from scotus_cloud.card_mcp import card_server,mcp_content
from scotus_cloud.claude_runner import run_claude,oauth_value
from scotus_cloud.research_errors import ResearchUnavailable

TOOL={'name':'probe','description':'Fixture host tool','inputSchema':{'type':'object','additionalProperties':False,'properties':{'word':{'type':'string'}},'required':['word']}}
SCHEMA={'type':'object','additionalProperties':False,'properties':{'ok':{'type':'boolean'}},'required':['ok']}
FAKE='''#!/usr/bin/env python3
import json,os,sys,time
from urllib.request import Request,urlopen
if '--version' in sys.argv:
 print('2.1.317 (Claude Code)');raise SystemExit(0)
args=sys.argv
value=lambda name:args[args.index(name)+1]
assert '--bare' not in args and '--no-session-persistence' in args
assert value('--tools') in ('','WebSearch,WebFetch','Read,Grep,Glob','Read,Grep,Glob,WebSearch,WebFetch') and value('--permission-mode')=='dontAsk'
assert 'ANTHROPIC_API_KEY' not in os.environ and 'OPENAI_API_KEY' not in os.environ and 'SCOTUS_PRIVATE_CODEX_WORKER' not in os.environ
assert os.environ['CLAUDE_CODE_OAUTH_TOKEN']=='dedicated-fixture-oauth'
policy=open(value('--system-prompt-file')).read()
if policy=='WEB':assert 'WebSearch,WebFetch' in value('--tools')
if policy=='FILES':
 assert value('--tools')=='Read,Grep,Glob'
 assert open('reference/sources/sample/pages/00001.txt').read()=='Exact source text.'
 assert open('input/case.json').read()=='{}'
 settings=json.load(open(value('--settings')))
 assert settings['disableAllHooks'] and settings['permissions']['blockReadsOutsideWorkingDirectories']
 assert settings['permissions']['blockWritesOutsideWorkingDirectories']
 assert settings['permissions']['additionalDirectories']==[os.path.realpath('reference')]
 assert any('mcp.json' in rule for rule in settings['permissions']['deny'])
 assert not os.path.exists('mcp.json')
 assert not any(name in value('--tools').split(',') for name in ('Bash','Edit','Write'))
if policy=='TIMEOUT':time.sleep(30)
if policy=='ERROR':
 print(json.dumps({'is_error':True,'result':'dedicated-fixture-oauth secret error'}));raise SystemExit(1)
if policy=='UNSTRUCTURED':
 print(json.dumps({'is_error':False,'result':'text instead of schema'}));raise SystemExit(0)
config=json.load(open(value('--mcp-config')))['mcpServers']['cards']
def call(message):
 r=urlopen(Request(config['url'],json.dumps(message).encode(),{'Content-Type':'application/json',**config['headers']}),timeout=5)
 return json.load(r) if r.status!=202 else None
assert call({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26'}})['result']['capabilities']['tools']=={}
assert call({'jsonrpc':'2.0','method':'notifications/initialized'}) is None
assert call({'jsonrpc':'2.0','id':2,'method':'tools/list'})['result']['tools'][0]['name']=='probe'
result=call({'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'probe','arguments':{'word':'exact'}}})['result']
assert not result['isError'] and result['content'][1]['type']=='image' and result['content'][1]['mimeType']=='image/jpeg'
assert 'input/case.json' in json.loads(sys.stdin.read().split('JSON input:\\n',1)[1])
print(json.dumps({'structured_output':{'ok':True},'is_error':False,'usage':{'input_tokens':12,'output_tokens':3},'num_turns':1,'total_cost_usd':0.0}))
'''

class ClaudeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.binary=Path(self.tmp.name)/'claude';self.binary.write_text(FAKE);self.binary.chmod(0o700)
  self.cloud=Mock();self.cloud.secret.return_value=b'{"oauth_token":"dedicated-fixture-oauth"}'
  self.dashboard=Mock();self.dashboard.call.return_value='private-lease';self.started=Mock();self.usage=Mock()
  output=io.BytesIO();Image.new('RGB',(4,4),'beige').save(output,'JPEG');self.data=base64.b64encode(output.getvalue()).decode()
  self.handler=Mock(return_value={'contentItems':[{'type':'inputText','text':'verified'},{'type':'inputImage','imageUrl':'data:image/jpeg;base64,'+self.data}]})
 def run_fixture(self,prompt='POLICY',seconds=5,web=False,references=None):
  with patch('scotus_cloud.claude_runner.shutil.which',return_value=str(self.binary)),patch.dict(os.environ,{'SCOTUS_PRIVATE_CODEX_WORKER':'1','ANTHROPIC_API_KEY':'must-not-inherit','OPENAI_API_KEY':'must-not-inherit'}):
   return run_claude(self.dashboard,self.cloud,'scotus-video-claude',prompt,SCHEMA,'haiku' if web else 'opus',inputs={'input/case.json':'{}'},tools=[TOOL],tool_handler=self.handler,timeout_seconds=seconds,web=web,on_start=self.started,on_usage=self.usage,references=references)
 def test_filesystem_tools_get_shared_sources_and_separate_input_files(self):
  root=Path(self.tmp.name)/'reference';(root/'sources/sample/pages').mkdir(parents=True);(root/'archive').mkdir()
  (root/'sources/sample/pages/00001.txt').write_text('Exact source text.')
  try:self.assertEqual(self.run_fixture('FILES',references=root),{'ok':True})
  except PermissionError as error:self.skipTest(str(error))
 def test_reader_has_explicit_web_access_in_addition_to_cached_source_tools(self):
  try:self.assertEqual(self.run_fixture('WEB',web=True),{'ok':True})
  except PermissionError as error:self.skipTest(str(error))
 def test_real_subprocess_and_loopback_mcp_roundtrip_without_any_model_call(self):
  try:result=self.run_fixture()
  except PermissionError as error:self.skipTest('Loopback sandbox permission: '+str(error))
  self.assertEqual(result,{'ok':True});self.handler.assert_called_once_with('probe',{'word':'exact'});self.started.assert_called_once()
  self.assertEqual(self.usage.call_args.args[0]['usage']['input_tokens'],12)
  self.assertEqual(self.dashboard.call.call_args.args[0],'auth_release')
 def test_provider_errors_do_not_expose_authentication_values(self):
  try:
   with self.assertRaises(ResearchUnavailable) as failure:self.run_fixture('ERROR')
  except PermissionError as error:self.skipTest(str(error))
  self.assertNotIn('dedicated-fixture-oauth',str(failure.exception));self.assertEqual(self.dashboard.call.call_args.args[0],'auth_release')
 def test_missing_structured_output_is_never_treated_as_a_valid_card_result(self):
  try:
   with self.assertRaisesRegex(ResearchUnavailable,'schema-validated'):self.run_fixture('UNSTRUCTURED')
  except PermissionError as error:self.skipTest(str(error))
 def test_timeout_terminates_the_process_and_releases_its_lease(self):
  began=time.monotonic()
  try:
   with self.assertRaisesRegex(ResearchUnavailable,'time limit'):self.run_fixture('TIMEOUT',1)
  except PermissionError as error:self.skipTest(str(error))
  self.assertLess(time.monotonic()-began,8);self.assertEqual(self.dashboard.call.call_args.args[0],'auth_release')
 def test_no_credential_or_wrong_cli_version_starts_no_model(self):
  with patch('scotus_cloud.claude_runner.shutil.which',return_value=None),patch.dict(os.environ,{'SCOTUS_PRIVATE_CODEX_WORKER':'1'}):
   with self.assertRaisesRegex(ResearchUnavailable,'Install'):run_claude(self.dashboard,self.cloud,'secret','p',SCHEMA,'opus',tools=[TOOL],tool_handler=self.handler)
  self.started.assert_not_called();self.dashboard.call.assert_not_called()
  self.binary.write_text('#!/usr/bin/env python3\nprint("old (Claude Code)")\n')
  with patch('scotus_cloud.claude_runner.shutil.which',return_value=str(self.binary)),patch.dict(os.environ,{'SCOTUS_PRIVATE_CODEX_WORKER':'1'}):
   with self.assertRaisesRegex(ResearchUnavailable,'version'):run_claude(self.dashboard,self.cloud,'secret','p',SCHEMA,'opus',tools=[TOOL],tool_handler=self.handler)
  self.cloud.secret.assert_not_called()
 def test_oauth_token_format_rejects_multiline_or_empty_values(self):
  for value in ('','token\nother','token other'):
   with self.assertRaises(ValueError):oauth_value(json.dumps({'oauth_token':value}))

class MCPTests(unittest.TestCase):
 def test_authentication_role_catalog_and_argument_validation(self):
  handler=Mock(return_value={'saved':True})
  try:
   with card_server([TOOL],handler) as config:
    c=config['mcpServers']['cards'];payload={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'probe','arguments':{'unexpected':'value'}}}
    with self.assertRaises(HTTPError) as denied:urlopen(Request(c['url'],json.dumps(payload).encode(),{'Content-Type':'application/json'}))
    self.assertEqual(denied.exception.code,403)
    value=json.load(urlopen(Request(c['url'],json.dumps(payload).encode(),c['headers'])))
    self.assertTrue(value['result']['isError']);handler.assert_not_called()
  except PermissionError as error:self.skipTest(str(error))
 def test_only_inline_preview_images_are_forwarded(self):
  with self.assertRaises(ValueError):mcp_content({'contentItems':[{'type':'inputImage','imageUrl':'https://example.com/private.jpg'}]})

if __name__=='__main__':unittest.main()
