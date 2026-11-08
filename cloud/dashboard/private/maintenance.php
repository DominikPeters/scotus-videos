<?php
declare(strict_types=1);
/** A separate owner action: upload the finished correction once, as unlisted. */
function upload_corrected_recording(array &$state,string $id):array {
 if(!isset($state['jobs'][$id]))throw new WorkflowConflict('Unknown recording');
 $job=&$state['jobs'][$id];$revision=&$job['render_revision'];
 if(($revision['status']??'')!=='complete')throw new WorkflowConflict('Finish the corrected render first');
 if(!empty($revision['upload_matches_current']))return ['status'=>'complete'];
 if(!empty($revision['upload_requested_at']))return ['status'=>$job['stages']['upload']['status']];
 if($job['status']!=='complete'||$job['stages']['upload']['status']!=='complete')throw new WorkflowConflict('Finish the current upload first');
 foreach(['prepare','enrich','align','plan','render','assemble'] as $name)if($job['stages'][$name]['status']!=='complete')throw new WorkflowConflict('Completed approved inputs are required');
 if(cards_pending($job)||array_filter(array_keys($job['review']['photos']??[]),fn($key)=>empty($job['approved_photos'][$key])))throw new WorkflowConflict('Finish owner review first');
 foreach($job['video_actions']??[] as $action)if(in_array($action['status'],['queued','starting','running'],true))throw new WorkflowConflict('Finish the existing video action first');
 $assembly=$job['stages']['assemble']['result']??[];
 if(empty($assembly['video_uri'])||empty($assembly['sha256'])||($assembly['sha256']??'')===($revision['previous_sha256']??''))throw new WorkflowConflict('A verified corrected MP4 is required');
 $revision['upload_requested_at']=gmdate('c');$revision['upload_sha256']=$assembly['sha256'];
 $job['stages']['upload']=['status'=>'pending','attempt'=>$job['stages']['upload']['attempt']??0,'progress'=>0];
 unset($job['workflow_releases']['upload']);
 $job['status']='queued';$job['run_requested']=true;$job['updated_at']=gmdate('c');
 event($state,$id,'Owner requested a new unlisted upload of the corrected MP4; earlier YouTube upload retained.');
 return ['status'=>'queued'];
}

function rerender_recording(array &$state,array $input,string $role):array {
 if($role!=='dispatcher')throw new WorkflowConflict('Rerender access denied');
 $id=(string)($input['job']??'');if(!isset($state['jobs'][$id]))throw new WorkflowConflict('Unknown recording');
 $job=&$state['jobs'][$id];
 if(($job['render_revision']['status']??'')==='queued')return ['status'=>'queued','version'=>$job['render_revision']['version']];
 if($job['status']!=='complete'||$job['stages']['enrich']['status']!=='complete'||$job['stages']['align']['status']!=='complete')throw new WorkflowConflict('Finish the current recording before requesting a render revision');
 if(($job['chunk_cleanup']['expires']??0)>time())throw new WorkflowConflict('Wait for chunk cleanup before rerendering');
 $previous=$job['stages']['assemble']['result']??[];
 $job['render_revision']=['version'=>($job['render_revision']['version']??0)+1,'status'=>'queued','requested_at'=>gmdate('c'),
  'previous_video_uri'=>$previous['video_uri']??null,'previous_sha256'=>$previous['sha256']??null,
  'existing_youtube_url'=>$job['stages']['upload']['result']['video_url']??null,'upload_matches_current'=>false];
 foreach(['plan','render','assemble'] as $name){$job['stages'][$name]=['status'=>'pending','attempt'=>$job['stages'][$name]['attempt']??0,'progress'=>0];unset($job['workflow_releases'][$name]);}
 unset($job['workflow_release'],$job['chunk_cleanup']);
 $job['status']='queued';$job['run_requested']=true;$job['updated_at']=gmdate('c');
 event($state,$id,'Corrected render queued from the approved inputs; existing YouTube upload retained.');
 return ['status'=>'queued','version'=>$job['render_revision']['version'],'existing_upload_preserved'=>true];
}

function source_refresh_operation(array &$state,array $input,string $role): mixed {
 if($role!=='dispatcher')throw new WorkflowConflict('Source refresh access denied');
 $id=(string)($input['job']??'');$job=&$state['jobs'][$id];if(!$job)throw new WorkflowConflict('Unknown recording');
 if(!empty($job['stages']['upload']['checkpoint'])||$job['stages']['upload']['status']==='complete')return ['status'=>'upload_frozen','message'=>'An existing upload cannot be rewound.'];
 $op=$input['op'];
 if($op==='source_refresh_claim'){
  if(empty($input['manual'])&&($job['maintenance']['retry_after']??0)>time())return null;
  $job['maintenance']=['kind'=>'refresh_sources','status'=>'checking','retry_after'=>time()+3600];return $job;
 }
 if($op==='source_refresh_wait'){$job['maintenance']=['kind'=>'refresh_sources','status'=>'waiting','retry_after'=>time()+300];return true;}
 if($op!=='source_refresh_apply')throw new WorkflowConflict('Unknown source refresh operation');
 if($job['pdf_url']!==$input['expected_pdf']||$job['audio_url']!==$input['expected_audio']||($job['stages']['prepare']['result']['transcript_uri']??null)!==$input['expected_prepared_uri'])return ['status'=>'source_changed','message'=>'Sources changed during the check; check again.'];
 foreach(['pdf_url','audio_url'] as $field){$url=parse_url((string)$input[$field]);if(($url['scheme']??'')!=='https'||!in_array($url['host']??'',['supremecourt.gov','www.supremecourt.gov'],true)||isset($url['user']))throw new InvalidArgumentException('Official Court sources required');}
 if(!preg_match('/^[a-f0-9]{64}$/D',(string)$input['pdf_sha256']))throw new InvalidArgumentException('Invalid transcript checksum');
 if(empty($input['changed'])){$job['pdf_url']=$input['pdf_url'];$job['audio_url']=$input['audio_url'];$job['maintenance']=['kind'=>'refresh_sources','status'=>'current','retry_after'=>time()+3600];return ['status'=>'current','message'=>'The prepared source is current.'];}
 foreach($job['stages'] as $stage)if(in_array($stage['status'],['starting','running'],true)){$job['maintenance']=['kind'=>'refresh_sources','status'=>'waiting','retry_after'=>time()+60];return ['status'=>'waiting_for_workers','message'=>'Source refresh will continue after the current worker finishes.'];}
 if(in_array($job['card_import']['status']??'',['starting','running'],true)){$job['maintenance']=['kind'=>'refresh_sources','status'=>'waiting','retry_after'=>time()+60];return ['status'=>'waiting_for_workers'];}
 if(($job['chunk_cleanup']['expires']??0)>time())return ['status'=>'waiting_for_cleanup'];
 $keep=(string)($input['keep_recovery']??'');
 if($keep!==''){$rec=recovery_lease($state,['recovery'=>$keep,'lease'=>$input['lease']??'']);if($rec['job']!==$id)throw new WorkflowConflict('Wrong source recovery');}
 if(!empty($job['stages']['enrich']['result']['enrichment_uri']))$job['editorial_cache_uri']=$job['stages']['enrich']['result']['enrichment_uri'];
 $job['previous_source']=['pdf_url'=>$job['pdf_url'],'audio_url'=>$job['audio_url'],'prepared_uri'=>$job['stages']['prepare']['result']['transcript_uri']??null];
 $job['pdf_url']=$input['pdf_url'];$job['audio_url']=$input['audio_url'];$job['source_version']=($job['source_version']??1)+1;
 if(isset($job['card_import'])){$job['card_import']['status']='needs_rebind';$job['card_import']['error']='Transcript changed; import the card file updated for this transcript.';}
 foreach($job['stages'] as &$stage)$stage=['status'=>'pending','attempt'=>$stage['attempt']??0,'progress'=>0];unset($stage);
 unset($job['workflow_release'],$job['workflow_releases'],$job['chunk_cleanup']);
 $state['recoveries']??=[];
 foreach($state['recoveries'] as $rid=>&$rec)if($rec['job']===$id&&!in_array($rec['status'],['repaired','cancelled'],true)){
  unset($rec['reusable_release']);
  if($rid===$keep){$rec['retry_requested']=true;$job['stages'][$rec['stage']]['recovery_id']=$rid;}
  else{$rec['status']='cancelled';unset($rec['lease'],$rec['dispatch_token'],$rec['expires']);}
  recovery_log($state,$rid,'system','Official sources changed; preparation and dependent artifacts are regenerating through normal processing.');
 }unset($rec);
 $job['status']='queued';$job['maintenance']=['kind'=>'refresh_sources','status'=>'refreshed','source_version'=>$job['source_version'],'retry_after'=>time()+3600];
 event($state,$id,'Official source refreshed; preparation queued. Existing title, portraits and case research retained.');return ['status'=>'refreshed','source_version'=>$job['source_version']];
}
