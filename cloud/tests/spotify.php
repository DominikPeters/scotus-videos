<?php
require dirname(__DIR__).'/dashboard/private/state.php';
function check($ok,$why){if(!$ok)throw new RuntimeException($why);}
function denied($fn){try{$fn();}catch(Throwable $e){return;}throw new RuntimeException('Expected rejection');}
$config=['spotify_enabled'=>true];$s=initial_state();$job=add_job($s,['docket'=>'25-735','argument_date'=>'2026-10-05','audio_url'=>'https://www.supremecourt.gov/a.mp3','pdf_url'=>'https://www.supremecourt.gov/t.pdf']);$id=$job['id'];
denied(fn()=>spotify_command($s,['job'=>$id,'command'=>'transfer']));
$s['jobs'][$id]['stages']['upload']=['status'=>'complete','result'=>['postprocessing_complete'=>true]];$s['jobs'][$id]['stages']['assemble']['result']=['video_uri'=>'gs://bucket/video.mp4'];
$item=spotify_command($s,['job'=>$id,'command'=>'transfer']);check($item['manual']&&$s['paused'],'Manual transfer changed video automation');$g=$item['generation'];
check(spotify_command($s,['job'=>$id,'command'=>'transfer'])['generation']===$g,'Duplicate queue');
$base=['job'=>$id,'generation'=>$g];denied(fn()=>spotify_operation($s,['op'=>'spotify_context',...$base],'render'));
$res=spotify_operation($s,['op'=>'spotify_reserve',...$base,'episode_id'=>str_repeat('a',22)],'spotify');$claim=spotify_operation($s,['op'=>'spotify_claim',...$base,'dispatch_token'=>$res['dispatch_token'],'claim_id'=>str_repeat('a',32)],'spotify');
check(spotify_operation($s,['op'=>'spotify_claim',...$base,'dispatch_token'=>$res['dispatch_token'],'claim_id'=>str_repeat('a',32)],'spotify')===$claim,'Claim response retry duplicated lease');
check(!isset(public_state($s)['jobs'][$id]['spotify']['lease']),'Lease leaked');
$update=['op'=>'spotify_update',...$base,'lease'=>$claim['lease'],'expected_status'=>'uploading','upload_id'=>'saved'];spotify_operation($s,[...$update,'status'=>'uploaded'],'spotify');
check(empty($s['jobs'][$id]['spotify']['publish_authorized']),'Upload authorized publication');denied(fn()=>spotify_operation($s,['op'=>'spotify_update',...$base,'expected_status'=>'uploaded','status'=>'publishing'],'spotify'));
spotify_command($s,['job'=>$id,'command'=>'publish']);check($s['jobs'][$id]['spotify']['status']==='publish_queued','Owner publish did not queue');
spotify_operation($s,['op'=>'spotify_update',...$base,'expected_status'=>'publish_queued','status'=>'failed'],'spotify');$retry=spotify_command($s,['job'=>$id,'command'=>'retry']);check($retry['upload_id']==='saved'&&$retry['generation']!==$g,'Retry discarded upload identity');
denied(fn()=>spotify_operation($s,['op'=>'spotify_update',...$base,'expected_status'=>'queued','status'=>'uploaded'],'spotify'));
spotify_operation($s,['op'=>'spotify_update','job'=>$id,'generation'=>$retry['generation'],'expected_status'=>'queued','status'=>'uploaded'],'spotify');check($s['jobs'][$id]['spotify']['status']==='uploaded','Checkpoint reconciliation failed');
echo "Spotify state checks passed.\n";
