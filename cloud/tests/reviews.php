<?php
require dirname(__DIR__).'/dashboard/private/state.php';
function check(bool $ok,string $message):void{if(!$ok)throw new RuntimeException($message);}
function rejected(callable $fn):void{try{$fn();}catch(Throwable $error){return;}throw new RuntimeException('Invalid action accepted');}
$s=initial_state();$s['paused']=false;$job=add_job($s,['docket'=>'25-735','argument_date'=>'2026-10-05','case_name'=>'Fixture','audio_url'=>'https://www.supremecourt.gov/a.mp3','pdf_url'=>'https://www.supremecourt.gov/t.pdf']);$id=$job['id'];
$s['jobs'][$id]['stages']['prepare']['status']='complete';$s['jobs'][$id]['stages']['align']['status']='complete';
$start=worker_update($s,['op'=>'dispatch','job'=>$id,'stage'=>'enrich'],'dispatcher');
$claim=worker_update($s,['op'=>'claim','job'=>$id,'stage'=>'enrich','dispatch_token'=>$start['dispatch_token']],'enrich');
$revision=str_repeat('b',64);$choice=['id'=>'portrait','portrait_uri'=>'gs://private/photo.jpg','preview_uri'=>'gs://private/preview.jpg','sha256'=>str_repeat('c',64)];
$review=['id'=>'review','revision'=>$revision,'titles'=>[['title'=>'Recommended'],['title'=>'Alternative']],'photos'=>['lawyer'=>['name'=>'Verified lawyer','candidates'=>[$choice]]]];
$result=worker_update($s,['op'=>'enrichment_review','job'=>$id,'stage'=>'enrich','lease'=>$claim['lease'],'review'=>$review,'result'=>['enrichment_uri'=>'gs://private/enrichment.json']],'enrich');
check($result['needs_review'],'Missing photo did not stop processing');
check(count($s['notifications'])===1,'Photo alert missing');
// Simulate a legacy review created while alignment was still pending.
$s['jobs'][$id]['stages']['align']['status']='pending';
$startAlign=worker_update($s,['op'=>'dispatch','job'=>$id,'stage'=>'align'],'dispatcher');
check(!empty($startAlign['dispatch_token']),'Photo review blocked independent alignment');
$align=worker_update($s,['op'=>'claim','job'=>$id,'stage'=>'align','dispatch_token'=>$startAlign['dispatch_token']],'align');
check($s['jobs'][$id]['status']==='needs_review','Alignment hid photo review');
check(worker_update($s,['op'=>'dispatch','job'=>$id,'stage'=>'plan'],'dispatcher')===null,'Plan bypassed photo review');
rejected(function()use(&$s,$id){review_command($s,['job'=>$id,'revision'=>'stale','command'=>'photo','person'=>'lawyer','candidate'=>'portrait']);});
// Approval while another phase failed must clear only the photo hold.
$failure=json_decode(json_encode($s),true);$failure['jobs'][$id]['status']='failed';$failure['jobs'][$id]['stages']['align']['status']='failed';
review_command($failure,['job'=>$id,'revision'=>$revision,'command'=>'photo','person'=>'lawyer','candidate'=>'portrait']);
check($failure['jobs'][$id]['status']==='failed','Approval concealed a failed alignment');
check($failure['jobs'][$id]['stages']['enrich']['status']==='pending','Approval during failure left a stale photo hold');
$failure['jobs'][$id]['status']='needs_review';$failure['jobs'][$id]['stages']['enrich']['status']='needs_review';
reconcile_reviews($failure);check($failure['jobs'][$id]['stages']['enrich']['status']==='pending','Saved approvals were not reconciled');
review_command($s,['job'=>$id,'revision'=>$revision,'command'=>'photo','person'=>'lawyer','candidate'=>'portrait']);
check($s['jobs'][$id]['status']==='running','Photo approval lost active alignment');
check(worker_update($s,['op'=>'dispatch','job'=>$id,'stage'=>'enrich'],'dispatcher')===null,'Approval bypassed unfinished alignment');
worker_update($s,['op'=>'finish','job'=>$id,'stage'=>'align','dispatch_token'=>$startAlign['dispatch_token'],'lease'=>$align['lease'],'result'=>[]],'align');
check(worker_update($s,['op'=>'dispatch','job'=>$id,'stage'=>'plan'],'dispatcher')===null,'Plan bypassed unfinished enrichment');
$resumed=worker_update($s,['op'=>'dispatch','job'=>$id,'stage'=>'enrich'],'dispatcher');check(!empty($resumed['dispatch_token']),'Completed alignment did not release approved enrichment');
review_command($s,['job'=>$id,'revision'=>$revision,'command'=>'title','index'=>1]);
check($s['jobs'][$id]['title']==='Alternative','Title was not selected');
$revision=$s['jobs'][$id]['review']['revision'];
rejected(function()use(&$s,$id,$revision){review_command($s,['job'=>$id,'revision'=>$revision,'command'=>'publish']);});
$s['jobs'][$id]['status']='complete';$s['jobs'][$id]['stages']['upload']=['status'=>'complete','result'=>['video_id'=>'existing','postprocessing_complete'=>true]];
review_command($s,['job'=>$id,'revision'=>$revision,'command'=>'publish']);review_command($s,['job'=>$id,'revision'=>$revision,'command'=>'publish']);
check(count($s['jobs'][$id]['video_actions'])===1,'Publication was not deduplicated');
$action=worker_update($s,['op'=>'video_action_dispatch','job'=>$id],'dispatcher');
rejected(function()use(&$s,$id,$action){worker_update($s,['op'=>'video_action_claim','job'=>$id,'action_id'=>$action['id'],'dispatch_token'=>$action['dispatch_token']],'align');});
$claim=worker_update($s,['op'=>'video_action_claim','job'=>$id,'action_id'=>$action['id'],'dispatch_token'=>$action['dispatch_token']],'upload');
worker_update($s,['op'=>'video_action_finish','job'=>$id,'action_id'=>$action['id'],'lease'=>$claim['action']['lease'],'success'=>true],'upload');
check($s['jobs'][$id]['privacy']==='public','Publication status missing');
check(!str_contains(json_encode(public_state($s)),$claim['action']['lease']),'Publication lease leaked');
echo "Passed photo hold/approval/resume, stale review rejection, title selection, publication gating/deduplication and role/lease fencing.\n";
