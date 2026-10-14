<?php
declare(strict_types=1);

function photo_active(array $state): bool {
    foreach($state['jobs'] as $job)foreach($job['photo_requests'] ?? [] as $request)if(in_array($request['status'],['starting','running'],true))return true;
    return false;
}

function photo_request(array &$state,array $input): array {
    $id=(string)$input['job'];$job=&$state['jobs'][$id];$person=(string)($input['person'] ?? '');
    $item=&$job['review']['photos'][$person];$action=(string)($input['action'] ?? '');$hint=trim((string)($input['hint'] ?? ''));
    if(!$item || !in_array($action,['different','recrop','synthetic'],true) || mb_strlen($hint)>2000)throw new InvalidArgumentException('Invalid photo request');
    if($job['status']==='cancelled'||$job['stages']['plan']['status']!=='pending')throw new RuntimeException('Rendering inputs are frozen');
    if(in_array($job['stages']['enrich']['status'],['starting','running'],true))throw new RuntimeException('Wait for enrichment to finish');
    $cid=(string)($input['candidate'] ?? '');$index=null;
    foreach($item['candidates'] as $i=>$c)if($c['id']===$cid)$index=$i;
    if($index===null && ($cid!=='' || $item['candidates'] || $action==='recrop'))throw new InvalidArgumentException('Unknown image');
    if($action==='recrop' && $item['candidates'][$index]['kind']!=='photo')throw new InvalidArgumentException('Only portraits are recropped');
    foreach($job['photo_requests'] ?? [] as $r)if($r['person']===$person&&in_array($r['status'],['queued','starting','running'],true))return ['id'=>$r['id'],'status'=>$r['status']];
    $key=hash('sha256',json_encode([$id,$person,$cid,$action,$hint,$job['review']['revision']]));
    $request=['id'=>$key,'person'=>$person,'candidate'=>$cid,'action'=>$action,'hint'=>$hint,'status'=>'queued','created_at'=>gmdate('c')];
    $job['photo_requests'][$key]=$request;
    if($index!==null){$item['candidates'][$index]['rejected']=true;$item['candidates'][$index]['rejection']=['action'=>$action,'hint'=>$hint];}
    unset($job['approved_photos'][$person]);if($job['status']!=='failed')$job['status']='needs_review';
    if(in_array($job['stages']['enrich']['status'],['complete','pending'],true))$job['stages']['enrich']['status']='needs_review';
    $job['review']['revision']=hash('sha256',json_encode($job['review']));
    event($state,$id,'Photo request queued: '.$item['name'].' ('.$action.')');return $request;
}

function photo_reconcile(array &$state): void {
    foreach($state['jobs'] as $id=>&$job)foreach($job['photo_requests'] ?? [] as $key=>$request){
        if($job['status']==='cancelled' && in_array($request['status'],['queued','starting','running'],true))$job['photo_requests'][$key]['status']='cancelled';
        elseif(in_array($request['status'],['starting','running'],true)&&($request['expires'] ?? 0)<=time()){
            $job['photo_requests'][$key]['status']='failed';$job['photo_requests'][$key]['error']='The photo worker stopped reporting. Retry the request.';
            unset($job['photo_requests'][$key]['lease'],$job['photo_requests'][$key]['dispatch_token']);event($state,$id,'Photo revision needs attention');
        }
    }
}

function photo_operation(array &$state,array $input,string $role): mixed {
    photo_reconcile($state);$id=(string)($input['job'] ?? '');$key=(string)($input['request'] ?? '');
    if(!isset($state['jobs'][$id]['photo_requests'][$key]))throw new InvalidArgumentException('Unknown photo request');
    $job=&$state['jobs'][$id];
    $request=&$job['photo_requests'][$key];$op=$input['op'];
    if(!$request || $job['status']==='cancelled' || $job['stages']['plan']['status']!=='pending')return null;
    if($op==='photo_dispatch'&&$role==='dispatcher'){
        if(!work_enabled($state,$job)||$request['status']!=='queued'||photo_active($state)||($state['auth_leases']['codex']['expires'] ?? 0)>time())return null;
        foreach($state['jobs'] as $j)if(in_array($j['stages']['enrich']['status'],['starting','running'],true))return null;
        foreach($state['recoveries'] ?? [] as $r)if(in_array($r['status'],['starting','running'],true))return null;
        $request['status']='starting';$request['started_at']=gmdate('c');$request['expires']=time()+600;$request['dispatch_token']=bin2hex(random_bytes(24));return $request;
    }
    if($op==='photo_dispatch_failed'&&$role==='dispatcher'){
        if(!hash_equals($request['dispatch_token'] ?? '',(string)$input['dispatch_token']))throw new RuntimeException('Stale photo request');
        $request['status']='failed';$request['error']='Photo worker could not be started';return true;
    }
    if($role!=='enrich')throw new RuntimeException('Photo access denied');
    if($op==='photo_claim'){
        if($request['status']!=='starting'||!hash_equals($request['dispatch_token'] ?? '',(string)$input['dispatch_token']))return null;
        $request['status']='running';$request['lease']=bin2hex(random_bytes(24));$request['expires']=time()+180;
        return ['request'=>$request,'job'=>$job];
    }
    if($request['status']!=='running'||($request['expires'] ?? 0)<=time()||!hash_equals($request['lease'] ?? '',(string)($input['lease'] ?? '')))throw new RuntimeException('Stale photo lease');
    if($op==='photo_heartbeat'){$request['expires']=time()+180;return true;}
    if($op==='photo_finish'){
        $candidates=$input['candidates'] ?? [];
        if(!$candidates||count($candidates)>3)throw new InvalidArgumentException('No replacement candidates');
        $item=&$job['review']['photos'][$request['person']];
        foreach($candidates as $candidate){
            if(empty($candidate['square_asset'])||!preg_match('/^[a-f0-9]{64}$/D',$candidate['sha256'] ?? '')||empty($candidate['portrait_uri'])||empty($candidate['source_uri']))throw new InvalidArgumentException('Invalid square asset');
            if(!array_filter($item['candidates'],fn($c)=>$c['id']===$candidate['id']))$item['candidates'][]=$candidate;
        }
        $request['status']='complete';$request['finished_at']=gmdate('c');
        $job['review']['revision']=hash('sha256',json_encode($job['review']));
        event($state,$id,'New photo options ready for '.$item['name']);notify_event($state,$key.'-ready','photos',$job['review']['id']);
    }elseif($op==='photo_fail'){
        $request['status']='failed';$request['error']=mb_substr((string)$input['message'],0,400);event($state,$id,'Photo revision needs attention');
        notify_event($state,$key.'-failed','photos',$job['review']['id']);
    }else throw new RuntimeException('Unknown photo operation');
    unset($request['lease'],$request['dispatch_token']);return true;
}
