<?php
require dirname(__DIR__).'/dashboard/private/state.php';
function check(bool $value,string $message):void {if(!$value)throw new RuntimeException($message);}
$state=initial_state();$job=add_job($state,['docket'=>'25-735','argument_date'=>'2026-10-05','pdf_url'=>'https://www.supremecourt.gov/test.pdf','audio_url'=>'https://www.supremecourt.gov/test.mp3']);$id=$job['id'];
command($state,['command'=>'start','job'=>$id]);
foreach(['prepare','enrich','align','plan'] as $name)$state['jobs'][$id]['stages'][$name]['status']='complete';
$state['jobs'][$id]['stages']['plan']['result']['chunks']=2;
$start=worker_update($state,['op'=>'dispatch','job'=>$id,'stage'=>'render'],'dispatcher');
$request=['job'=>$id,'stage'=>'render','dispatch_token'=>$start['dispatch_token'],'task'=>0];
$first=worker_update($state,['op'=>'claim',...$request,'claim_id'=>str_repeat('a',32)],'render');
$same=worker_update($state,['op'=>'claim',...$request,'claim_id'=>str_repeat('a',32)],'render');
check($first['lease']===$same['lease'],'Lost claim reply acquired another lease');
check(worker_update($state,['op'=>'claim',...$request,'claim_id'=>str_repeat('b',32)],'render')===null,'Concurrent worker took the active task');
worker_update($state,['op'=>'finish',...$request,'lease'=>$first['lease'],'result'=>['sha256'=>'preserved']],'render');
$operation='projects/project/locations/us-central1/operations/owned';
worker_update($state,['op'=>'execution_record','job'=>$id,'stage'=>'render','dispatch_token'=>$start['dispatch_token'],'operation'=>$operation],'dispatcher');
$complete=$state['jobs'][$id]['stages']['render']['tasks'][0];
check(worker_update($state,['op'=>'execution_closed','job'=>$id,'stage'=>'render','operation'=>$operation.'-stale'],'dispatcher')===false,'Stale execution failed a new phase');
worker_update($state,['op'=>'execution_closed','job'=>$id,'stage'=>'render','operation'=>$operation],'dispatcher');
check($state['jobs'][$id]['status']==='failed','Closed execution stayed running');
check($state['jobs'][$id]['stages']['render']['tasks'][0]===$complete,'Completed chunk was altered');
check($state['jobs'][$id]['stages']['render']['tasks'][1]['status']==='failed','Unclaimed task did not fail');
check(count($state['recoveries'])===1,'Recovery was not queued');
worker_update($state,['op'=>'execution_closed','job'=>$id,'stage'=>'render','operation'=>$operation],'dispatcher');check(count($state['recoveries'])===1,'Recovery duplicated');
command($state,['command'=>'retry','job'=>$id]);
check(!isset($state['jobs'][$id]['stages']['render']['cloud_operation']),'Retry retained the old operation');
check($state['jobs'][$id]['stages']['render']['tasks'][0]===$complete,'Retry lost the completed chunk');
check($state['jobs'][$id]['stages']['render']['tasks'][1]['status']==='pending','Missing chunk was not queued');
echo "Passed idempotent claims, closed execution recovery, stale operation fencing and preserved chunks.\n";
