<?php
require __DIR__.'/../dashboard/private/state.php';
$privateDir=sys_get_temp_dir().'/scotus-podcast-test-'.bin2hex(random_bytes(5));mkdir($privateDir,0700);$podcastPublicDir=$privateDir.'/public';
$s=initial_state();$id='2026-10-05-25-170-argument-1';$uri='gs://private/align.json';
$s['jobs'][$id]=['id'=>$id,'stages'=>['align'=>['status'=>'complete','result'=>['transcript_uri'=>$uri]]]];
$record=['schema_version'=>1,'recording_id'=>$id,'term'=>'2026','docket'=>'25-170','argument_date'=>'2026-10-05','case_name'=>'Case','audio'=>['sha256'=>str_repeat('a',64)],'sections'=>[]];
$payload=json_encode($record);$revision=hash('sha256',$payload);
$input=['op'=>'podcast_export','job'=>$id,'source_uri'=>$uri,'payload'=>$payload,'revision'=>$revision];
podcast_operation($s,$input,'dispatcher');$index=json_decode(file_get_contents($podcastPublicDir.'/index.json'),true);
if($index['recordings'][$id]['revision']!==$revision)throw new RuntimeException('Index differs');
if(hash_file('sha256',$podcastPublicDir.'/'.$id.'-'.$revision.'.json')!==$revision)throw new RuntimeException('Published bytes differ');
podcast_operation($s,$input,'dispatcher');if(count($index['recordings'])!==1)throw new RuntimeException('Duplicate export');
$input['source_uri']='gs://private/stale.json';try{podcast_operation($s,$input,'dispatcher');throw new RuntimeException('Accepted stale alignment');}catch(RuntimeException $e){if($e->getMessage()!=='Alignment changed')throw $e;}
echo "Podcast export checks passed\n";
