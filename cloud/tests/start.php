<?php
// In-memory only: no media, cloud execution or notifications.
require dirname(__DIR__).'/dashboard/private/state.php';
function check(bool $value,string $message): void {if(!$value)throw new RuntimeException($message);}
$state=initial_state();
$input=['argument_date'=>'2026-10-05','pdf_url'=>'https://www.supremecourt.gov/test.pdf','audio_url'=>'https://www.supremecourt.gov/test.mp3'];
$first=add_job($state,['docket'=>'25-735',...$input])['id'];
$other=add_job($state,['docket'=>'25-170',...$input])['id'];
command($state,['command'=>'start','job'=>$first]);
$events=count($state['events']);command($state,['command'=>'start','job'=>$first]);
check(count($state['events'])===$events,'Duplicate Start added an event');
check($state['paused']===true,'Start enabled automatic work');
check(worker_update($state,['op'=>'discovery_claim'],'dispatcher')===false,'Start enabled discovery');
check(worker_update($state,['op'=>'dispatch','job'=>$other,'stage'=>'prepare'],'dispatcher')===null,'Unselected recording started');
foreach(['prepare','align','enrich','plan','render','assemble','upload'] as $name){
    if($name==='render')$state['jobs'][$first]['stages']['plan']['result']['chunks']=2;
    $claim=worker_update($state,['op'=>'dispatch','job'=>$first,'stage'=>$name],'dispatcher');
    check(!empty($claim['dispatch_token']),'Selected recording stopped at '.$name);
    check(worker_update($state,['op'=>'dispatch','job'=>$first,'stage'=>$name],'dispatcher')===null,'Duplicate dispatch started '.$name);
    $state['jobs'][$first]['stages'][$name]['status']='complete';
}
// A failed manually started recording can repair and resume while paused.
$state['jobs'][$first]['status']='failed';$state['jobs'][$first]['stages']['upload']['status']='failed';
$rid=recovery_failure($state,$first,'upload','worker_failed');
$claim=recovery_operation($state,['op'=>'recovery_dispatch','recovery'=>$rid,'reserve_usd'=>0.1,'seconds'=>600],'dispatcher');
check(!empty($claim['dispatch_token']),'Selected recording repair blocked');
$state['jobs'][$other]['status']='failed';$state['jobs'][$other]['stages']['prepare']['status']='failed';
$otherRid=recovery_failure($state,$other,'prepare','worker_failed');
check(recovery_operation($state,['op'=>'recovery_dispatch','recovery'=>$otherRid,'reserve_usd'=>0.1,'seconds'=>600],'dispatcher')===null,'Unselected repair started');
command($state,['command'=>'retry','job'=>$first]);
check(work_enabled($state,$state['jobs'][$first]),'Retry lost explicit start request');
command($state,['command'=>'cancel','job'=>$first]);command($state,['command'=>'retry','job'=>$first]);
check(!work_enabled($state,$state['jobs'][$first]),'Cancellation did not revoke start request');
$state['jobs'][$first]['status']='needs_review';
try{command($state,['command'=>'start','job'=>$first]);throw new RuntimeException('Start bypassed review');}catch(InvalidArgumentException $expected){}
echo "Passed per-recording Start, all-stage continuation, discovery isolation, dispatch idempotency, repair gating and cancellation.\n";
