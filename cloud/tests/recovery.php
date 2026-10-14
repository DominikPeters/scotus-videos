<?php
// In-memory recovery state only. No dashboard, cloud job or notification is called.
require dirname(__DIR__).'/dashboard/private/state.php';
function check(bool $value,string $message): void { if (!$value) throw new RuntimeException($message); }
function rejected(callable $callback): void { try {$callback();}catch(Throwable $error){return;}throw new RuntimeException('Invalid operation accepted'); }
$state=initial_state();$state['paused']=false;
$job=add_job($state,['docket'=>'25-735','argument_date'=>'2026-10-05','case_name'=>'Test fixture',
    'pdf_url'=>'https://www.supremecourt.gov/test.pdf','audio_url'=>'https://www.supremecourt.gov/test.mp3']);
$jid=$job['id'];$state['jobs'][$jid]['status']='failed';$state['jobs'][$jid]['stages']['prepare']['status']='failed';
$rid=recovery_failure($state,$jid,'prepare','invalid_inputs',['fingerprint'=>str_repeat('a',64),'message'=>'Changed PDF layout']);
check(recovery_failure($state,$jid,'prepare','invalid_inputs',['fingerprint'=>str_repeat('a',64)])===$rid,'Failure was not deduplicated');
$dispatch=recovery_operation($state,['op'=>'recovery_dispatch','recovery'=>$rid,'reserve_usd'=>0.1,'seconds'=>600],'dispatcher');
$claimInput=['op'=>'recovery_claim','recovery'=>$rid,'dispatch_token'=>$dispatch['dispatch_token'],'claim_id'=>str_repeat('c',32)];
$claim=recovery_operation($state,$claimInput,'recovery');
check(recovery_operation($state,$claimInput,'recovery')['recovery']['lease']===$claim['recovery']['lease'],'Lost recovery claim reply changed its lease');
check(recovery_operation($state,[...$claimInput,'claim_id'=>str_repeat('d',32)],'recovery')===null,'Different recovery claimant acquired an active lease');
$auth=worker_update($state,['op'=>'auth_claim','name'=>'codex','claim_id'=>str_repeat('e',32)],'recovery');
check(worker_update($state,['op'=>'auth_claim','name'=>'codex','claim_id'=>str_repeat('e',32)],'recovery')===$auth,'Lost auth claim reply abandoned the credential lease');
check(worker_update($state,['op'=>'auth_claim','name'=>'codex','claim_id'=>str_repeat('f',32)],'recovery')===null,'Concurrent auth claimant got the credential lease');
worker_update($state,['op'=>'auth_release','name'=>'codex','token'=>$auth],'recovery');
$request=['recovery'=>$rid,'lease'=>$claim['recovery']['lease']];
rejected(function() use (&$state,$request) {recovery_operation($state,['op'=>'recovery_log',...$request,'kind'=>'note','message'=>'No access'],'upload');});
rejected(function() use (&$state,$request) {recovery_operation($state,['op'=>'recovery_check',...$request,'lease'=>'stale'],'recovery');});
recovery_operation($state,['op'=>'recovery_log',...$request,'kind'=>'diagnosis','message'=>'The appearances header moved to a second line.'],'recovery');
rejected(function() use (&$state,$request) {recovery_operation($state,['op'=>'recovery_finish',...$request,'status'=>'repaired','summary'=>'Claimed repair without retry.'],'recovery');});
recovery_operation($state,['op'=>'recovery_question',...$request,'question_id'=>'source-choice','message'=>'Which source should be used?',
    'options'=>[['id'=>'official','label'=>'Official transcript','private_effect'=>'Keep official text.']]],'recovery');
// Pending questions force needs_input even if the model suggests another status.
recovery_operation($state,['op'=>'recovery_finish',...$request,'status'=>'unresolved','summary'=>'The source choice needs your input.'],'recovery');
check($state['recoveries'][$rid]['status']==='needs_input','Question did not hold the recovery');
$answer=['recovery'=>$rid,'question'=>'source-choice','revision'=>$state['recoveries'][$rid]['input_revision'],'choice'=>'official'];
rejected(function() use (&$state,$answer) {recovery_answer($state,[...$answer,'revision'=>'stale']);});
recovery_answer($state,$answer);
check($state['recoveries'][$rid]['status']==='queued','Answer did not queue continuation');
rejected(function() use (&$state,$answer) {recovery_answer($state,$answer);});
check(!str_contains(json_encode(public_state($state)),$claim['recovery']['lease']),'Lease leaked to the dashboard');
check(count($state['recoveries'][$rid]['log'])>=4,'Explanatory log was not persisted');
$budget=initial_state();check(recovery_budget($budget,'first',0.7,600),'Valid reservation rejected');
check(recovery_budget($budget,'first',0.7,600),'Idempotent reservation rejected');
check(!recovery_budget($budget,'second',0.4,600),'Daily budget exceeded');
rejected(function() use (&$budget) {recovery_budget($budget,'invalid',-1,600);});
// Successful retries close every inactive waiting state, without spending more.
foreach(['waiting_for_resource','waiting_for_stage','queued','unresolved','needs_input'] as $status){
    $fixture=$state;$fixture['recoveries'][$rid]['status']=$status;$fixture['recoveries'][$rid]['retry_requested']=true;
    $fixture['jobs'][$jid]['status']='running';$fixture['jobs'][$jid]['stages']['prepare']['status']='complete';
    $fixture['jobs'][$jid]['stages']['prepare']['finished_at']='2026-10-12T22:21:07+00:00';
    $fixture['recoveries'][$rid]['questions']['obsolete']=['status'=>'pending','message'=>'Old source choice'];
    $reservations=$fixture['repair_budget'];reconcile_recoveries($fixture);
    check($fixture['recoveries'][$rid]['status']==='repaired','Completed retry retained '.$status);
    check($fixture['recoveries'][$rid]['questions']['obsolete']['status']==='dismissed','Obsolete question still asks for an answer');
    check($fixture['recoveries'][$rid]['finished_at']==='2026-10-12T22:21:07+00:00','Completion time was not preserved');
    check($fixture['repair_budget']===$reservations,'Completion changed resource accounting');
    $logs=count($fixture['recoveries'][$rid]['log']);reconcile_recoveries($fixture);
    check(count($fixture['recoveries'][$rid]['log'])===$logs,'Reconciliation duplicated success logs');
}
// A submitted retry is waiting for its phase, rather than another cloud resource.
$fixture=$state;$fixture['recoveries'][$rid]['status']='waiting_for_resource';$fixture['recoveries'][$rid]['retry_requested']=true;
$fixture['jobs'][$jid]['status']='running';$fixture['jobs'][$jid]['stages']['prepare']['status']='running';
reconcile_recoveries($fixture);check($fixture['recoveries'][$rid]['status']==='waiting_for_stage','Queued retry mislabeled as a resource wait');
// A failed phase, superseded recovery or operator stop is not called repaired.
foreach(['failed','superseded','cancelled'] as $mode){
    $fixture=$state;$fixture['recoveries'][$rid]['status']=$mode==='cancelled'?'cancelled':'waiting_for_resource';
    $fixture['jobs'][$jid]['stages']['prepare']['status']=$mode==='failed'?'failed':'complete';
    if($mode==='superseded')$fixture['jobs'][$jid]['stages']['prepare']['recovery_id']='newer-recovery';
    reconcile_recoveries($fixture);check($fixture['recoveries'][$rid]['status']!=='repaired','Invalid recovery marked repaired: '.$mode);
}
// A worker may finish its checkpoint/log after the phase passes; its final result
// is then resolved even when it returns the old waiting_for_resource enum.
$fixture=$state;$fixture['recoveries'][$rid]['status']='running';$fixture['recoveries'][$rid]['expires']=time()+180;
$fixture['recoveries'][$rid]['lease']='worker-lease';$fixture['recoveries'][$rid]['retry_requested']=true;
$fixture['jobs'][$jid]['status']='running';$fixture['jobs'][$jid]['stages']['prepare']['status']='complete';
reconcile_recoveries($fixture);check($fixture['recoveries'][$rid]['status']==='running','Active checkpoint worker lost its lease early');
$done=recovery_operation($fixture,['op'=>'recovery_finish','recovery'=>$rid,'lease'=>'worker-lease','status'=>'waiting_for_resource','summary'=>'The phase checks passed.'],'recovery');
check($done['status']==='repaired','Finished worker did not return its resolved state');
$fixture=$state;command($fixture,['command'=>'retry','job'=>$jid]);
$fixture['recoveries'][$rid]['status']='waiting_for_resource';$fixture['recoveries'][$rid]['retry_requested']=true;
$started=worker_update($fixture,['op'=>'dispatch','job'=>$jid,'stage'=>'prepare'],'dispatcher');
$claimed=worker_update($fixture,['op'=>'claim','job'=>$jid,'stage'=>'prepare','dispatch_token'=>$started['dispatch_token']],'prepare');
worker_update($fixture,['op'=>'finish','job'=>$jid,'stage'=>'prepare','dispatch_token'=>$started['dispatch_token'],'lease'=>$claimed['lease'],'result'=>[]],'prepare');
check($fixture['recoveries'][$rid]['status']==='repaired','Phase finish did not immediately close recovery');
// General fixes become defaults only after the affected phase actually passes.
$fixture=$state;$base=str_repeat('a',64);$pointer=['uri'=>'gs://private/tested-fix.json','sha256'=>str_repeat('b',64),'baseline_sha256'=>$base,'stages'=>['prepare'],'reason'=>'Input-independent parser fix','test_report_uri'=>'gs://private/tests/passed.json'];
$fixture['recoveries'][$rid]['status']='waiting_for_resource';$fixture['recoveries'][$rid]['reusable_release']=$pointer;
reconcile_recoveries($fixture);check(empty($fixture['reusable_repairs']),'Unfinished repair became a default');
$fixture['jobs'][$jid]['status']='running';$fixture['jobs'][$jid]['stages']['prepare']['status']='complete';reconcile_recoveries($fixture);
check($fixture['reusable_repairs'][$base]['prepare']['uri']===$pointer['uri'],'Validated general repair was not persisted');
$new=add_job($fixture,['docket'=>'25-170','argument_date'=>'2026-10-05','pdf_url'=>'https://www.supremecourt.gov/test.pdf','audio_url'=>'https://www.supremecourt.gov/test.mp3']);
$claim=worker_update($fixture,['op'=>'dispatch','job'=>$new['id'],'stage'=>'prepare','baseline_sha256'=>$base],'dispatcher');check($claim['workflow_release']['uri']===$pointer['uri'],'Future job did not inherit the validated default');
$other=add_job($fixture,['docket'=>'25-171','argument_date'=>'2026-10-05','pdf_url'=>'https://www.supremecourt.gov/test.pdf','audio_url'=>'https://www.supremecourt.gov/test.mp3']);
$claim=worker_update($fixture,['op'=>'dispatch','job'=>$other['id'],'stage'=>'prepare','baseline_sha256'=>str_repeat('c',64)],'dispatcher');check($claim['workflow_release']===null,'Default crossed immutable source versions');
echo "Passed failure deduplication, role/lease fencing, private explanatory logs, async answers, replay rejection and daily reservations.\n";
echo "Passed completed-phase recovery closure, waiting-state normalization, obsolete questions, preserved reservations, supersession and active checkpoint fencing.\n";
