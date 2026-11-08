<?php
require dirname(__DIR__).'/dashboard/private/state.php';
function check(bool $ok,string $message):void{if(!$ok)throw new RuntimeException($message);}
function fixture(array &$s,string $docket):string{
 $j=add_job($s,['docket'=>$docket,'argument_date'=>'2026-11-02','pdf_url'=>'https://www.supremecourt.gov/t.pdf','audio_url'=>'https://www.supremecourt.gov/a.mp3']);$id=$j['id'];
 foreach($s['jobs'][$id]['stages'] as &$stage)$stage['status']='complete';return $id;
}
function incident(array &$s,string $id,string $stage):string{
 $s['jobs'][$id]['status']='failed';$s['jobs'][$id]['stages'][$stage]['status']='failed';
 $rid=recovery_failure($s,$id,$stage,'worker_failed');$s['recoveries'][$rid]['status']='running';$s['recoveries'][$rid]['lease']='lease';$s['recoveries'][$rid]['expires']=time()+180;return $rid;
}
function retry(array &$s,string $rid,string $restart,array $extra=[]):void{
 recovery_operation($s,['op'=>'recovery_retry','recovery'=>$rid,'lease'=>'lease','restart_from'=>$restart,...$extra],'dispatcher');
}
foreach(['align','enrich','plan'] as $failed){
 $s=initial_state();$s['paused']=false;$id=fixture($s,'25-352');$j=&$s['jobs'][$id];
 $j['stages']['enrich']['result']=['enrichment_uri'=>'gs://test/editorial.json'];$j['approved_photos']=['lawyer'=>'approved'];$j['selected_title']='Owner title';$j['cards_approved_revision']='old';$rid=incident($s,$id,$failed);
 $oldRecovery=null;
 if($failed==='align'){$oldRecovery=recovery_failure($s,$id,'enrich','invalid_inputs');$s['recoveries'][$oldRecovery]['status']='queued';}
 retry($s,$rid,'align');
 foreach(['align','enrich','plan','render','assemble','upload'] as $stage)check($j['stages'][$stage]['status']==='pending','Alignment restart left stale '.$stage);
 check(empty($j['stages']['enrich']['result'])&&!isset($j['cards_approved_revision']),'Old annotation approval/result survived realignment');
 check($j['editorial_cache_uri']==='gs://test/editorial.json'&&$j['approved_photos']['lawyer']==='approved'&&$j['selected_title']==='Owner title','Reusable editorial work was lost');
 if($oldRecovery)check($s['recoveries'][$oldRecovery]['status']==='cancelled','Obsolete downstream recovery remained queued');
}
$s=initial_state();$s['paused']=false;$id=fixture($s,'25-352');$j=&$s['jobs'][$id];
$j['stages']['render']['tasks']=[['status'=>'complete','result'=>['video_deleted_at'=>'today']],['status'=>'complete','result'=>['video_uri'=>'healthy','sha256'=>'keep']]];
$j['chunk_cleanup']=['status'=>'complete','deleted_indices'=>[0]];$rid=incident($s,$id,'upload');$before=json_decode(json_encode($s),true);
try{retry($s,$rid,'assemble');throw new RuntimeException('Missing chunk accepted');}catch(RuntimeException $e){check(str_contains($e->getMessage(),'resource reservation'),'Wrong reassembly rejection');}
check($s===$before,'Rejected retry changed state');
$uploadOnly=$before;command($uploadOnly,['command'=>'retry','job'=>$id]);
check($uploadOnly['jobs'][$id]['stages']['render']['status']==='complete','Upload-only retry unnecessarily regenerated deleted chunks');
$healthy=$j['stages']['render']['tasks'][1];retry($s,$rid,'render',['restore_render_chunks'=>true]);
check($j['stages']['render']['tasks'][0]['status']==='pending'&&$j['stages']['render']['tasks'][1]===$healthy,'Restoration failed to preserve healthy chunk');
check(!isset($j['chunk_cleanup'])&&$j['stages']['assemble']['status']==='pending','Old cleanup state survived restoration');
$manual=$before;$manual['jobs'][$id]['stages']['assemble']['status']='failed';command($manual,['command'=>'retry','job'=>$id]);
check($manual['jobs'][$id]['stages']['render']['status']==='pending'&&$manual['jobs'][$id]['stages']['render']['tasks'][1]===$healthy,'Manual retry did not regenerate only missing inputs');
$blocked=$before;$blocked['jobs'][$id]['status']='queued';$blocked['jobs'][$id]['stages']['assemble']['status']='pending';
check(worker_update($blocked,['op'=>'dispatch','job'=>$id,'stage'=>'assemble'],'dispatcher')===null,'Assembly launched with removed inputs');
foreach(['recovery','enrich','photo','statistics'] as $first){
 $s=initial_state();$s['paused']=false;$id=fixture($s,'25-352');$rid=incident($s,$id,'prepare');$s['recoveries'][$rid]['status']='queued';unset($s['recoveries'][$rid]['lease']);
 $eid=fixture($s,'25-5930');$s['jobs'][$eid]['status']='queued';$s['jobs'][$eid]['stages']['enrich']['status']='pending';
 $pid=fixture($s,'25-170');$s['jobs'][$pid]['status']='needs_review';$s['jobs'][$pid]['stages']['enrich']['status']='needs_review';$s['jobs'][$pid]['stages']['plan']['status']='pending';$s['jobs'][$pid]['photo_requests']['photo']=['status'=>'queued'];
 $start=function(string $kind)use(&$s,$id,$rid,$eid,$pid){return match($kind){
  'recovery'=>recovery_operation($s,['op'=>'recovery_dispatch','recovery'=>$rid,'reserve_usd'=>0.1,'seconds'=>600],'dispatcher'),
  'enrich'=>worker_update($s,['op'=>'dispatch','job'=>$eid,'stage'=>'enrich'],'dispatcher'),
  'photo'=>worker_update($s,['op'=>'photo_dispatch','job'=>$pid,'request'=>'photo'],'dispatcher'),
  'statistics'=>statistics_operation($s,['op'=>'stats_dispatch','index_revision'=>'new'],'dispatcher')};};
 check(!empty($start($first)),'First model worker failed to reserve: '.$first);
 foreach(array_diff(['recovery','enrich','photo','statistics'],[$first]) as $second)check($start($second)===null,$first.' and '.$second.' both reserved model access');
 check(empty($s['auth_leases']),'Fixture accidentally tested auth contention instead of dispatch reservation');
 switch($first){
  case 'recovery':$s['recoveries'][$rid]['status']='waiting_for_tests';break;
  case 'enrich':$s['jobs'][$eid]['stages']['enrich']['status']='needs_review';break;
  case 'photo':$s['jobs'][$pid]['photo_requests']['photo']['status']='complete';break;
  case 'statistics':$s['statistics']['status']='idle';break;
 }
 check(!empty($start($first==='recovery'?'enrich':'recovery')),'Finished worker did not release its model reservation');
}
echo "Passed dependency invalidation, removed-chunk restoration and all model-slot reservation orderings.\n";
