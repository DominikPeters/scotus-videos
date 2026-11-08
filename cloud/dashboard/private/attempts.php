<?php
declare(strict_types=1);
function &launch_owner(array &$state,array $owner): array {
 $kind=$owner['kind']??'';$id=$owner['job']??'';
 if($kind==='stage')$item=&$state['jobs'][$id]['stages'][$owner['stage']??''];
 elseif($kind==='recovery')$item=&$state['recoveries'][$owner['recovery']??''];
 elseif($kind==='photo')$item=&$state['jobs'][$id]['photo_requests'][$owner['request']??''];
 elseif($kind==='asset')$item=&$state['jobs'][$id]['asset_publication'];
 elseif($kind==='import')$item=&$state['jobs'][$id]['card_import'];
 elseif($kind==='video')$item=&$state['jobs'][$id]['video_actions'][$owner['action']??''];
 else throw new InvalidArgumentException('Unknown execution owner');
 if(!$item)throw new RuntimeException('Execution owner disappeared');return $item;
}
function launch_requeue(array &$item,array $owner): void {
 $item['administrative_retries']=($item['administrative_retries']??0)+1;
 if($item['administrative_retries']>3){$item['status']=$owner['kind']==='recovery'?'waiting_for_resource':'failed';$item['error']='Repeated worker interruptions; saved work retained for review';}
 else $item['status']=$owner['kind']==='stage'?'pending':'queued';
 unset($item['dispatch_token'],$item['lease'],$item['expires'],$item['cloud_operation']);
}
function launch_operation(array &$state,array $input,string $role): mixed {
 if($role!=='dispatcher')throw new RuntimeException('Execution access denied');
 $owner=$input['owner']??[];$item=&launch_owner($state,$owner);$op=$input['op'];
 if($op==='launch_prepare'){
  $token=(string)($input['dispatch_token']??'');
  if(!in_array($item['status'],['starting','running'],true)||!hash_equals($item['dispatch_token']??'',$token))throw new RuntimeException('Stale execution request');
  if(!preg_match('/^scotus-video-[a-z0-9-]+$/D',(string)$input['cloud_job']))throw new InvalidArgumentException('Invalid cloud job');
  $hash=hash('sha256',$token);
  if(($item['_launch']['token_hash']??'')===$hash)return [...$item['_launch'],'claimed'=>false];
  $state['execution_sequence']=($state['execution_sequence']??0)+1;
  $item['_launch']=['id'=>'run-'.$state['execution_sequence'],'owner'=>$owner,'cloud_job'=>$input['cloud_job'],'status'=>'requested','created_at'=>time(),'misses'=>0,'token_hash'=>$hash];
  return [...$item['_launch'],'claimed'=>true];
 }
 $launch=&$item['_launch'];if(!$launch||$launch['id']!==($input['attempt']??''))return false;
 if($op==='launch_record'){
  $operation=(string)$input['operation'];if(!preg_match('#^projects/[a-z0-9-]+/locations/[a-z0-9-]+/(operations/[a-zA-Z0-9-]+|jobs/scotus-video-[a-z0-9-]+/executions/scotus-video-[a-z0-9-]+)$#D',$operation))throw new InvalidArgumentException('Invalid cloud execution');
  $item['cloud_operation']=$operation;$item['cloud_job']=$launch['cloud_job'];$item['cloud_operation_recorded_at']=gmdate('c');$launch['status']='started';return true;
 }
 if($op==='launch_uncertain'){$launch['status']='uncertain';return true;}
 if($op==='launch_missing'){
  if(time()-$launch['created_at']<300||time()-($launch['last_checked_at']??0)<30)return false;
  $launch['last_checked_at']=time();$launch['misses']++;
  if($launch['misses']<2||$item['status']!=='starting')return false;
  $launch['status']='absent';launch_requeue($item,$owner);
  if($owner['kind']==='stage'&&$item['status']==='failed')$state['jobs'][$owner['job']]['status']='failed';return true;
 }
 if($op==='launch_closed'){
  if(!in_array($item['status'],['starting','running'],true))return false;
  $launch['status']='closed';
  if($owner['kind']==='stage')return worker_update($state,['op'=>'execution_closed','job'=>$owner['job'],'stage'=>$owner['stage'],'operation'=>$item['cloud_operation']],'dispatcher');
  if($owner['kind']==='video'){$item['status']='failed';$item['error']='Check the saved YouTube action before retrying';}
  else launch_requeue($item,$owner);
  return true;
 }
 throw new InvalidArgumentException('Unknown execution operation');
}
