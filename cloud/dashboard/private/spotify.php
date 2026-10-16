<?php
declare(strict_types=1);

function spotify_command(array &$state,array $input): array {
    global $config;
    if(empty($config['spotify_enabled']))throw new RuntimeException('Spotify transfers are not configured');
    $id=(string)($input['job'] ?? '');
    if(!isset($state['jobs'][$id]))throw new InvalidArgumentException('Unknown recording');
    $job=&$state['jobs'][$id];$item=&$job['spotify'];
    $action=$input['command'] ?? '';
    if($job['stages']['upload']['status']!=='complete'||empty($job['stages']['upload']['result']['postprocessing_complete'])||empty($job['stages']['assemble']['result']['video_uri']))throw new RuntimeException('Finish the YouTube upload first');
    if($action==='publish'){
        if(($item['status'] ?? '')==='published')return $item;
        if(!in_array($item['status'] ?? '',['uploaded','publish_queued','publishing'],true)||empty($item['upload_id'])||empty($item['episode_id']))throw new RuntimeException('Finish the Spotify transfer first');
        $item['publish_authorized']=true;
        if($item['status']==='uploaded')$item['status']='publish_queued';
    }elseif(in_array($action,['transfer','retry'],true)){
        if(in_array($item['status'] ?? '',['queued','waiting_episode','starting','uploading','uploaded','publish_queued','publishing','published'],true)){
            $item['publish_authorized']=true;
            if($item['status']==='uploaded')$item['status']='publish_queued';
            return $item;
        }
        if($action==='retry'&&($item['expires'] ?? 0)>time())throw new RuntimeException('The previous worker is still active');
        $saved=$item ?? [];
        if(!empty($input['episode_id'])){
            if(!preg_match('/^[A-Za-z0-9]{22}$/D',(string)$input['episode_id']))throw new InvalidArgumentException('Invalid episode ID');
            if(!empty($saved['upload_id'])&&($saved['episode_id'] ?? '')!==$input['episode_id'])throw new RuntimeException('Cannot change the episode of a saved upload');
            $saved['episode_id']=$input['episode_id'];
        }
        $item=['generation'=>bin2hex(random_bytes(16)),'status'=>'queued','requested_at'=>gmdate('c'),'retry_after'=>0,'attempts'=>($saved['attempts'] ?? 0),'manual'=>true,'publish_authorized'=>true];
        foreach(['episode_id','upload_id','thumbnail_status','thumbnail_note'] as $key)if(isset($saved[$key]))$item[$key]=$saved[$key];
    }else throw new InvalidArgumentException('Unknown Spotify command');
    event($state,$id,$action==='publish'?'Spotify publication requested':'Spotify transfer requested');
    return $item;
}

function spotify_operation(array &$state,array $input,string $role): mixed {
    if($role!=='spotify')throw new RuntimeException('Spotify access denied');
    $id=(string)($input['job'] ?? '');$op=$input['op'];
    if(!isset($state['jobs'][$id]))throw new InvalidArgumentException('Unknown recording');
    $job=&$state['jobs'][$id];
    if($op==='spotify_context')return ['id'=>$id,'docket'=>$job['docket'],'argument_date'=>$job['argument_date'],'case_name'=>$job['case_name'],
        'duration_seconds'=>$job['stages']['prepare']['result']['duration_seconds'] ?? 0,
        'video'=>$job['stages']['assemble']['result'] ?? [],'thumbnail_uri'=>$job['stages']['plan']['result']['thumbnail_uri'] ?? null,'spotify'=>$job['spotify'] ?? []];
    $item=&$job['spotify'];
    if(!$item||!hash_equals($item['generation'] ?? '',(string)($input['generation'] ?? '')))throw new RuntimeException('Stale Spotify request');
    if($op==='spotify_reserve'){
        if(!in_array($item['status'],['queued','waiting_episode'],true))return null;
        $episode=(string)$input['episode_id'];if(!preg_match('/^[A-Za-z0-9]{22}$/D',$episode))throw new InvalidArgumentException('Invalid episode');
        $item['episode_id']=$episode;$item['status']='starting';$item['attempts']++;
        $item['dispatch_token']=bin2hex(random_bytes(24));$item['expires']=time()+600;$item['progress']=0;
        return ['dispatch_token'=>$item['dispatch_token']];
    }
    if($op==='spotify_claim'){
        if(!hash_equals($item['dispatch_token'] ?? '',(string)($input['dispatch_token'] ?? ''))||($item['expires'] ?? 0)<=time())return null;
        $claim=(string)($input['claim_id'] ?? '');if(!preg_match('/^[a-f0-9]{32}$/D',$claim))throw new InvalidArgumentException('Invalid claim');
        if($item['status']==='uploading'&&($item['claim_id'] ?? '')===$claim)return ['lease'=>$item['lease']];
        if($item['status']!=='starting')return null;
        $item['status']='uploading';$item['lease']=bin2hex(random_bytes(24));$item['claim_id']=$claim;$item['expires']=time()+180;
        return ['lease'=>$item['lease']];
    }
    if($op==='spotify_heartbeat'){
        if($item['status']!=='uploading'||($item['expires'] ?? 0)<=time()||!hash_equals($item['lease'] ?? '',(string)($input['lease'] ?? '')))throw new RuntimeException('Spotify lease lost');
        $item['expires']=time()+180;$item['progress']=max($item['progress'] ?? 0,min(1,max(0,(float)($input['progress'] ?? 0))));return true;
    }
    if($op==='spotify_update'){
        if($item['status']!==($input['expected_status'] ?? ''))return false;
        if($item['status']==='uploading'&&(($item['expires'] ?? 0)<=time()||!hash_equals($item['lease'] ?? '',(string)($input['lease'] ?? ''))))throw new RuntimeException('Spotify lease lost');
        $status=(string)($input['status'] ?? $item['status']);
        $allowed=['queued'=>['queued','waiting_episode','uploaded','failed','needs_auth','published'],
            'waiting_episode'=>['waiting_episode','queued','uploaded','failed','needs_auth','published'],
            'starting'=>['starting','failed'],'uploading'=>['uploading','uploaded','publishing','failed','needs_auth'],
            'uploaded'=>['uploaded','publish_queued','published','failed','needs_auth'],
            'publish_queued'=>['publish_queued','publishing','published','failed','needs_auth'],
            'publishing'=>['publishing','published','failed','needs_auth']];
        if(!in_array($status,$allowed[$item['status']] ?? [],true))throw new RuntimeException('Invalid Spotify transition');
        if($status==='publishing'&&empty($item['publish_authorized']))throw new RuntimeException('Publication was not authorized');
        foreach(['episode_id','upload_id'] as $key)if(isset($input[$key])){
            if(!preg_match($key==='episode_id'?'/^[A-Za-z0-9]{22}$/D':'/^[A-Za-z0-9_-]{1,100}$/D',(string)$input[$key]))throw new InvalidArgumentException('Invalid Spotify identity');
            $item[$key]=$input[$key];
        }
        foreach(['error','note'] as $key)if(isset($input[$key]))$item[$key]=substr((string)$input[$key],0,500);
        if(isset($input['thumbnail_status'])){
            if(!in_array($input['thumbnail_status'],['complete','failed','skipped'],true))throw new InvalidArgumentException('Invalid thumbnail status');
            $item['thumbnail_status']=$input['thumbnail_status'];
        }
        if(isset($input['thumbnail_note']))$item['thumbnail_note']=substr((string)$input['thumbnail_note'],0,500);
        if(isset($input['retry_after']))$item['retry_after']=min(time()+86400,max(0,(int)$input['retry_after']));
        $before=$item['status'];$item['status']=$status;$item['updated_at']=gmdate('c');
        if(!in_array($status,['starting','uploading'],true))unset($item['lease'],$item['dispatch_token'],$item['claim_id'],$item['expires']);
        if($before!==$status){
            event($state,$id,'Spotify: '.str_replace('_',' ',$status));
            if(in_array($status,['uploaded','published','failed','needs_auth'],true))notify_event($state,$id.'-spotify-'.$item['generation'].'-'.$status,'spotify',$job['review']['id'] ?? '',$id);
        }
        return true;
    }
    throw new RuntimeException('Unknown Spotify operation');
}

function spotify_reconcile(array &$state): void {
    foreach($state['jobs'] as $id=>&$job){
        if(empty($job['spotify']))continue;
        $item=&$job['spotify'];
        if(in_array($item['status'] ?? '',['starting','uploading'],true)&&($item['expires'] ?? 0)<=time()){
            $item['status']='failed';$item['error']='Spotify worker stopped reporting. Retry reconciles the saved upload before sending more data.';
            unset($item['lease'],$item['dispatch_token'],$item['claim_id'],$item['expires']);event($state,$id,'Spotify transfer needs retry');
        }
    }
}
