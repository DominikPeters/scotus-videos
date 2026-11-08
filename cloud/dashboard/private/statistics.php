<?php
function statistics_operation(array &$state,array $input,string $role): mixed {
    if(!in_array($role,['dispatcher','stats'],true))throw new RuntimeException('Statistics access denied');
    $stats=&$state['statistics'];$stats = array_replace(['enabled'=>true,'status'=>'idle','log'=>[],'questions'=>[],'answers'=>[]],$stats ?? []);
    if($role==='dispatcher'&&in_array($input['op'],['stats_dispatched','stats_dispatch_failed','stats_execution_closed'],true)){
        if($input['op']==='stats_execution_closed'){
            if(($stats['operation']??'')!==$input['operation']||!in_array($stats['status'],['starting','running'],true))return false;
        }elseif(!hash_equals($stats['token']??'',(string)$input['token']))return false;
        if($input['op']==='stats_dispatched'){$stats['operation']=$input['operation'];return true;}
        $stats['status']='failed';$stats['message']=$input['message']??'Statistics worker exited before reporting completion; retry queued.';$stats['retry_after']=time()+60;unset($stats['token']);return true;
    }
    if($input['op']==='stats_dispatch'){
        if(!empty($state['deployment_hold']))return null;
        if($role!=='dispatcher'||empty($stats['enabled']))return null;
        if(codex_work_reserved($state))return null;
        if(in_array($stats['status'],['starting','running'],true)&&($stats['expires']??0)>time())return null;
        if(($stats['retry_after']??0)>time())return null;
        if(empty($stats['requested'])&&empty($stats['pending'])&&($stats['index_revision']??'')===$input['index_revision']&&($stats['checked_date']??'')===gmdate('Y-m-d'))return null;
        $stats['status']='starting';$stats['message']='Starting statistics update';$stats['token']=bin2hex(random_bytes(24));$stats['expires']=time()+1800;$stats['requested']=false;unset($stats['operation']);
        return ['token'=>$stats['token']];
    }
    if($role!=='stats'||!hash_equals($stats['token']??'',(string)($input['token']??'')))throw new RuntimeException('Stale statistics worker');
    if($input['op']==='stats_start'){
        if($stats['status']!=='starting')return null;
        $stats['status']='running';$stats['started_at']=gmdate('c');
        return array_intersect_key($stats,array_flip(['token','data_uri','answers']));
    }
    if($input['op']!=='stats_update'||$stats['status']!=='running')throw new RuntimeException('Statistics worker inactive');
    $stats['expires']=time()+1800;$stats['message']=mb_substr((string)$input['message'],0,1000);$stats['updated_at']=gmdate('c');
    $stats['log'][]=['at'=>gmdate('c'),'message'=>$stats['message']];$stats['log']=array_slice($stats['log'],-60);
    if(isset($input['publish'])){
        $publish=$input['publish'];$compressed=base64_decode($publish['gzip_base64'],true);
        if($compressed===false||strlen($compressed)>1500000)throw new RuntimeException('Statistics payload too large');
        $payload=gzdecode($compressed,8000000);
        if($payload===false||hash('sha256',$payload)!==$publish['sha256'])throw new RuntimeException('Statistics checksum differs');
        $records=json_decode($payload,true,512,JSON_THROW_ON_ERROR);$ids=[];
        if(!is_array($records)||count($records)!==(int)$publish['count']||count($records)<($stats['count']??0))throw new RuntimeException('Statistics lost records');
        foreach($records as $record){$id=$record['objectID']??'';if(!is_string($id)||!preg_match('/^\d{4}\//',$id)||isset($ids[$id]))throw new RuntimeException('Invalid statistics identity');$ids[$id]=true;}
        global $privateDir,$statisticsPublicDir;
        $folder=$statisticsPublicDir??dirname($privateDir).'/scotusstats/data';if(!is_dir($folder)&&!mkdir($folder,0755,true))throw new RuntimeException('Statistics directory unavailable');
        if(is_file($folder.'/flattened_records.json'))file_put_contents($privateDir.'/statistics.previous.json.gz',gzencode(file_get_contents($folder.'/flattened_records.json')));
        podcast_write($folder.'/flattened_records.json',$payload);$stats['count']=count($records);$stats['published_at']=gmdate('c');
        podcast_write($folder.'/status.json',json_encode(['updated_at'=>$stats['published_at'],'cases'=>$stats['count']],JSON_THROW_ON_ERROR));
        $stats['data_uri']=$input['data_uri'];$stats['index_revision']=$input['index_revision'];$stats['checked_date']=gmdate('Y-m-d');$stats['pending']=min(2000,max(0,(int)$input['pending']));
        $questions=$input['questions']??[];
        foreach($questions as $key=>$message)if(($stats['questions'][$key]??'')!==$message)notify_event($state,'stats-'.hash('sha256',$key.$message),'statistics',$key);
        $stats['questions']=$questions;
        $stats['technical_errors']=$input['technical_errors']??[];
        foreach($input['answered']??[] as $key)unset($stats['answers'][$key]);
    }
    if(!empty($input['finish'])){
        $stats['status']=!empty($input['failed'])?'failed':'idle';$stats['finished_at']=gmdate('c');$stats['retry_after']=time()+(!empty($input['failed'])?600:(!empty($stats['pending'])?min(3600,max(0,(int)($input['retry_after_seconds']??0))):60));unset($stats['token']);
        if(!empty($input['failed']))notify_event($state,'stats-failed-'.gmdate('Y-m-d-H'),'statistics','failure');
    }
    return true;
}
