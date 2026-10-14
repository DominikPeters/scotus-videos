<?php
require dirname(__DIR__).'/dashboard/private/state.php';
function check(bool $v,string $msg):void{if(!$v)throw new RuntimeException($msg);}
function rejected(callable $fn):void{try{$fn();}catch(Throwable $e){return;}throw new RuntimeException('Invalid operation accepted');}
$s=initial_state();$job=add_job($s,['docket'=>'25-735','argument_date'=>'2026-10-05','audio_url'=>'https://www.supremecourt.gov/a.mp3','pdf_url'=>'https://www.supremecourt.gov/t.pdf']);$id=$job['id'];
command($s,['command'=>'start','job'=>$id]);$j=&$s['jobs'][$id];$j['status']='needs_review';$j['stages']['prepare']['status']='complete';$j['stages']['enrich']['status']='needs_review';
$revision=str_repeat('b',64);$j['review']=['id'=>'review','revision'=>$revision,'photos'=>['lawyer'=>['name'=>'Test Advocate','candidates'=>[['id'=>'source','kind'=>'photo','portrait_uri'=>'gs://private/source.jpg','sha256'=>str_repeat('c',64)]]]]];
$input=['job'=>$id,'revision'=>$revision,'command'=>'photo_request','person'=>'lawyer','candidate'=>'source','action'=>'recrop','hint'=>'Do not clip his head'];
rejected(function()use(&$s,$input){review_command($s,[...$input,'revision'=>'stale']);});
$request=review_command($s,$input);$key=$request['id'];
check($j['photo_requests'][$key]['hint']==='Do not clip his head','Owner hint was lost');check($j['review']['photos']['lawyer']['candidates'][0]['rejected'],'Original was not marked rejected');
$start=worker_update($s,['op'=>'photo_dispatch','job'=>$id,'request'=>$key],'dispatcher');
check(!empty($start['dispatch_token']),'Photo worker did not dispatch while alignment is eligible');
$align=worker_update($s,['op'=>'dispatch','job'=>$id,'stage'=>'align'],'dispatcher');check(!empty($align['dispatch_token']),'Photo revision blocked alignment');
$claim=worker_update($s,['op'=>'photo_claim','job'=>$id,'request'=>$key,'dispatch_token'=>$start['dispatch_token']],'enrich');
$data=['job'=>$id,'request'=>$key,'lease'=>$claim['request']['lease']];
rejected(function()use(&$s,$data){worker_update($s,['op'=>'photo_finish',...$data,'candidates'=>[]],'upload');});
rejected(function()use(&$s,$data){worker_update($s,['op'=>'photo_heartbeat',...$data,'lease'=>'stale'],'enrich');});
check(!str_contains(json_encode(public_state($s)),$claim['request']['lease']),'Photo lease leaked to the dashboard');
$new=['id'=>'cropped','kind'=>'photo','square_asset'=>true,'portrait_uri'=>'gs://private/crop.jpg','source_uri'=>'gs://private/original.bin','sha256'=>str_repeat('d',64)];
worker_update($s,['op'=>'photo_finish',...$data,'candidates'=>[$new]],'enrich');
check(empty($j['approved_photos']['lawyer']),'Codex approved its own replacement');
check(count($j['review']['photos']['lawyer']['candidates'])===2,'Replacement not exposed for approval');
rejected(function()use(&$s,$id,&$j){review_command($s,['job'=>$id,'revision'=>$j['review']['revision'],'command'=>'photo','person'=>'lawyer','candidate'=>'source']);});
review_command($s,['job'=>$id,'revision'=>$j['review']['revision'],'command'=>'photo','person'=>'lawyer','candidate'=>'cropped']);
check($j['approved_photos']['lawyer']['id']==='cropped','New crop approval failed');check($j['stages']['align']['status']==='starting','Approval interrupted alignment');
echo "Passed async owner photo feedback, independent alignment, revision/role/lease fencing, rejected-image protection and fresh approval.\n";
