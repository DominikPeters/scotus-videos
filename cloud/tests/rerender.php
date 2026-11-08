<?php
require __DIR__.'/../dashboard/private/state.php';
function check(bool $ok,string $message):void{if(!$ok)throw new RuntimeException($message);}
$s=initial_state();$s['paused']=true;$j=add_job($s,['docket'=>'25-352','argument_date'=>'2026-11-02','pdf_url'=>'https://www.supremecourt.gov/a.pdf','audio_url'=>'https://www.supremecourt.gov/a.mp3']);$id=$j['id'];
foreach($s['jobs'][$id]['stages'] as &$stage)$stage=['status'=>'complete','attempt'=>1,'result'=>['uri'=>'preserved']];unset($stage);
$j=&$s['jobs'][$id];$j['status']='complete';$j['privacy']='unlisted';$j['cards_approved_revision']=3;$j['approved_photos']=['a'=>['id'=>'photo']];$j['selected_title']='Approved title';
$j['stages']['assemble']['result']=['video_uri'=>'gs://owned/scratch/'.$id.'/old.mp4','sha256'=>str_repeat('a',64)];
$j['stages']['upload']['checkpoint']=['video_id'=>'abcdefghijk'];$j['stages']['upload']['result']=['video_id'=>'abcdefghijk','video_url'=>'https://www.youtube.com/watch?v=abcdefghijk','postprocessing_complete'=>true];
$upstream=array_intersect_key($j['stages'],array_flip(['prepare','enrich','align','upload']));$upload=$j['stages']['upload'];
try{worker_update($s,['op'=>'rerender','job'=>$id],'enrich');throw new RuntimeException('Wrong role accepted');}catch(WorkflowConflict $e){}
$result=worker_update($s,['op'=>'rerender','job'=>$id],'dispatcher');check($result['existing_upload_preserved'],'Upload not preserved');
check(array_intersect_key($j['stages'],$upstream)===$upstream,'Upstream or upload changed');check($j['cards_approved_revision']===3&&$j['selected_title']==='Approved title','Approvals changed');
check($s['paused']===true&&$j['run_requested']===true,'Pause preference changed');
check(worker_update($s,['op'=>'rerender','job'=>$id],'dispatcher')['version']===1,'Duplicate request started another render');
foreach(['plan','render'] as $name)$j['stages'][$name]['status']='complete';
$j['stages']['assemble']['status']='running';$j['stages']['assemble']['dispatch_token']=str_repeat('d',48);$j['stages']['assemble']['lease']=['token'=>'lease','expires'=>time()+180];
worker_update($s,['op'=>'finish','job'=>$id,'stage'=>'assemble','dispatch_token'=>str_repeat('d',48),'lease'=>'lease','result'=>['video_uri'=>'gs://owned/scratch/'.$id.'/corrected.mp4','sha256'=>str_repeat('b',64),'verification'=>'mp4_header'],'continue_upload'=>true,'handoff_id'=>str_repeat('a',32)],'assemble');
check($j['status']==='complete'&&$j['render_revision']['status']==='complete','Render revision not completed');
check($j['stages']['upload']===$upload,'Existing upload or checkpoint was rewritten');check(!$j['render_revision']['upload_matches_current'],'Old upload was labelled corrected');
$completedInputs=array_intersect_key($j['stages'],array_flip(['prepare','enrich','align','plan','render','assemble']));
$result=command($s,['command'=>'upload_corrected','job'=>$id]);check($result['status']==='queued','Corrected upload not queued');
check(array_intersect_key($j['stages'],$completedInputs)===$completedInputs,'Upload rewound completed inputs');
check(empty($j['stages']['upload']['checkpoint'])&&$j['stages']['upload']['attempt']===1,'Old video checkpoint reused for corrected upload');
check($j['render_revision']['existing_youtube_url']==='https://www.youtube.com/watch?v=abcdefghijk','Earlier video reference lost');
check($s['paused']===true&&$j['run_requested']===true,'Corrected upload changed automatic pause');
command($s,['command'=>'upload_corrected','job'=>$id]);check($j['stages']['upload']['attempt']===1,'Duplicate request restarted upload');
$j['stages']['upload']['status']='running';$j['stages']['upload']['dispatch_token']=str_repeat('e',48);$j['stages']['upload']['lease']=['token'=>'upload-lease','expires'=>time()+180];
$j['stages']['upload']['checkpoint']=['video_id'=>'corrected12'];
worker_update($s,['op'=>'finish','job'=>$id,'stage'=>'upload','dispatch_token'=>str_repeat('e',48),'lease'=>'upload-lease','result'=>['video_id'=>'corrected12','video_url'=>'https://www.youtube.com/watch?v=corrected12','postprocessing_complete'=>true,'privacy'=>'unlisted']],'upload');
check($j['render_revision']['upload_matches_current']&&$j['status']==='complete','Corrected upload did not become current');
command($s,['command'=>'upload_corrected','job'=>$id]);check($j['stages']['upload']['checkpoint']['video_id']==='corrected12','Repeated completed request created another upload');
echo "Passed render-only regeneration, approval/pause preservation, duplicate request handling and no upload handoff.\n";
