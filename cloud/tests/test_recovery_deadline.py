import json,tempfile,unittest
from pathlib import Path
from unittest.mock import AsyncMock,Mock,patch
from scotus_cloud.recovery_worker import run_turn

class DeadlineTests(unittest.IsolatedAsyncioTestCase):
 async def test_repair_wrap_up_steers_same_turn_and_saves_continuation(self):
  process=Mock(returncode=0);rpc=Mock();rpc.send=AsyncMock()
  rpc.request=AsyncMock(side_effect=[{}, {'thread':{'id':'thread'}},{'turn':{'id':'active'}}])
  result={'status':'unresolved','private_summary':'Saved diagnosis and next experiment','checks':[],'workflow_patch_refs':[],'operator_messages':[]}
  rpc.receive=AsyncMock(side_effect=[{'method':'item/completed','params':{'item':{'type':'agentMessage','text':json.dumps(result)}}},{'method':'turn/completed','params':{'turn':{'status':'completed'}}}])
  times=iter([0,0]+[1001]*30);tools=Mock();tools.waiting=False
  with tempfile.TemporaryDirectory() as folder,patch('asyncio.create_subprocess_exec',AsyncMock(return_value=process)),patch('scotus_cloud.recovery_worker.RPC',return_value=rpc),patch('scotus_cloud.recovery_worker.checkpoint_session') as saved:
   value,thread=await run_turn({'_auth_lease':'lease'},Mock(),Mock(),{}, {},Path(folder),Path(folder),tools,clock=lambda:next(times))
  self.assertEqual(value,result);self.assertEqual(thread,'thread')
  steering=[c.args[0] for c in rpc.send.call_args_list if c.args[0].get('method')=='turn/steer']
  self.assertEqual(len(steering),1);self.assertEqual(steering[0]['params']['expectedTurnId'],'active')
  self.assertEqual(sum(c.args[0]=='turn/start' for c in rpc.request.call_args_list),1);self.assertGreaterEqual(saved.call_count,1)
