<?php
require dirname(__DIR__).'/dashboard/private/state.php';
function check(bool $ok,string $message):void{if(!$ok)throw new RuntimeException($message);}
function rejected(callable $fn):void{try{$fn();}catch(Throwable $error){return;}throw new RuntimeException('Invalid action accepted');}
$config=['push_public_key'=>'public-key'];
$s=initial_state();$job=add_job($s,['docket'=>'25-459','argument_date'=>'2026-10-14','case_name'=>'Salazar v. Paramount Global','audio_url'=>'https://www.supremecourt.gov/a.mp3','pdf_url'=>'https://www.supremecourt.gov/t.pdf']);$id=$job['id'];
$keys=['p256dh'=>str_repeat('B',87),'auth'=>str_repeat('a',22)];
rejected(function()use(&$s,$keys){push_subscribe($s,['subscription'=>['endpoint'=>'https://attacker.example/push','keys'=>$keys]]);});
rejected(function()use(&$s){push_subscribe($s,['subscription'=>['endpoint'=>'https://web.push.apple.com/abc','keys'=>['p256dh'=>'short','auth'=>'x']]]);});
$device=push_subscribe($s,['subscription'=>['endpoint'=>'https://web.push.apple.com/abc','keys'=>$keys],'label'=>'iPhone, Home Screen app']);
push_subscribe($s,['subscription'=>['endpoint'=>'https://web.push.apple.com/abc','keys'=>$keys],'label'=>'iPhone, Home Screen app']);
check(count($s['push_subscriptions'])===1,'Resubscribing duplicated a device');
$view=public_state($s);
check($view['push']['devices'][0]['id']===$device['id']&&$view['push']['public_key']==='public-key','Device summary missing');
check(!str_contains(json_encode($view),'web.push.apple.com')&&!str_contains(json_encode($view),$keys['auth']),'Push endpoint or key leaked to the page');

// A review notice names the case and what it needs, and links to its screen.
$s['jobs'][$id]['status']='needs_review';$s['jobs'][$id]['stages']['enrich']['status']='needs_review';
$s['jobs'][$id]['review']=['id'=>'review','revision'=>str_repeat('b',64),'card_revision'=>str_repeat('c',64),'titles'=>[['title'=>'T']],
    'cards'=>[['id'=>'one','recommended'=>true],['id'=>'two','recommended'=>false]],'photos'=>['lawyer'=>['name'=>'Lawyer','candidates'=>[]]]];
notify_event($s,'review-1','case_review','review');
$claim=worker_update($s,['op'=>'notification_claim'],'dispatcher');
check($claim['payload']['title']==='Salazar v. Paramount Global','Notification title is not the case name');
check($claim['payload']['body']==='2 annotation cards to review · 1 portrait to approve','Notification body: '.$claim['payload']['body']);
check($claim['payload']['hash']==='#/case/'.rawurlencode($id)&&$claim['payload']['badge']===1,'Deep link or badge missing');
check($claim['subscriptions'][0]['endpoint']==='https://web.push.apple.com/abc','Devices missing from claim');
check(!isset($s['notifications'][$claim['id']]['payload']),'Payload persisted in the outbox');
$revision=$s;$revision['jobs'][$id]['annotation_revision_only']=true;$revision['jobs'][$id]['stages']['plan']['status']='complete';
check(in_array('2 annotation cards to review',attention($revision,$revision['jobs'][$id]),true),'Revised cards missing from push attention');
check(notification_payload($revision,$s['notifications'][$claim['id']])!==null,'Revised card notification suppressed');
worker_update($s,['op'=>'notification_finish','id'=>$claim['id'],'token'=>$claim['token'],'sent'=>true,'delivered'=>[$device['id']],'gone'=>[]],'dispatcher');
check(!empty($s['push_subscriptions'][$device['id']]['last_sent_at']),'Delivery time not recorded');

// Handled before sending: the outbox skips it instead of sending a stale request.
review_command($s,['job'=>$id,'revision'=>str_repeat('b',64),'command'=>'cards','selections'=>['one'=>true,'two'=>false]]);
$s['jobs'][$id]['review']['photos']=[];
notify_event($s,'review-2','case_review','review');
check(worker_update($s,['op'=>'notification_claim'],'dispatcher')===null,'Handled review was still sent');
check($s['notifications'][hash('sha256','review-2')]['status']==='skipped','Handled review not marked skipped');

// Ready notices carry the job even without a review; gone devices are removed.
$s['jobs'][$id]['status']='complete';$s['jobs'][$id]['stages']['upload']=['status'=>'complete','result'=>['video_id'=>'v','postprocessing_complete'=>true]];
notify_event($s,'ready-1','ready','',$id);
$claim=worker_update($s,['op'=>'notification_claim'],'dispatcher');
check($claim['payload']['body']==='Uploaded and processed. Ready to publish.','Ready notice body');
worker_update($s,['op'=>'notification_finish','id'=>$claim['id'],'token'=>$claim['token'],'sent'=>false,'delivered'=>[],'gone'=>[$device['id']]],'dispatcher');
check(empty($s['push_subscriptions']),'Expired device was kept');
notify_event($s,'test-1','test','');
$test=worker_update($s,['op'=>'notification_claim'],'dispatcher');
check($test['kind']==='test'&&$test['payload']['hash']==='#/settings','Test notice missing');
echo "Passed push device validation/privacy, case-specific payloads, stale-notice skipping, delivery bookkeeping and expired-device removal.\n";

// Partial delivery is retried only for the device that did not accept it.
$one=push_subscribe($s,['subscription'=>['endpoint'=>'https://web.push.apple.com/mac','keys'=>['p256dh'=>str_repeat('A',87),'auth'=>str_repeat('B',22)]],'label'=>'Mac']);
$two=push_subscribe($s,['subscription'=>['endpoint'=>'https://web.push.apple.com/iphone','keys'=>['p256dh'=>str_repeat('A',87),'auth'=>str_repeat('B',22)]],'label'=>'iPhone']);
notify_event($s,'partial-device-test','test','');
$claim=worker_update($s,['op'=>'notification_claim'],'dispatcher');
worker_update($s,['op'=>'notification_finish','id'=>$claim['id'],'token'=>$claim['token'],'sent'=>false,'web_push'=>true,'delivered'=>[$one['id']],'gone'=>[]],'dispatcher');
check($s['notifications'][$claim['id']]['status']==='pending','Partial delivery marked complete');
$s['notifications'][$claim['id']]['expires']=0;
$retry=worker_update($s,['op'=>'notification_claim'],'dispatcher');
check(array_column($retry['subscriptions'],'id')===[$two['id']],'Retry duplicated the delivered Mac notification');
worker_update($s,['op'=>'notification_finish','id'=>$retry['id'],'token'=>$retry['token'],'sent'=>false,'web_push'=>true,'delivered'=>[$two['id']],'gone'=>[]],'dispatcher');
check($s['notifications'][$claim['id']]['status']==='sent','Both delivered devices did not complete the notice');
// A repair that gives up produces an actionable notification without requiring a question.
$s['jobs'][$id]['status']='failed';$s['jobs'][$id]['stages']['align']=['status'=>'failed','recovery_id'=>'stopped-repair'];
$s['recoveries']['stopped-repair']=['id'=>'stopped-repair','job'=>$id,'stage'=>'align','status'=>'unresolved','turns'=>6];
recovery_attention_notifications($s);
$key=hash('sha256','stopped-repair-attention-unresolved-6');
check(isset($s['notifications'][$key]),'Stopped recovery has no alert');
check(str_contains(notification_payload($s,$s['notifications'][$key])['body'],'Automatic repair stopped'),'Stopped recovery payload is not actionable');
$s['recoveries']['stopped-repair']['status']='waiting_for_resource';recovery_attention_notifications($s);
check(isset($s['notifications'][hash('sha256','stopped-repair-attention-waiting_for_resource-6')]),'Budget pause has no alert');
echo "Passed per-device notification retry and repair attention alerts.\n";

// A button test is targeted, bypassing older queued work without claiming non-test notices.
notify_event($s,'direct-test','test','');$testId=hash('sha256','direct-test');
$direct=worker_update($s,['op'=>'notification_claim','notice_id'=>$testId],'dispatcher');
check($direct['id']===$testId,'Immediate test claimed an older notice');
check(worker_update($s,['op'=>'notification_claim','notice_id'=>$key],'dispatcher')===null,'Test path claimed a non-test notice');
echo "Passed direct test delivery selection.\n";
