<?php
declare(strict_types=1);

/** Web Push devices. Payloads are encrypted to each device, so they may name the case. */
const PUSH_HOSTS=['web.push.apple.com','fcm.googleapis.com','updates.push.services.mozilla.com','push.services.mozilla.com'];

function push_subscribe(array &$state,array $input): array {
    $sub=$input['subscription'] ?? null;
    $endpoint=(string)($sub['endpoint'] ?? '');$parts=parse_url($endpoint);
    $host=strtolower($parts['host'] ?? '');
    $known=in_array($host,PUSH_HOSTS,true)||str_ends_with($host,'.notify.windows.com')||str_ends_with($host,'.push.apple.com');
    if(($parts['scheme'] ?? '')!=='https'||!$known||isset($parts['user'])||isset($parts['port'])||strlen($endpoint)>1024)
        throw new InvalidArgumentException('Unsupported push service');
    $p256dh=(string)($sub['keys']['p256dh'] ?? '');$auth=(string)($sub['keys']['auth'] ?? '');
    if(!preg_match('/^[A-Za-z0-9_-]{86,88}={0,2}$/D',$p256dh)||!preg_match('/^[A-Za-z0-9_-]{21,24}={0,2}$/D',$auth))
        throw new InvalidArgumentException('Invalid push keys');
    $id=substr(hash('sha256',$endpoint),0,16);
    $label=mb_substr(preg_replace('/[\x00-\x1f\x7f<>]/u','',(string)($input['label'] ?? 'Device')),0,60);
    $state['push_subscriptions'] ??= [];
    $previous=$state['push_subscriptions'][$id] ?? [];
    $state['push_subscriptions'][$id]=['id'=>$id,'endpoint'=>$endpoint,'p256dh'=>rtrim($p256dh,'='),'auth'=>rtrim($auth,'='),
        'label'=>$label,'created_at'=>$previous['created_at'] ?? gmdate('c')]+array_intersect_key($previous,['last_sent_at'=>1]);
    // A handful of devices at most; the oldest registration goes first.
    uasort($state['push_subscriptions'],fn($a,$b)=>strcmp($b['created_at'],$a['created_at']));
    $state['push_subscriptions']=array_slice($state['push_subscriptions'],0,8,true);
    event($state,'','Notifications turned on for '.$label);
    return ['id'=>$id];
}

function push_unsubscribe(array &$state,array $input): bool {
    $id=(string)($input['id'] ?? '');
    if(!isset($state['push_subscriptions'][$id]))return false;
    event($state,'','Notifications turned off for '.$state['push_subscriptions'][$id]['label']);
    unset($state['push_subscriptions'][$id]);return true;
}

function push_delivery(array &$state,array $delivered,array $gone): void {
    foreach($delivered as $id)if(isset($state['push_subscriptions'][$id]))$state['push_subscriptions'][$id]['last_sent_at']=gmdate('c');
    foreach($gone as $id)unset($state['push_subscriptions'][$id]);
}

function notification_prune(array &$state): void {
    $cutoff=gmdate('c',time()-30*86400);
    foreach($state['notifications'] ?? [] as $id=>$item)
        if(in_array($item['status'],['sent','skipped'],true)&&($item['created_at'] ?? '')<$cutoff)unset($state['notifications'][$id]);
}

function notification_job(array $state,array $item): ?string {
    if(!empty($item['job'])&&isset($state['jobs'][$item['job']]))return $item['job'];
    if(in_array($item['kind'],['question','recovery','failure'],true))return $state['recoveries'][$item['target']]['job'] ?? null;
    foreach($state['jobs'] as $id=>$job)if($item['target']!==''&&($job['review']['id'] ?? '')===$item['target'])return $id;
    return null;
}

function pending_questions(array $state,string $job): array {
    $questions=[];
    foreach($state['recoveries'] ?? [] as $rec){
        if($rec['job']!==$job||$rec['status']!=='needs_input')continue;
        $stage=$state['jobs'][$job]['stages'][$rec['stage']] ?? [];
        if(($stage['status'] ?? '')==='complete'&&($stage['recovery_id'] ?? '')===$rec['id'])continue;
        foreach($rec['questions'] ?? [] as $question)if($question['status']==='pending')$questions[]=$question;
    }
    return $questions;
}

/** What a recording needs from the owner; the dashboard computes the same list in model.js. */
function attention(array $state,array $job): array {
    $id=$job['id'];$todo=[];
    $editable=$job['status']!=='cancelled'&&$job['stages']['plan']['status']==='pending';
    $questions=count(pending_questions($state,$id));
    foreach($state['recoveries'] ?? [] as $rec)if($rec['job']===$id&&($job['stages'][$rec['stage']]['status'] ?? '')!=='complete'){
        if($rec['status']==='unresolved')$todo[]='Repair stopped; needs your decision';
        if($rec['status']==='waiting_for_resource')$todo[]='Repair paused: daily budget reached';
    }
    if($questions)$todo[]=$questions===1?'Codex has a question':"Codex has $questions questions";
    if(($editable||!empty($job['annotation_revision_only']))&&cards_pending($job))$todo[]=count($job['review']['cards']).' annotation '.(count($job['review']['cards'])===1?'card':'cards').' to review';
    $busy=[];foreach($job['photo_requests'] ?? [] as $r)if(in_array($r['status'],['queued','starting','running'],true))$busy[$r['person']]=true;
    $portraits=0;foreach(array_keys($job['review']['photos'] ?? []) as $person)if(empty($job['approved_photos'][$person])&&empty($busy[$person]))$portraits++;
    if($editable&&$portraits)$todo[]=$portraits.' '.($portraits===1?'portrait':'portraits').' to approve';
    $upload=$job['stages']['upload'];$publishing=false;
    foreach($job['video_actions'] ?? [] as $action){
        if($action['kind']==='publish'&&in_array($action['status'],['queued','starting','running'],true))$publishing=true;
        if($action['status']==='failed')$todo[]=$action['kind']==='publish'?'Publication failed':'Title update failed';
    }
    if($job['status']==='complete'&&$job['privacy']==='unlisted'&&($upload['status'] ?? '')==='complete'&&!empty($upload['result']['postprocessing_complete'])&&!$publishing)$todo[]='Ready to publish';
    if($job['status']==='failed'){
        $repairing=false;
        foreach($state['recoveries'] ?? [] as $rec)if($rec['job']===$id&&in_array($rec['status'],['queued','starting','running','needs_input','waiting_for_stage','waiting_for_tests'],true))$repairing=true;
        if(!$repairing)$todo[]='Processing stopped';
    }
    if(array_filter($job['photo_requests'] ?? [],fn($r)=>$r['status']==='failed'))$todo[]='Portrait request failed';
    global $config;
    if(!empty($config['spotify_enabled'])){
        $spotify=$job['spotify']['status'] ?? '';
        if($spotify==='uploaded')$todo[]='Ready to publish on Spotify';
        if($spotify==='needs_auth')$todo[]='Spotify needs reconnecting';
        if($spotify==='failed')$todo[]='Spotify transfer failed';
    }
    if(($job['asset_publication']['status'] ?? '')==='failed')$todo[]='Portrait commit to GitHub failed';
    return $todo;
}

function attention_count(array $state): int {
    return count(array_filter($state['jobs'] ?? [],fn($job)=>(bool)attention($state,$job)));
}

/** Title, text and deep link for one outbox entry, or null when it no longer applies. */
function notification_payload(array $state,array $item): ?array {
    $base=['badge'=>attention_count($state),'at'=>$item['created_at'] ?? gmdate('c')];
    if($item['kind']==='statistics'){
        $message=$state['statistics']['questions'][$item['target']] ?? null;
        if($item['target']==='failure'&&($state['statistics']['status']??'')==='failed')$message=$state['statistics']['message'];
        return $message?$base+['title'=>'Scotus statistics','body'=>mb_substr($message,0,300),'hash'=>'#/settings','tag'=>'statistics','job'=>'']:null;
    }
    if($item['kind']==='test')return $base+['title'=>'Scotus videos','body'=>'Notifications work on this device.','hash'=>'#/settings','tag'=>'test','job'=>''];
    $id=notification_job($state,$item);$job=$id?$state['jobs'][$id]:null;
    if(!$job)return in_array($item['kind'],['recovery','question'],true)?$base+['title'=>'Scotus videos','body'=>'Processing needs attention.','hash'=>'#/','tag'=>'general','job'=>'']:null;
    $short=fn(string $text,int $limit)=>mb_strlen($text)>$limit?rtrim(mb_substr($text,0,$limit-1)).'…':$text;
    $todo=attention($state,$job);
    switch($item['kind']){
        case 'case_review':case 'photos':
            if(!array_filter($todo,fn($t)=>str_contains($t,'card')||str_contains($t,'portrait'))&&
               !array_filter($job['photo_requests'] ?? [],fn($r)=>$r['status']==='failed'))return null;
            $body=implode(' · ',array_filter($todo,fn($t)=>str_contains($t,'card')||str_contains($t,'portrait')));
            if($body==='')$body='A portrait request failed.';break;
        case 'question':
            $questions=pending_questions($state,$id);
            if(!$questions)return null;
            $body=$short((string)end($questions)['message'],220);break;
        case 'ready':
            if($job['privacy']!=='unlisted')return null;
            $body='Uploaded and processed. Ready to publish.';break;
        case 'failure':
            $rec=$state['recoveries'][$item['target']] ?? [];
            if(!in_array($rec['status'] ?? '',['unresolved','waiting_for_resource'],true)||$job['status']==='cancelled'||$job['stages'][$rec['stage']]['status']==='complete')return null;
            $body=$rec['status']==='waiting_for_resource'?'Repair paused: daily budget reached. Open the case to continue.':'Automatic repair stopped. Open the case to decide what to do next.';break;
        case 'recovery':
            $rec=$state['recoveries'][$item['target']] ?? [];
            if(in_array($rec['status'] ?? '',['cancelled','repaired','unresolved','waiting_for_resource'],true))return null;
            $body='Processing needs recovery'.(isset($rec['stage'])?' at '.$rec['stage']:'').'; Codex is working on it.';break;
        case 'clip':
            $clip=$job['clips'][$item['target']]??[];
            $body=['ready'=>'Vertical clip ready to download.','uploaded'=>'Vertical clip uploaded to YouTube (unlisted).','failed'=>'Vertical clip failed; open the case for details.'][$clip['status']??'']??null;
            if(str_starts_with($clip['mode']??'','tiktok_')&&in_array($clip['status']??'',['ready','uploaded'],true))$body=!empty($clip['tiktok']['published'])?'Clip published on TikTok.':'TikTok draft saved.';
            if(!$body)return null;break;
        case 'spotify':
            $status=$job['spotify']['status'] ?? '';
            $body=['uploaded'=>'Uploaded to Spotify. Ready to publish there.','published'=>'Published on Spotify.',
                   'failed'=>'Spotify transfer failed.','needs_auth'=>'Spotify needs reconnecting.'][$status] ?? null;
            if(!$body)return null;break;
        default:return null;
    }
    return $base+['title'=>$short($job['case_name'],80),'body'=>$body,'hash'=>'#/case/'.rawurlencode($id),'tag'=>$id,'job'=>$id];
}

/** Event-driven send after the state transaction and HTTP reply, independent of work polling. */
function schedule_push_delivery(): void {
    static $scheduled=false;
    if($scheduled)return;
    $scheduled=true;
    register_shutdown_function(function(){
        global $config;
        if(empty($config['control_url'])||!function_exists('cloud_request'))return;
        if(session_status()===PHP_SESSION_ACTIVE)session_write_close();
        if(function_exists('fastcgi_finish_request'))fastcgi_finish_request();
        try{cloud_request($config,'notifications',[],15);}catch(Throwable $error){error_log('Scotus immediate push delivery failed; outbox retained for retry.');}
    });
}
