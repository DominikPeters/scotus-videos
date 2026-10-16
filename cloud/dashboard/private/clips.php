<?php
/** Owner-selected derivatives; never alter the recording's main stages or upload. */
function clip_seconds(mixed $value):float{
    if(is_numeric($value))$seconds=(float)$value;
    elseif(is_string($value)&&preg_match('/^(\d+):([0-5]\d)(?::([0-5]\d(?:\.\d{1,3})?))?$/D',$value,$m))$seconds=isset($m[3])?(int)$m[1]*3600+(int)$m[2]*60+(float)$m[3]:(int)$m[1]*60+(float)$m[2];
    else throw new InvalidArgumentException('Use seconds, mm:ss or hh:mm:ss');
    if(!is_finite($seconds)||$seconds<0)throw new InvalidArgumentException('Invalid clip time');
    return round($seconds*20)/20;
}
function clip_command(array &$state,array $input):array{
    $id=(string)($input['job']??'');if(!isset($state['jobs'][$id]))throw new RuntimeException('Unknown recording');$job=&$state['jobs'][$id];
    $action=$input['command']??'';
    if($action==='create'){
        if(($job['stages']['plan']['status']??'')!=='complete'||empty($job['stages']['plan']['result']['bundle_uri']))throw new RuntimeException('Wait for preparation, alignment and presentation planning');
        if(count($job['clips']??[])>=30)throw new RuntimeException('This recording already has 30 clips');
        $start=clip_seconds($input['start']??null);$end=clip_seconds($input['end']??null);
        $duration=(float)($job['stages']['prepare']['result']['duration_seconds']??0);
        if($end<=$start||$end>$duration||$end-$start>600)throw new RuntimeException('Choose a range within the recording, at most 10 minutes');
        $title=trim((string)($input['title']??''));if(!$title||mb_strlen($title)>100)throw new RuntimeException('Enter a title of at most 100 characters');
        $key=bin2hex(random_bytes(8));$job['clips'][$key]=['id'=>$key,'title'=>$title,'start'=>$start,'end'=>$end,'status'=>'render_queued','created_at'=>gmdate('c'),
            'source_plan'=>$job['stages']['plan']['result'],'audio_uri'=>$job['stages']['prepare']['result']['audio_uri'],'progress'=>0];
    }else{
        $key=(string)($input['clip']??'');if(!isset($job['clips'][$key]))throw new RuntimeException('Unknown clip');$clip=&$job['clips'][$key];
        if(in_array($action,['tiktok_draft','tiktok_publish'],true)){
            if(!in_array($clip['status'],['ready','uploaded','failed'],true)||empty($clip['result']['video_uri']))throw new RuntimeException('Wait for this clip to finish');
            if(!empty($clip['tiktok']['published']))throw new RuntimeException('This clip is already published on TikTok');
            if($action==='tiktok_draft'&&!empty($clip['tiktok']['saved']))throw new RuntimeException('This clip already has a TikTok draft');
            $caption=trim((string)($input['caption']??$clip['tiktok']['caption']??$clip['title']));
            if(!$caption||mb_strlen($caption)>4000)throw new RuntimeException('Enter a TikTok caption of at most 4000 characters');
            if((!empty($clip['tiktok']['saved'])||!empty($clip['tiktok_checkpoint']))&&$caption!==($clip['tiktok']['caption']??''))throw new RuntimeException('Keep the saved caption while resuming this transfer');
            $clip['tiktok']['caption']=$caption;$clip['status']=$action.'_queued';
        }elseif($action==='upload'){
            if(!in_array($clip['status'],['ready','failed'],true)||empty($clip['result']['video_uri']))throw new RuntimeException('Render this clip first');
            if(!empty($clip['upload']['video_id']))throw new RuntimeException('This clip already has a YouTube upload');
            $clip['status']='upload_queued';
        }elseif($action==='retry'){
            if($clip['status']!=='failed')throw new RuntimeException('Only failed clips can be retried');
            $clip['status']=match($clip['mode']??'render'){'upload'=>'upload_queued','tiktok_draft'=>'tiktok_draft_queued','tiktok_publish'=>'tiktok_publish_queued',default=>'render_queued'};
        }else throw new RuntimeException('Unknown clip command');
        unset($clip['error']);
    }
    event($state,$id,'Vertical clip '.($action==='create'?'queued':$action.' requested'));return ['id'=>$key];
}
function clip_operation(array &$state,array $input,string $role):mixed{
    $id=(string)($input['job']??'');$key=(string)($input['clip']??'');
    if(!isset($state['jobs'][$id]['clips'][$key]))throw new RuntimeException('Unknown clip');
    $job=&$state['jobs'][$id];$clip=&$job['clips'][$key];$op=$input['op'];
    if($role==='dispatcher'&&$op==='clip_context')return ['job'=>$job,'clip'=>$clip];
    if($role==='dispatcher'&&$op==='clip_dispatch'){
        if(!in_array($clip['status'],['render_queued','upload_queued','tiktok_draft_queued','tiktok_publish_queued'],true))return null;
        $clip['mode']=match($clip['status']){'upload_queued'=>'upload','tiktok_draft_queued'=>'tiktok_draft','tiktok_publish_queued'=>'tiktok_publish',default=>'render'};$clip['status']='starting';$clip['dispatch_token']=bin2hex(random_bytes(24));$clip['expires']=time()+1200;unset($clip['operation']);
        return ['token'=>$clip['dispatch_token']];
    }
    if($role==='dispatcher'&&$op==='clip_dispatched'){$clip['operation']=$input['operation'];return true;}
    if($role==='dispatcher'&&$op==='clip_closed'){
        if(($clip['operation']??'')!==($input['operation']??'')||!in_array($clip['status'],['starting','rendering','uploading'],true))return false;
        $clip['status']='failed';$clip['error']='The cloud worker stopped before reporting completion. Retry preserves any saved upload identity.';unset($clip['lease'],$clip['dispatch_token']);return true;
    }
    if($role!=='upload')throw new RuntimeException('Clip worker access denied');
    if($op==='clip_claim'){
        if($clip['status']!=='starting'||!hash_equals($clip['dispatch_token']??'',(string)($input['token']??'')))return null;
        $clip['status']=$clip['mode']==='render'?'rendering':'uploading';$clip['lease']=bin2hex(random_bytes(24));$clip['expires']=time()+1200;$clip['started_at']=gmdate('c');
        return ['job'=>$job,'clip'=>$clip];
    }
    if(($clip['expires']??0)<time()||!hash_equals($clip['lease']??'',(string)($input['lease']??''))||!in_array($clip['status'],['rendering','uploading'],true))throw new RuntimeException('Stale clip worker');
    if($op==='clip_heartbeat'){$clip['expires']=time()+1200;$clip['progress']=min(1,max(0,(float)($input['progress']??0)));return true;}
    if($op==='clip_checkpoint'){$field=str_starts_with($clip['mode'],'tiktok_')?'tiktok_checkpoint':'upload';$clip[$field]=array_replace($clip[$field]??[],$input['checkpoint']);return true;}
    if($op==='clip_finish'){
        if(!empty($input['error'])){$clip['status']='failed';$clip['error']=mb_substr((string)$input['error'],0,500);}
        elseif(str_starts_with($clip['mode'],'tiktok_')){$clip['status']=isset($clip['youtube'])?'uploaded':'ready';$clip['tiktok']=array_replace($clip['tiktok']??[],$input['result']);}
        elseif($clip['mode']==='upload'){$clip['status']='uploaded';$clip['youtube']=$input['result'];}
        else{$clip['status']='ready';$clip['result']=$input['result'];}
        $clip['finished_at']=gmdate('c');$clip['progress']=1;unset($clip['lease'],$clip['dispatch_token']);
        notify_event($state,'clip-'.$id.'-'.$key.'-'.$clip['mode'].'-'.$clip['status'],'clip',$key,$id);event($state,$id,'Vertical clip: '.$clip['mode'].' '.$clip['status']);return true;
    }
    throw new RuntimeException('Unknown clip operation');
}
