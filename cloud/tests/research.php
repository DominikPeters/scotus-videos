<?php
require dirname(__DIR__).'/dashboard/private/state.php';
function check(bool $ok,string $message):void{if(!$ok)throw new RuntimeException($message);}
$s=initial_state();$j=add_job($s,['docket'=>'25-735','argument_date'=>'2026-10-05','audio_url'=>'https://www.supremecourt.gov/a.mp3','pdf_url'=>'https://www.supremecourt.gov/t.pdf']);$id=$j['id'];command($s,['command'=>'start','job'=>$id]);
$d=worker_update($s,['op'=>'dispatch','job'=>$id,'stage'=>'prepare'],'dispatcher');$base=['job'=>$id,'stage'=>'prepare','dispatch_token'=>$d['dispatch_token']];$c=worker_update($s,['op'=>'claim',...$base],'prepare');
$f=['op'=>'finish',...$base,'lease'=>$c['lease'],'result'=>['transcript_uri'=>'gs://bucket/prepared.json','duration_seconds'=>6100],'continue_enrich'=>true,'handoff_id'=>str_repeat('a',32)];
check(worker_update($s,$f,'prepare')['next']===null,'Preparation bypassed alignment through handoff');
check(worker_update($s,$f,'prepare')['next']===null,'Lost handoff reply launched blocked enrichment');
check($s['jobs'][$id]['stages']['enrich']['attempt']===0,'Blocked enrichment consumed an attempt');
check(worker_update($s,['op'=>'dispatch','job'=>$id,'stage'=>'enrich'],'dispatcher')===null,'Pending alignment allowed enrichment');
$ad=worker_update($s,['op'=>'dispatch','job'=>$id,'stage'=>'align'],'dispatcher');$al=['job'=>$id,'stage'=>'align','dispatch_token'=>$ad['dispatch_token']];$ac=worker_update($s,['op'=>'claim',...$al],'align');
check(worker_update($s,['op'=>'dispatch','job'=>$id,'stage'=>'enrich'],'dispatcher')===null,'Running alignment allowed enrichment');
$failed=$s;worker_update($failed,['op'=>'fail',...$al,'lease'=>$ac['lease'],'error'=>'alignment_review'],'align');
check(worker_update($failed,['op'=>'dispatch','job'=>$id,'stage'=>'enrich'],'dispatcher')===null,'Failed alignment allowed enrichment');
check($failed['jobs'][$id]['stages']['enrich']['status']==='pending','Dependency failure changed pending enrichment');
check(count($failed['recoveries'])===1&&array_values($failed['recoveries'])[0]['stage']==='align','Dependency failure created downstream recovery');
command($failed,['command'=>'retry','job'=>$id]);check($failed['jobs'][$id]['stages']['enrich']['attempt']===0,'Retry spent an enrichment attempt');
check(worker_update($failed,['op'=>'dispatch','job'=>$id,'stage'=>'enrich'],'dispatcher')===null,'Retry bypassed alignment');
// A launch already reserved by an old controller must defer without failing.
$stale=$s;$stale['jobs'][$id]['stages']['enrich']['status']='starting';$stale['jobs'][$id]['stages']['enrich']['dispatch_token']=str_repeat('b',48);
check(worker_update($stale,['op'=>'claim','job'=>$id,'stage'=>'enrich','dispatch_token'=>str_repeat('b',48)],'enrich')===null,'Stale launch claimed blocked enrichment');
check($stale['jobs'][$id]['stages']['enrich']['status']==='pending'&&empty($stale['recoveries']),'Stale launch created a false failure');
worker_update($s,['op'=>'finish',...$al,'lease'=>$ac['lease'],'result'=>['transcript_uri'=>'gs://bucket/aligned.json']],'align');
$ed=worker_update($s,['op'=>'dispatch','job'=>$id,'stage'=>'enrich'],'dispatcher');check(!empty($ed),'Completed alignment did not release enrichment');
$en=['job'=>$id,'stage'=>'enrich','dispatch_token'=>$ed['dispatch_token']];$ec=worker_update($s,['op'=>'claim',...$en],'enrich');
check(worker_update($s,['op'=>'dispatch','job'=>$id,'stage'=>'plan'],'dispatcher')===null,'Planning bypassed enrichment');
worker_update($s,['op'=>'finish',...$en,'lease'=>$ec['lease'],'result'=>[]],'enrich');
check(worker_update($s,['op'=>'dispatch','job'=>$id,'stage'=>'plan'],'dispatcher')!==null,'Completed dependencies did not enable planning');
echo "Research checks passed: dependency-gated dispatch/handoff/claim, failure isolation and automatic release.\n";
