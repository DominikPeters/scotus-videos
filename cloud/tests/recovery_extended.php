<?php
require dirname(__DIR__).'/dashboard/private/state.php';
function check($ok,$message){if(!$ok)throw new RuntimeException($message);}
$s=initial_state();$s['paused']=false;$job=add_job($s,['docket'=>'25-498','argument_date'=>'2026-10-06','case_name'=>'Fixture','audio_url'=>'https://www.supremecourt.gov/a.mp3','pdf_url'=>'https://www.supremecourt.gov/t.pdf']);$jid=$job['id'];
foreach(['prepare','enrich','align'] as $name){$s['jobs'][$jid]['stages'][$name]['status']='complete';$s['jobs'][$jid]['stages'][$name]['result']=['value'=>'old'];}
$s['jobs'][$jid]['stages']['enrich']['result']=['enrichment_uri'=>'gs://bucket/editorial.json'];$s['jobs'][$jid]['approved_photos']=['lawyer'=>['id'=>'approved']];$s['jobs'][$jid]['selected_title']='Owner title';$s['jobs'][$jid]['status']='failed';$s['jobs'][$jid]['stages']['plan']['status']='failed';
$rid=recovery_failure($s,$jid,'plan','invalid_inputs');$s['recoveries'][$rid]['status']='running';$s['recoveries'][$rid]['expires']=time()+180;$s['recoveries'][$rid]['lease']='lease';
$f=json_decode(json_encode($s),true);$f['jobs'][$jid]['stages']['upload']['checkpoint']=['video_id'=>'saved-video'];
try{recovery_operation($f,['op'=>'recovery_retry','recovery'=>$rid,'lease'=>'lease','restart_from'=>'prepare'],'dispatcher');throw new RuntimeException('Existing upload rewound');}catch(Throwable $e){check($e->getMessage()!=='Existing upload rewound','Existing upload rewind accepted');}
recovery_operation($s,['op'=>'recovery_retry','recovery'=>$rid,'lease'=>'lease','restart_from'=>'prepare'],'dispatcher');
check($s['jobs'][$jid]['stages']['prepare']['status']==='pending','Preparation was not restarted');check(empty($s['jobs'][$jid]['stages']['align']['result']),'Stale aligned artifact retained');
check($s['jobs'][$jid]['approved_photos']['lawyer']['id']==='approved','Photo approvals lost');check($s['jobs'][$jid]['selected_title']==='Owner title','Selected title lost');check($s['jobs'][$jid]['editorial_cache_uri']==='gs://bucket/editorial.json','Editorial cache lost');
$key=str_repeat('a',64);$s['recoveries'][$rid]['actions'][$key]=['kind'=>'tests','status'=>'recorded','result'=>['report_uri'=>'gs://bucket/report']];
recovery_operation($s,['op'=>'recovery_wait','recovery'=>$rid,'lease'=>'lease','action_id'=>$key],'recovery');
recovery_operation($s,['op'=>'recovery_finish','recovery'=>$rid,'lease'=>'lease','status'=>'waiting_for_tests','summary'=>'Checks queued.'],'recovery');
check($s['recoveries'][$rid]['status']==='waiting_for_tests','Worker did not yield for checks');
recovery_operation($s,['op'=>'recovery_tests_ready','recovery'=>$rid,'action_id'=>$key,'passed'=>true,'report'=>['passed'=>true]],'dispatcher');check($s['recoveries'][$rid]['status']==='queued','Checks did not queue an automatic continuation');
$s['recoveries'][$rid]['status']='cancelled';check(recovery_operation($s,['op'=>'recovery_tests_ready','recovery'=>$rid,'action_id'=>$key,'passed'=>true],'dispatcher')===false,'Cancelled recovery resumed');
echo "Passed upstream invalidation, preserved approvals/editorial, upload rewind rejection and async check continuation/cancellation.\n";
