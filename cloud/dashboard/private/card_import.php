<?php
declare(strict_types=1);
function card_import_operation(array &$state,array $input,string $role): mixed {
 $id=(string)($input['job']??'');$job=&$state['jobs'][$id];if(!$job)throw new WorkflowConflict('Unknown recording');$op=$input['op'];
 if($op==='card_import_create'&&$role==='dispatcher'){
  if($job['stages']['align']['status']!=='complete'||($job['stages']['align']['result']['transcript_uri']??'')!==$input['alignment_uri'])throw new WorkflowConflict('Wait for completed alignment before importing cards');
  if($job['stages']['plan']['status']!=='pending'&&$job['status']!=='complete')throw new WorkflowConflict('Wait for the current render before revising its cards');
  if(($job['card_import']['request_hash']??'')===$input['request_hash']&&($job['card_import']['alignment_uri']??'')===$input['alignment_uri']&&!in_array($job['card_import']['status']??'',['failed','needs_rebind'],true))return array_intersect_key($job['card_import'],array_flip(['id','status','card_count','spec_uri']));
  if(in_array($job['card_import']['status']??'',['starting','running'],true))throw new WorkflowConflict('A card import is already running');
  $metadata=empty($job['stages']['enrich']['result']['enrichment_uri'])||in_array($job['stages']['enrich']['status'],['starting','running'],true);
  $job['card_import']=['id'=>$input['import_id'],'status'=>'uploading','spec_uri'=>$input['spec_uri'],'alignment_uri'=>$input['alignment_uri'],'request_hash'=>$input['request_hash'],'card_count'=>$input['card_count'],'created_at'=>gmdate('c'),'previous_status'=>$job['status'],'previous_enrich_status'=>$job['stages']['enrich']['status']];
  if($job['status']==='complete')$job['annotation_revision_only']=true;
  if(!$metadata){$job['stages']['enrich']['status']='needs_review';$job['status']='needs_review';}
  event($state,$id,'Card import received: '.$input['card_count'].' cards');return array_intersect_key($job['card_import'],array_flip(['id','status','card_count','spec_uri']));
 }
 $item=&$job['card_import'];if(!$item)throw new WorkflowConflict('No card import');
 if($op==='card_import_cancel'&&$role==='dispatcher'){
  if($item['status']==='complete')throw new WorkflowConflict('These cards are ready for review; select which to show or hide.');
  $complete=($item['previous_status']??'')==='complete';unset($job['card_import']);
  if($complete){$job['status']='complete';$job['stages']['enrich']['status']='complete';unset($job['annotation_revision_only']);}
  elseif(!in_array($job['stages']['enrich']['status'],['starting','running'],true)){$job['stages']['enrich']['status']='needs_review';$job['status']='needs_review';reconcile_reviews($state);}
  else $job['annotation_import_cancelled']=true;
  event($state,$id,'Card import cancelled; existing case work retained');return ['status'=>'cancelled'];
 }
 if($op==='card_import_ready'&&$role==='dispatcher'){
  if($item['id']!==$input['import_id']||$item['request_hash']!==$input['request_hash'])throw new WorkflowConflict('Card import changed');
  if($item['status']==='uploading')$item['status']=empty($job['stages']['enrich']['result']['enrichment_uri'])||in_array($job['stages']['enrich']['status'],['starting','running'],true)?'waiting_for_metadata':'queued';
  return array_intersect_key($item,array_flip(['id','status','card_count']));
 }
 if($op==='card_import_dispatch'&&$role==='dispatcher'){
  if(!work_enabled($state,$job)||$item['status']!=='queued')return null;
  if(($job['stages']['align']['result']['transcript_uri']??'')!==$item['alignment_uri']){$item['status']='failed';$item['error']='Transcript changed; import the revised card file.';return null;}
  $item['status']='starting';$item['dispatch_token']=bin2hex(random_bytes(24));$item['expires']=time()+600;return $item;
 }
 if($role!=='enrich')throw new WorkflowConflict('Card import access denied');
 if($op==='card_import_claim'){
  if($item['status']!=='starting'||$item['id']!==($input['import_id']??'')||!hash_equals($item['dispatch_token']??'',(string)($input['dispatch_token']??'')))return null;
  $item['status']='running';$item['lease']=bin2hex(random_bytes(24));$item['expires']=time()+180;return ['job'=>$job,'import'=>$item];
 }
 if($op==='card_import_finish'&&$item['status']==='complete'&&$item['id']===($input['import_id']??''))return true;
 if($item['status']!=='running'||($item['expires']??0)<=time()||!hash_equals($item['lease']??'',(string)($input['lease']??'')))throw new WorkflowConflict('Stale card import');
 if($op==='card_import_heartbeat'){
  $item['expires']=time()+180;$item['progress']=max($item['progress']??0,min(1,max(0,$input['progress']??0)));
  if(isset($input['prepared_cards'])){if(count($input['prepared_cards'])>$item['card_count']||strlen(json_encode($input['prepared_cards']))>1048576)throw new InvalidArgumentException('Imported card checkpoint is too large');$item['prepared_cards']=$input['prepared_cards'];}
  return true;
 }
 if($op==='card_import_finish'){
  if(($job['stages']['align']['result']['transcript_uri']??'')!==$item['alignment_uri'])throw new WorkflowConflict('Transcript changed during import');
  $review=$job['review'];$review['cards']=$input['cards'];$review['private_notes']=[...($review['private_notes']??[]),...($input['private_notes']??[])];
  review_install($job,$review);unset($job['cards_approved_revision']);
  $job['stages']['enrich']['result']['enrichment_uri']=$input['enrichment_uri'];$job['stages']['enrich']['status']='needs_review';$job['status']='needs_review';
  $item['status']='complete';$item['finished_at']=gmdate('c');event($state,$id,'Imported cards are ready for review');
  unset($job['research_attention']); // The owner supplied a replacement set through the validated import action.
  notify_event($state,$item['id'].'-ready','case_review',$job['review']['id'],$id);
 }elseif($op==='card_import_fail'){$item['status']='failed';$item['error']=mb_substr((string)$input['message'],0,600);event($state,$id,'Card import needs a revised file: '.$item['error']);}
 else throw new WorkflowConflict('Unknown card import operation');
 unset($item['lease'],$item['dispatch_token']);if($item['status']==='complete')unset($item['prepared_cards']);return true;
}
