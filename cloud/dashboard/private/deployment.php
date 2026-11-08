<?php
declare(strict_types=1);
/** Replace only exact saved repair pointers while this release owns the hold. */
function deployment_rebase(array &$state,array $input,string $role): array {
 $id=(string)($input['release_id']??'');
 if($role!=='dispatcher'||($state['deployment_hold']['id']??'')!==$id)throw new WorkflowConflict('Deployment hold required');
 $replacements=$input['replacements']??[];$count=0;$retired=0;
 foreach($replacements as $pointer)if($pointer!==null&&(!str_starts_with($pointer['uri']??'','gs://')||!str_contains($pointer['uri'],'/releases/'.$id.'/compatibility/')||!preg_match('/^[a-f0-9]{64}$/D',$pointer['sha256']??'')||($pointer['release_id']??'')!==$id))throw new InvalidArgumentException('Invalid tested repair pointer');
 $replace=function(array $pointer)use($replacements,&$count,&$retired):?array{
  $key=($pointer['uri']??'').'#'.($pointer['sha256']??'');
  if(!array_key_exists($key,$replacements))return $pointer;
  if($replacements[$key]===null){$retired++;return null;}
  $count++;return array_replace($pointer,$replacements[$key]);
 };
 foreach($state['jobs'] as &$job){
  if(isset($job['workflow_release'])){
   $new=$replace($job['workflow_release']);
   if($new)$job['workflow_release']=$new;else{$job['previous_workflow_release']=$job['workflow_release'];unset($job['workflow_release']);}
  }
  foreach($job['workflow_releases']??[] as $stage=>$pointer){
   $new=$replace($pointer);
   if($new)$job['workflow_releases'][$stage]=$new;else{$job['previous_workflow_releases'][$stage]=$pointer;unset($job['workflow_releases'][$stage]);}
  }
 }
 unset($job);$reusable=[];
 foreach($state['reusable_repairs']??[] as $version=>$entries)foreach($entries as $stage=>$pointer){$new=$replace($pointer);if($new)$reusable[$new['release_id']??$version][$stage]=$new;}
 $state['reusable_repairs']=$reusable;
 return ['updated_references'=>$count,'superseded_references'=>$retired];
}
