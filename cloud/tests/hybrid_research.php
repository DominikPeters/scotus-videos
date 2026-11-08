<?php
require dirname(__DIR__).'/dashboard/private/state.php';
function check(bool $ok,string $why):void{if(!$ok)throw new RuntimeException($why);}
function rejected(callable $fn):void{try{$fn();}catch(Throwable $error){return;}throw new RuntimeException('Invalid research action accepted');}
$s=initial_state();$s['paused']=false;$job=add_job($s,['docket'=>'25-352','argument_date'=>'2026-11-02','audio_url'=>'https://www.supremecourt.gov/audio.mp3','pdf_url'=>'https://www.supremecourt.gov/transcript.pdf']);$id=$job['id'];
$s['jobs'][$id]['stages']['prepare']['status']='complete';$s['jobs'][$id]['stages']['align']['status']='complete';
$d=worker_update($s,['op'=>'dispatch','job'=>$id,'stage'=>'enrich'],'dispatcher');$base=['job'=>$id,'stage'=>'enrich','dispatch_token'=>$d['dispatch_token']];$claim=worker_update($s,['op'=>'claim',...$base],'enrich');$base['lease']=$claim['lease'];
$uri='gs://owned/enrichment/'.$id.'/metadata-'.str_repeat('a',64).'.json';
worker_update($s,['op'=>'enrichment_checkpoint',...$base,'enrichment_uri'=>$uri],'enrich');
rejected(function()use(&$s,$base,$uri){worker_update($s,['op'=>'enrichment_checkpoint',...$base,'enrichment_uri'=>$uri],'render');});
worker_update($s,['op'=>'research_save',...$base,'version'=>0,'operation_id'=>str_repeat('a',32),'checkpoint'=>['events'=>[],'plan'=>['hybrid'=>['readers'=>['haiku'=>['saved'=>true]],'calls'=>['editor'=>1],'tool_calls'=>['editor'=>5]]]]],'enrich');
worker_update($s,['op'=>'research_defer',...$base,'kind'=>'provider','message'=>'Subscription quota wait','retry_after'=>300,'phase'=>'haiku'],'enrich');
check($s['jobs'][$id]['status']==='queued'&&$s['jobs'][$id]['stages']['enrich']['status']==='pending'&&empty($s['recoveries']),'Provider wait started code recovery');
check($s['jobs'][$id]['stages']['enrich']['result']['enrichment_uri']===$uri,'Provider wait lost completed metadata');
check(worker_update($s,['op'=>'dispatch','job'=>$id,'stage'=>'enrich'],'dispatcher')===null,'Provider deadline was ignored');
$s['jobs'][$id]['stages']['enrich']['retry_after']=time()-1;$d=worker_update($s,['op'=>'dispatch','job'=>$id,'stage'=>'enrich'],'dispatcher');$base=['job'=>$id,'stage'=>'enrich','dispatch_token'=>$d['dispatch_token']];$claim=worker_update($s,['op'=>'claim',...$base],'enrich');$base['lease']=$claim['lease'];
worker_update($s,['op'=>'research_defer',...$base,'kind'=>'decision','message'=>'Opus already ran; explicit retry decision needed','retry_after'=>86400,'phase'=>'editor'],'enrich');
$s['jobs'][$id]['review']=['id'=>'review','revision'=>1,'photos'=>[],'cards'=>[]];reconcile_reviews($s);
check($s['jobs'][$id]['stages']['enrich']['status']==='needs_review'&&empty($s['recoveries']),'A review gate launched a doomed repair/retry');
$version=$s['jobs'][$id]['card_research']['version'];$s['paused']=true;
rejected(function()use(&$s,$id){command($s,['command'=>'research_resume','job'=>$id]);});
command($s,['command'=>'research_resume','job'=>$id,'allow_opus_retry'=>true]);$hybrid=$s['jobs'][$id]['card_research']['checkpoint']['plan']['hybrid'];
check($hybrid['calls']['editor']===0&&$hybrid['authorized_retries']['editor']===1&&$hybrid['readers']['haiku']['saved'],'Explicit retry lost reader work or failed to authorize the exception');
check($s['jobs'][$id]['card_research']['version']===$version+1&&$s['paused']&&$s['jobs'][$id]['run_requested'],'Owner resume lost fencing or changed global pause');
rejected(function()use(&$s,$base){worker_update($s,['op'=>'research_save',...$base,'version'=>1,'operation_id'=>str_repeat('b',32),'checkpoint'=>[]],'enrich');});
$token=worker_update($s,['op'=>'auth_claim','name'=>'claude'],'enrich');check(is_string($token),'Enrich could not reserve Claude');
rejected(function()use(&$s){worker_update($s,['op'=>'auth_claim','name'=>'claude'],'stats');});
worker_update($s,['op'=>'auth_release','name'=>'claude','token'=>$token],'enrich');
echo "Passed hybrid metadata checkpoints, provider waits, no repair on quotas, explicit bounded editor retry, preserved readers and Claude credential-role fencing.\n";
