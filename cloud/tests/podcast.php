<?php
require __DIR__.'/../dashboard/private/state.php';
$privateDir=sys_get_temp_dir().'/scotus-podcast-test-'.bin2hex(random_bytes(5));mkdir($privateDir,0700);$podcastPublicDir=$privateDir.'/public';
$s=initial_state();$id='2026-10-05-25-170-argument-1';$uri='gs://private/align.json';
$img=imagecreatetruecolor(1500,1500);ob_start();imagejpeg($img,null,70);$image=ob_get_clean();unset($img);$artHash=hash('sha256',$image);
$s['jobs'][$id]=['id'=>$id,'stages'=>['align'=>['status'=>'complete','result'=>['transcript_uri'=>$uri]],'plan'=>['status'=>'complete','result'=>['podcast_artwork_uri'=>$uri,'podcast_artwork_sha256'=>$artHash]]]];
$record=['schema_version'=>1,'recording_id'=>$id,'term'=>'2026','docket'=>'25-170','argument_date'=>'2026-10-05','case_name'=>'Case','audio'=>['sha256'=>str_repeat('a',64)],'sections'=>[],'artwork'=>['sha256'=>$artHash,'mime_type'=>'image/jpeg']];
$payload=json_encode($record);$revision=hash('sha256',$payload);
$input=['op'=>'podcast_export','job'=>$id,'source_uri'=>$uri,'payload'=>$payload,'revision'=>$revision,'artwork_base64'=>base64_encode($image)];
podcast_operation($s,$input,'dispatcher');$index=json_decode(file_get_contents($podcastPublicDir.'/index.json'),true);
if($index['recordings'][$id]['revision']!==$revision)throw new RuntimeException('Index differs');
if(hash_file('sha256',$podcastPublicDir.'/'.$id.'-'.$revision.'.json')!==$revision)throw new RuntimeException('Published bytes differ');
podcast_operation($s,$input,'dispatcher');if(count($index['recordings'])!==1)throw new RuntimeException('Duplicate export');
$input['source_uri']='gs://private/stale.json';try{podcast_operation($s,$input,'dispatcher');throw new RuntimeException('Accepted stale alignment');}catch(RuntimeException $e){if($e->getMessage()!=='Plan changed')throw $e;}
if(!is_file($podcastPublicDir.'/'.$id.'-'.$artHash.'.jpg'))throw new RuntimeException('Artwork missing');
echo "Podcast export checks passed\n";

$s['jobs'][$id]['docket']='25-170';$s['jobs'][$id]['argument_date']='2026-10-05';$s['jobs'][$id]['audio_url']='https://www.supremecourt.gov/a.mp3';
$record['audio']['url']=$s['jobs'][$id]['audio_url'];unset($record['artwork']);
$payload=json_encode($record);$revision=hash('sha256',$payload);$s['jobs'][$id]['stages']['plan']['status']='pending';
$input=['op'=>'transcript_export','job'=>$id,'source_uri'=>$uri,'payload'=>$payload,'revision'=>$revision];podcast_operation($s,$input,'dispatcher');
$file=$podcastPublicDir.'/'.$id.'-'.$revision.'.json';$before=file_get_contents($file);
$s['jobs'][$id]['stages']['plan']['status']='complete';
podcast_operation($s,['op'=>'podcast_artwork','job'=>$id,'source_uri'=>$uri,'revision'=>$revision,'artwork_base64'=>base64_encode($image)],'dispatcher');
$index=json_decode(file_get_contents($podcastPublicDir.'/index.json'),true);
if(file_get_contents($file)!==$before||$index['recordings'][$id]['revision']!==$revision||empty($index['recordings'][$id]['artwork_url']))throw new RuntimeException('Artwork rewrote shared transcript');
echo "Early shared transcript and later artwork checks passed\n";
