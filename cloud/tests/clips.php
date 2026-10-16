<?php
require dirname(__DIR__).'/dashboard/private/state.php';
function check(bool $ok,string $m):void{if(!$ok)throw new RuntimeException($m);}
function rejected(callable $fn):void{try{$fn();}catch(Throwable $e){return;}throw new RuntimeException('Invalid clip action accepted');}
$s=initial_state();$j=add_job($s,['docket'=>'25-459','argument_date'=>'2026-10-14','case_name'=>'Fixture','audio_url'=>'https://www.supremecourt.gov/a.mp3','pdf_url'=>'https://www.supremecourt.gov/t.pdf']);$id=$j['id'];
$s['jobs'][$id]['status']='complete';$s['jobs'][$id]['stages']['prepare']['result']=['duration_seconds'=>3000,'audio_uri'=>'gs://bucket/audio.mp3'];$s['jobs'][$id]['stages']['plan']=['status'=>'complete','result'=>['bundle_uri'=>'gs://bucket/bundle.tar.gz']];$before=$s['jobs'][$id]['stages'];
check(clip_seconds('01:02:03.5')===3723.5,'Clock parser');check(clip_seconds('12:34')===754.0,'Minute parser');
foreach([['start'=>10,'end'=>9],['start'=>0,'end'=>601],['start'=>2999,'end'=>3001]] as $range)rejected(function()use(&$s,$id,$range){clip_command($s,['job'=>$id,'command'=>'create','title'=>'Test']+$range);});
$c=clip_command($s,['job'=>$id,'command'=>'create','title'=>'Test clip','start'=>'00:30','end'=>'00:45']);$key=$c['id'];
rejected(function()use(&$s,$id,$key){clip_command($s,['job'=>$id,'clip'=>$key,'command'=>'upload']);});
$d=worker_update($s,['op'=>'clip_dispatch','job'=>$id,'clip'=>$key],'dispatcher');
check(worker_update($s,['op'=>'clip_dispatch','job'=>$id,'clip'=>$key],'dispatcher')===null,'Duplicate dispatch');
rejected(function()use(&$s,$id,$key){worker_update($s,['op'=>'clip_claim','job'=>$id,'clip'=>$key,'token'=>'wrong'],'enrich');});
$claim=worker_update($s,['op'=>'clip_claim','job'=>$id,'clip'=>$key,'token'=>$d['token']],'upload');$lease=$claim['clip']['lease'];
$public=public_state($s);check(!str_contains(json_encode($public),$lease),'Clip lease exposed');check(!isset($public['jobs'][$id]['clips'][$key]['source_plan']),'Private plan exposed');
worker_update($s,['op'=>'clip_finish','job'=>$id,'clip'=>$key,'lease'=>$lease,'result'=>['video_uri'=>'gs://bucket/clips/video.mp4','sha256'=>str_repeat('a',64)]],'upload');
check($s['jobs'][$id]['clips'][$key]['status']==='ready','Clip not ready');check($s['jobs'][$id]['stages']===$before&&$s['jobs'][$id]['status']==='complete','Clip changed original recording');
clip_command($s,['job'=>$id,'clip'=>$key,'command'=>'upload']);check($s['jobs'][$id]['clips'][$key]['status']==='upload_queued','Upload not queued');
rejected(function()use(&$s,$id,$key,$lease){worker_update($s,['op'=>'clip_finish','job'=>$id,'clip'=>$key,'lease'=>$lease,'result'=>[]],'upload');});
echo "Passed clip times, bounds, isolated state, explicit upload, dispatch fencing and private checkpoints.\n";
$c=clip_command($s,['job'=>$id,'command'=>'create','title'=>'TikTok fixture','start'=>90,'end'=>100]);$tk=$c['id'];
$s['jobs'][$id]['clips'][$tk]['status']='ready';$s['jobs'][$id]['clips'][$tk]['result']=['video_uri'=>'gs://bucket/clips/example.mp4'];
clip_command($s,['job'=>$id,'clip'=>$tk,'command'=>'tiktok_draft','caption'=>'Fixture caption']);
$dispatch=worker_update($s,['op'=>'clip_dispatch','job'=>$id,'clip'=>$tk],'dispatcher');
$claim=worker_update($s,['op'=>'clip_claim','job'=>$id,'clip'=>$tk,'token'=>$dispatch['token']],'upload');$lease=$claim['clip']['lease'];
worker_update($s,['op'=>'clip_checkpoint','job'=>$id,'clip'=>$tk,'lease'=>$lease,'checkpoint'=>['draft_pending'=>true]],'upload');
check(!isset(public_state($s)['jobs'][$id]['clips'][$tk]['tiktok_checkpoint']),'Private TikTok checkpoint exposed');
worker_update($s,['op'=>'clip_finish','job'=>$id,'clip'=>$tk,'lease'=>$lease,'result'=>['saved'=>true,'published'=>false,'caption'=>'Fixture caption']],'upload');
check($s['jobs'][$id]['clips'][$tk]['status']==='ready','TikTok replaced clip status');
check($s['jobs'][$id]['clips'][$tk]['result']['video_uri']==='gs://bucket/clips/example.mp4','TikTok replaced clip media');
rejected(function()use(&$s,$id,$tk){clip_command($s,['job'=>$id,'clip'=>$tk,'command'=>'tiktok_draft']);});
rejected(function()use(&$s,$id,$tk){clip_command($s,['job'=>$id,'clip'=>$tk,'command'=>'tiktok_publish','caption'=>'Different caption']);});
clip_command($s,['job'=>$id,'clip'=>$tk,'command'=>'tiktok_publish','caption'=>'Fixture caption']);
$dispatch=worker_update($s,['op'=>'clip_dispatch','job'=>$id,'clip'=>$tk],'dispatcher');
$claim=worker_update($s,['op'=>'clip_claim','job'=>$id,'clip'=>$tk,'token'=>$dispatch['token']],'upload');
worker_update($s,['op'=>'clip_finish','job'=>$id,'clip'=>$tk,'lease'=>$claim['clip']['lease'],'result'=>['published'=>true,'saved'=>false]],'upload');
rejected(function()use(&$s,$id,$tk){clip_command($s,['job'=>$id,'clip'=>$tk,'command'=>'tiktok_publish']);});
check($s['jobs'][$id]['stages']===$before,'TikTok changed the main recording');
echo "Passed TikTok draft/publish transitions, duplicate guards, caption identity and media preservation.\n";
