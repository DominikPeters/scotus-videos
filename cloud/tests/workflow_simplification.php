<?php
require dirname(__DIR__).'/dashboard/private/state.php';
function check(bool $value,string $message):void{if(!$value)throw new RuntimeException($message);}
function rejected(callable $fn):void{try{$fn();}catch(Throwable $e){return;}throw new RuntimeException('Stale operation accepted');}
function fixture():array{
 $s=initial_state();$s['paused']=false;$j=add_job($s,['docket'=>'25-352','argument_date'=>'2026-11-02','case_name'=>'Younge','pdf_url'=>'https://www.supremecourt.gov/old.pdf','audio_url'=>'https://www.supremecourt.gov/audio.mp3']);$id=$j['id'];
 $s['jobs'][$id]['stages']['prepare']['status']='complete';$s['jobs'][$id]['stages']['prepare']['result']=['transcript_uri'=>'gs://owned/prepared.json'];$s['jobs'][$id]['stages']['align']=['status'=>'complete','result'=>['transcript_uri'=>'gs://owned/aligned.json']];
 return [$s,$id];
}
[$s,$id]=fixture();$j=&$s['jobs'][$id];$j['review']=['id'=>'review','revision'=>str_repeat('a',64),'card_revision'=>str_repeat('b',64),'cards'=>[['id'=>'one','cue'=>['text'=>'Approved']]],'titles'=>[['title'=>'First']],'photos'=>['a'=>['name'=>'A','candidates'=>[]],'b'=>['name'=>'B','candidates'=>[]]]];$j['cards_approved_revision']=str_repeat('b',64);review_versions($j);
check($j['review']['version']===1&&$j['cards_approved_revision']===1,'Legacy approval was lost');
review_touch($j,'photo','a');review_check($j,['version'=>1],'cards');review_check($j,['version'=>1],'photo','b');review_check($j,['version'=>1],'title');
rejected(function()use(&$j){review_check($j,['version'=>1],'photo','a');});
$incoming=$j['review'];$incoming['cards'][0]['cue']['text']='Changed';review_install($j,$incoming);check(!isset($j['cards_approved_revision'])&&$j['review']['card_revision']===2,'Changed card retained approval');

// One checkpoint, compare-and-swap writes, and idempotence after a lost reply.
$j['stages']['enrich']=['status'=>'running','lease'=>['token'=>'lease','expires'=>time()+180]];
$base=['job'=>$id,'lease'=>'lease'];$write=['op'=>'research_save',...$base,'version'=>0,'operation_id'=>str_repeat('a',32),'checkpoint'=>['events'=>array_fill(0,120,['note'=>'retained'])]];
check(worker_update($s,$write,'enrich')['version']===1,'First checkpoint failed');check(worker_update($s,$write,'enrich')['version']===1,'Lost reply duplicated checkpoint');
rejected(function()use(&$s,$write){worker_update($s,[...$write,'operation_id'=>str_repeat('b',32)],'enrich');});
check(count($j['card_research']['checkpoint']['events'])===100,'History grew beyond the current checkpoint');check(!isset(public_state($s)['jobs'][$id]['card_research']),'Research leaked into every dashboard response');

// Commit intent before launching; confirm absence twice before returning to queue.
[$s,$id]=fixture();$j=&$s['jobs'][$id];$j['stages']['align']=['status'=>'pending','attempt'=>0];$claim=worker_update($s,['op'=>'dispatch','job'=>$id,'stage'=>'align'],'dispatcher');$owner=['kind'=>'stage','job'=>$id,'stage'=>'align'];$input=['op'=>'launch_prepare','owner'=>$owner,'cloud_job'=>'scotus-video-align','dispatch_token'=>$claim['dispatch_token']];
$intent=worker_update($s,$input,'dispatcher');check($intent['claimed']&&$intent['id']==='run-1','Launch intent missing');check(!worker_update($s,$input,'dispatcher')['claimed'],'Repeated request could duplicate a launch');
$j['stages']['align']['_launch']['created_at']=time()-400;
worker_update($s,['op'=>'launch_missing','owner'=>$owner,'attempt'=>'run-1'],'dispatcher');check($j['stages']['align']['status']==='starting','One missing listing rewound an execution');
$j['stages']['align']['_launch']['last_checked_at']=time()-31;worker_update($s,['op'=>'launch_missing','owner'=>$owner,'attempt'=>'run-1'],'dispatcher');check($j['stages']['align']['status']==='pending'&&empty($s['recoveries']),'Unconfirmed launch spent a repair turn');

// A changed official input is ordinary regeneration, retaining independent work.
[$s,$id]=fixture();$j=&$s['jobs'][$id];$j['status']='failed';$j['stages']['align']['status']='failed';$rid=recovery_failure($s,$id,'align','alignment_review');$j['selected_title']='Owner title';$j['approved_photos']=['person'=>['id'=>'portrait']];$j['card_research']=['version'=>7,'checkpoint'=>['sources'=>['s'=>'saved']]];
$input=['op'=>'source_refresh_apply','job'=>$id,'expected_pdf'=>$j['pdf_url'],'expected_audio'=>$j['audio_url'],'expected_prepared_uri'=>'gs://owned/prepared.json','pdf_url'=>'https://www.supremecourt.gov/new.pdf','audio_url'=>$j['audio_url'],'pdf_sha256'=>str_repeat('c',64),'changed'=>true];
worker_update($s,$input,'dispatcher');check($j['stages']['prepare']['status']==='pending'&&$j['status']==='queued','Source refresh failed to restart preparation');check($j['selected_title']==='Owner title'&&$j['approved_photos']['person']['id']==='portrait'&&$j['card_research']['version']===7,'Source refresh discarded independent work');check($s['recoveries'][$rid]['status']==='cancelled'&&$s['recoveries'][$rid]['turns']===0,'Source refresh launched code repair');

// Administrative setup does not consume a reasoning turn.
[$s,$id]=fixture();$s['jobs'][$id]['status']='failed';$s['jobs'][$id]['stages']['align']['status']='failed';$rid=recovery_failure($s,$id,'align','worker_failed');$d=recovery_operation($s,['op'=>'recovery_dispatch','recovery'=>$rid,'reserve_usd'=>0.1,'seconds'=>720],'dispatcher');$claim=recovery_operation($s,['op'=>'recovery_claim','recovery'=>$rid,'dispatch_token'=>$d['dispatch_token']],'recovery');$base=['recovery'=>$rid,'lease'=>$claim['recovery']['lease']];check($s['recoveries'][$rid]['turns']===0,'Starting a process consumed reasoning');
recovery_operation($s,['op'=>'recovery_turn_begin',...$base],'recovery');recovery_operation($s,['op'=>'recovery_turn_begin',...$base],'recovery');check($s['recoveries'][$rid]['turns']===1,'Reasoning start was not idempotent');
// Imported previews remain unapproved until an owner selects the actual new set.
[$s,$id]=fixture();$j=&$s['jobs'][$id];$j['status']='needs_review';$j['stages']['enrich']=['status'=>'needs_review','result'=>['enrichment_uri'=>'gs://owned/base.json']];
$j['review']=['id'=>'review','revision'=>str_repeat('a',64),'titles'=>[['title'=>'Owner title']],'photos'=>[],'cards'=>[]];$j['selected_title']='Owner title';
$create=['op'=>'card_import_create','job'=>$id,'import_id'=>'cards-one','spec_uri'=>'gs://owned/reviews/'.$id.'/imports/cards-one.json','request_hash'=>str_repeat('b',64),'alignment_uri'=>'gs://owned/aligned.json','card_count'=>1];
$intent=worker_update($s,$create,'dispatcher');check($intent['status']==='uploading','Import did not persist intent before upload');check(worker_update($s,$create,'dispatcher')['id']==='cards-one','Upload acknowledgement loss created another import');
worker_update($s,['op'=>'card_import_ready','job'=>$id,'import_id'=>'cards-one','request_hash'=>str_repeat('b',64)],'dispatcher');
$dispatch=worker_update($s,['op'=>'card_import_dispatch','job'=>$id],'dispatcher');$claim=worker_update($s,['op'=>'card_import_claim','job'=>$id,'import_id'=>'cards-one','dispatch_token'=>$dispatch['dispatch_token']],'enrich');
worker_update($s,['op'=>'card_import_finish','job'=>$id,'lease'=>$claim['import']['lease'],'enrichment_uri'=>'gs://owned/new.json','cards'=>[['id'=>'one','visual_checked'=>false,'owner_review_required'=>true,'cue'=>['text'=>'Actual rendered content']]],'private_notes'=>[]],'enrich');
check(cards_pending($j)&&$j['status']==='needs_review','Import invented owner visual approval');check($j['selected_title']==='Owner title','Import overwrote title selection');
review_command($s,['job'=>$id,'version'=>$j['review']['versions']['cards'],'command'=>'cards','selections'=>['one'=>true]]);
check(!cards_pending($j)&&$j['stages']['enrich']['status']==='pending','Owner approval did not resume finalization');
// A deployment hold does not change the owner's pause preference or allow a launcher through.
[$s,$id]=fixture();$s['paused']=true;worker_update($s,['op'=>'deployment_hold','release_id'=>'worker-test'],'dispatcher');
check(!work_enabled($s,['run_requested'=>true]),'Manual launch bypassed deployment hold');
check(worker_update($s,['op'=>'stats_dispatch','index_revision'=>'x'],'dispatcher')===null,'Statistics bypassed hold');
worker_update($s,['op'=>'deployment_release','release_id'=>'worker-test'],'dispatcher');check($s['paused']===true,'Deployment undid owner pause');
// Deployment owns compatibility migration; stale code cannot be dispatched into a new image.
worker_update($s,['op'=>'deployment_hold','release_id'=>'worker-test'],'dispatcher');$old=['uri'=>'gs://owned/old','sha256'=>str_repeat('a',64),'release_id'=>'worker-old'];$new=['uri'=>'gs://owned/releases/worker-test/compatibility/one/source.json','sha256'=>str_repeat('b',64),'release_id'=>'worker-test'];
$s['jobs'][$id]['workflow_releases']['align']=$old;$s['reusable_repairs']['worker-old']['align']=$old;
worker_update($s,['op'=>'deployment_rebase','release_id'=>'worker-test','replacements'=>[$old['uri'].'#'.$old['sha256']=>$new]],'dispatcher');
check($s['jobs'][$id]['workflow_releases']['align']['release_id']==='worker-test'&&isset($s['reusable_repairs']['worker-test']['align']),'Tested repair was not migrated');
worker_update($s,['op'=>'deployment_rebase','release_id'=>'worker-test','replacements'=>[$new['uri'].'#'.$new['sha256']=>null]],'dispatcher');
check(empty($s['jobs'][$id]['workflow_releases'])&&isset($s['jobs'][$id]['previous_workflow_releases']['align']),'Superseded patch could launch or saved work disappeared');

// A closed render resumes unfinished tasks; an uncertain upload cannot create another video.
[$s,$id]=fixture();$j=&$s['jobs'][$id];$operation='projects/project/locations/us-central1/operations/owned';
$j['status']='running';$j['stages']['render']=['status'=>'running','cloud_operation'=>$operation,'_launch'=>['id'=>'run-1'],'tasks'=>[['status'=>'complete','result'=>['uri'=>'saved']],['status'=>'running','lease'=>['token'=>'lost']]]];
worker_update($s,['op'=>'execution_closed','job'=>$id,'stage'=>'render','operation'=>$operation],'dispatcher');
check($j['stages']['render']['status']==='pending'&&$j['stages']['render']['tasks'][0]['result']['uri']==='saved'&&$j['stages']['render']['tasks'][1]['status']==='pending','Interrupted render lost finished work');
$j['status']='running';$j['stages']['upload']=['status'=>'running','cloud_operation'=>$operation,'_launch'=>['id'=>'run-2'],'checkpoint'=>['creation_pending'=>true]];
worker_update($s,['op'=>'execution_closed','job'=>$id,'stage'=>'upload','operation'=>$operation],'dispatcher');
check($j['stages']['upload']['status']==='failed'&&$j['stages']['upload']['error']==='upload_uncertain','Uncertain video creation was retried');

// Browser responses do not expose import inputs, leases or launch bookkeeping.
$j['card_import']=['id'=>'cards-test','status'=>'running','card_count'=>2,'lease'=>'private','dispatch_token'=>'private','request_hash'=>'internal','spec_uri'=>'gs://owned/input','prepared_cards'=>[['id'=>'large']]];
$j['stages']['render']['_launch']=['id'=>'run-1','token_hash'=>'private'];
$view=public_state($s);check(!isset($view['jobs'][$id]['card_import']['lease'])&&!isset($view['jobs'][$id]['card_import']['spec_uri'])&&!isset($view['jobs'][$id]['stages']['render']['_launch']),'Private execution bookkeeping leaked');
check(isset(public_state($s,true)['jobs'][$id]['stages']['render']['_launch']['id']),'Dispatcher lost its durable receipt');
echo "Passed independent review versions, checkpoint CAS, durable launches, source regeneration, reasoning accounting, imported-card review and deployment holds.\n";
