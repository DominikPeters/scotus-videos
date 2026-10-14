<?php
function chunk_cleanup_operation(array &$state,array $input,string $role):mixed{
 if($role!=='dispatcher')throw new RuntimeException('Cleanup requires dispatcher');
 $id=(string)($input['job'] ?? '');$job=&$state['jobs'][$id];if(!$job)throw new InvalidArgumentException('Unknown recording');
 $assembled=$job['stages']['assemble'];$tasks=$job['stages']['render']['tasks'] ?? [];
 if($assembled['status']!=='complete'||$job['stages']['render']['status']!=='complete'||!$tasks)return null;
 $uri=$assembled['result']['video_uri'] ?? '';if(!$uri||empty($assembled['result']['sha256'])||(empty($assembled['result']['verification'])&&!(($job['stages']['upload']['status'] ?? '')==='complete'&&!empty($job['stages']['upload']['result']['postprocessing_complete']))))return null;
 $saved=&$job['chunk_cleanup'];
 if($input['op']==='chunk_cleanup_claim'){
  if(($saved['final_uri'] ?? '')!==$uri)$saved=['final_uri'=>$uri,'status'=>'pending','deleted_indices'=>[]];
  if($saved['status']==='complete'||($saved['retry_after'] ?? 0)>time())return null;
  if(($saved['expires'] ?? 0)>time())return null;
  $saved['lease']=bin2hex(random_bytes(24));$saved['expires']=time()+120;$saved['status']='running';
  return ['job'=>$job,'cleanup'=>$saved];
 }
 if(($saved['expires'] ?? 0)<=time()||!hash_equals($saved['lease'] ?? '',(string)($input['lease'] ?? ''))||$saved['final_uri']!==$uri||$input['final_uri']!==$uri)throw new RuntimeException('Stale cleanup');
 foreach($input['indices'] as $index){
  if(!is_int($index)||!isset($tasks[$index]))throw new InvalidArgumentException('Unknown chunk');
  $saved['deleted_indices'][]=$index;$job['stages']['render']['tasks'][$index]['result']['video_deleted_at']=gmdate('c');
 }
 $saved['deleted_indices']=array_values(array_unique($saved['deleted_indices']));unset($saved['lease'],$saved['expires']);
 if(!empty($input['error'])){$saved['status']='pending';$saved['error']=mb_substr($input['error'],0,300);$saved['retry_after']=time()+300;}
 else{$saved['status']=count($saved['deleted_indices'])===count($tasks)?'complete':'pending';unset($saved['error'],$saved['retry_after']);}
 if($saved['status']==='complete'){$saved['finished_at']=gmdate('c');event($state,$id,'Encoded chunks removed; finished MP4 and preview retained');}
 return ['status'=>$saved['status'],'deleted'=>count($saved['deleted_indices'])];
}
