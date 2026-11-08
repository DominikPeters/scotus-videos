<?php
declare(strict_types=1);

function review_key(mixed $value): string {
 if(is_array($value)){if(!array_is_list($value))ksort($value);foreach($value as &$item)$item=review_key_value($item);}
 return hash('sha256',json_encode($value,JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR));
}
function review_key_value(mixed $value): mixed {
 if(is_array($value)){if(!array_is_list($value))ksort($value);foreach($value as &$item)$item=review_key_value($item);}return $value;
}
function review_versions(array &$job): void {
 if(empty($job['review']))return;
 $r=&$job['review'];if(isset($r['versions']))return;
 $old=$r['revision']??null;$card=$r['card_revision']??null;
 $r['version']=1;$r['revision']=1;$r['versions']=['cards'=>1,'title'=>1,'photos'=>array_fill_keys(array_keys($r['photos']??[]),1)];
 if(is_string($old)){$r['legacy_revision']=$old;$r['legacy_versions']=['cards'=>$old,'title'=>$old,'photos'=>array_fill_keys(array_keys($r['photos']??[]),$old)];}
 $r['card_revision']=1;
 if($card!==null&&($job['cards_approved_revision']??null)===$card)$job['cards_approved_revision']=1;
}
function review_component(array $job,string $scope,string $person=''): int {
 return (int)($scope==='photo'?($job['review']['versions']['photos'][$person]??1):($job['review']['versions'][$scope]??$job['review']['version']??1));
}
function review_check(array &$job,array $input,string $scope,string $person=''): void {
 review_versions($job);
 if(array_key_exists('version',$input)){$ok=is_int($input['version'])&&$input['version']===review_component($job,$scope,$person);}
 else{$value=$input['revision']??null;$legacy=$scope==='photo'?($job['review']['legacy_versions']['photos'][$person]??null):($job['review']['legacy_versions'][$scope]??$job['review']['legacy_revision']??null);$ok=$value===($job['review']['revision']??null)||($value!==null&&$value===$legacy);}
 if(!$ok)throw new WorkflowConflict('This item changed; refresh its review');
}
function review_touch(array &$job,string $scope,string $person=''): void {
 review_versions($job);$r=&$job['review'];$r['revision']=++$r['version'];unset($r['legacy_revision']);
 if($scope==='photo'){$r['versions']['photos'][$person]=review_component($job,'photo',$person)+1;unset($r['legacy_versions']['photos'][$person]);}
 else {$r['versions'][$scope]=review_component($job,$scope)+1;unset($r['legacy_versions'][$scope]);}
 if($scope==='cards')$r['card_revision']=$r['versions']['cards'];
}
function review_install(array &$job,array $incoming): void {
 review_versions($job);$previous=$job['review']??[];
 $versions=$previous['versions']??['cards'=>1,'title'=>1,'photos'=>[]];$changed=false;
 $project=fn($cards)=>array_map(fn($c)=>array_intersect_key($c,array_flip(['id','cue','cue_json','start','end','preview_id','frame_uri','card_uri'])),$cards);
 if($previous&&review_key($project($incoming['cards']??[]))!==review_key($project($previous['cards']??[]))){$versions['cards']++;$changed=true;unset($job['cards_approved_revision']);}
 if($previous&&review_key($incoming['titles']??[])!==review_key($previous['titles']??[])){$versions['title']++;$changed=true;}
 foreach($incoming['photos']??[] as $person=>$photo){
  $versions['photos'][$person]??=1;
  if(isset($previous['photos'][$person])&&review_key($photo)!==review_key($previous['photos'][$person])){$versions['photos'][$person]++;$changed=true;}
 }
 $version=($previous['version']??1)+($changed?1:0);
 $legacy=$incoming['revision']??null;
 unset($incoming['legacy_revision'],$incoming['legacy_versions']);$job['review']=[...$incoming,'version'=>$version,'revision'=>$version,'versions'=>$versions,'card_revision'=>$versions['cards']];
 if(is_string($legacy)&&preg_match('/^[a-f0-9]{64}$/D',$legacy)){$job['review']['legacy_revision']=$legacy;$job['review']['legacy_versions']=['cards'=>$legacy,'title'=>$legacy,'photos'=>array_fill_keys(array_keys($incoming['photos']??[]),$legacy)];}
}

function notify_event(array &$state,string $key,string $kind,string $target,string $job=''): void {
    $id=hash('sha256',$key);$state['notifications'] ??= [];
    if(isset($state['notifications'][$id]))return;
    $state['notifications'][$id]=['id'=>$id,'kind'=>$kind,'target'=>$target,'job'=>$job,'status'=>'pending','attempts'=>0,'created_at'=>gmdate('c')];
    schedule_push_delivery();
}

function review_operation(array &$state,array $input,string $role): mixed {
    $op=$input['op'];
    if($role==='dispatcher'&&$op==='notification_claim'){
        notification_prune($state);
        foreach($state['notifications'] ?? [] as $id=>$item){
            if(!empty($input['notice_id'])&&($id!==$input['notice_id']||$item['kind']!=='test'))continue;
            if(in_array($item['status'],['sent','skipped'],true)||($item['expires'] ?? 0)>time()||$item['attempts']>=3)continue;
            // Built at send time, so a review handled in the meantime sends nothing.
            $payload=notification_payload($state,$item);
            if(!$payload){$state['notifications'][$id]['status']='skipped';continue;}
            $item['token']=bin2hex(random_bytes(24));$item['expires']=time()+90;$item['attempts']++;
            $state['notifications'][$id]=$item;
            $subscriptions=array_filter($state['push_subscriptions'] ?? [],fn($s)=>empty($item['delivered'][$s['id']]));
            return $item+['payload'=>$payload,'subscriptions'=>array_values(array_map(fn($s)=>array_intersect_key($s,array_flip(['id','endpoint','p256dh','auth'])),$subscriptions))];
        }return null;
    }
    if($role==='dispatcher'&&$op==='notification_finish'){
        $item=&$state['notifications'][$input['id']];
        if(!$item||!hash_equals($item['token'] ?? '',(string)$input['token']))throw new WorkflowConflict('Stale notification');
        $delivered=(array)($input['delivered'] ?? []);$gone=(array)($input['gone'] ?? []);
        push_delivery($state,$delivered,$gone);
        foreach($delivered as $device)$item['delivered'][$device]=gmdate('c');
        $devices=$state['push_subscriptions'] ?? [];
        $complete=!empty($input['sent'])||(!empty($input['web_push'])&&$devices&&!array_filter($devices,fn($s)=>empty($item['delivered'][$s['id']])));
        $item['status']=$complete?'sent':($devices?'pending':'waiting_for_device');
        if(!$devices)$item['attempts']=0;
        unset($item['token']);$item['expires']=time()+300;return true;
    }
    $id=(string)($input['job'] ?? '');if(!isset($state['jobs'][$id]))throw new InvalidArgumentException('Unknown recording');
    $job=&$state['jobs'][$id];
    review_versions($job);
    if($op==='asset_publish_dispatch'&&$role==='dispatcher'){
        if(!work_enabled($state,$job))return null;
        $item=&$job['asset_publication'];if(($item['status'] ?? '')!=='queued')return null;
        $item['status']='starting';$item['dispatch_token']=bin2hex(random_bytes(24));$item['expires']=time()+180;
        return ['dispatch_token'=>$item['dispatch_token']];
    }
    if($op==='asset_publish_claim'&&$role==='assets'){
        $item=&$job['asset_publication'];if(($item['status'] ?? '')!=='starting'||!hash_equals($item['dispatch_token'] ?? '',(string)$input['dispatch_token']))return null;
        $item['status']='running';$item['lease']=bin2hex(random_bytes(24));$item['expires']=time()+180;
        return ['job'=>$job,'lease'=>$item['lease']];
    }
    if($op==='asset_portrait_export'&&$role==='assets'){
        $item=$job['asset_publication']??[];
        if(($item['status']??'')!=='running'||($item['expires']??0)<=time()||!hash_equals($item['lease']??'',(string)($input['lease']??'')))throw new WorkflowConflict('Stale portrait publisher');
        $person=(string)($input['person']??'');$approved=$job['approved_photos'][$person]??null;
        if(!preg_match('/^[a-z][a-z0-9_]{1,100}$/D',$person)||!$approved)throw new WorkflowConflict('Portrait not approved');
        $bytes=base64_decode((string)($input['image_base64']??''),true);
        if($bytes===false||strlen($bytes)>4194304||!hash_equals($approved['sha256'],hash('sha256',$bytes))||!str_starts_with($bytes,"\xff\xd8\xff"))throw new WorkflowConflict('Approved JPEG differs');
        global $privateDir,$statisticsPublicDir;
        $root=$statisticsPublicDir??dirname($privateDir).'/scotusstats/data';$folder=dirname($root).'/img/advocates';
        if(!is_dir($folder)&&!mkdir($folder,0755,true))throw new WorkflowConflict('Portrait folder unavailable');
        podcast_write($folder.'/'.$person.'.jpg',$bytes);
        return ['url'=>'/img/advocates/'.$person.'.jpg'];
    }
    if($op==='asset_publish_finish'&&$role==='assets'){
        $item=&$job['asset_publication'];if(!$item||($item['expires'] ?? 0)<=time()||!hash_equals($item['lease'] ?? '',(string)$input['lease']))throw new WorkflowConflict('Stale portrait publisher');
        $item['status']=!empty($input['success'])?'complete':'failed';$item['results']=$input['results'];unset($item['lease'],$item['dispatch_token']);
        event($state,$id,!empty($input['success'])?(!empty($input['results'])?'Approved portraits published and saved to GitHub':'Approved portraits published'):'Portrait publication needs review');return true;
    }
    if($op==='card_context'&&$role==='enrich')return $job;
    if($op==='review_context'&&$role==='dispatcher')return $job;
    if($op==='review_candidate_add'&&$role==='dispatcher'){
        review_check($job,$input,'photo',$input['person']);
        if(!isset($job['review']['photos'][$input['person']]))throw new WorkflowConflict('Review changed');
        $photo=&$job['review']['photos'][$input['person']];
        if(count($photo['candidates'])>=8)throw new WorkflowConflict('Too many candidates');
        $photo['candidates'][]=$input['candidate'];
        review_touch($job,'photo',$input['person']);
        if(($input['candidate']['kind'] ?? '')==='photo'&&empty($input['candidate']['square_asset']))photo_request($state,['job'=>$id,'person'=>$input['person'],'candidate'=>$input['candidate']['id'],'action'=>'recrop','hint'=>'Prepare a square portrait with full head and headroom.']);
        event($state,$id,'Photo candidate added for '.$photo['name']);return ['saved'=>true];
    }
    if($op==='enrichment_review'&&$role==='enrich'){
        $stage=&$job['stages']['enrich'];
        if(($stage['status'] ?? '')!=='running'||($stage['lease']['expires'] ?? 0)<=time()||
           !hash_equals($stage['lease']['token'] ?? '',(string)($input['lease'] ?? '')))throw new WorkflowConflict('Stale enrichment');
        $review=$input['review'];
        if(!is_array($review)||count($review['titles'] ?? [])>3)throw new InvalidArgumentException('Invalid review');
        foreach($review['titles'] ?? [] as $candidate)if(!is_string($candidate['title'] ?? null)||mb_strlen($candidate['title'])>100)throw new InvalidArgumentException('Invalid title');
        if(!empty($review['cards'])&&count(array_unique(array_column($review['cards'],'id')))!==count($review['cards']))throw new InvalidArgumentException('Invalid annotation review');
        review_install($job,$review);$review=$job['review'];$stage['result']=$input['result'];
        if(!empty($job['annotation_import_cancelled'])&&empty($review['cards'])){unset($job['annotation_import_cancelled'],$stage['lease']);$stage['status']='pending';$job['status']='queued';return ['needs_review'=>true];}
        $missing=false;
        if(($job['card_import']['status']??'')==='waiting_for_metadata')$job['card_import']['status']='queued';
        if(in_array($job['card_import']['status']??'',['uploading','queued','starting','running','failed','needs_rebind'],true))$missing=true;
        foreach($review['photos'] ?? [] as $person=>$item){
            if(empty($job['approved_photos'][$person])){
                if(!empty($item['approved_existing'])){
                    $job['approved_photos'][$person]=$item['approved_existing'];
                    if(!in_array($job['asset_publication']['status']??'',['starting','running'],true))$job['asset_publication']=['status'=>'queued'];
                }
                else $missing=true;
            }
        }
        if(cards_pending($job))$missing=true;
        if($missing){$stage['status']='needs_review';if($job['status']!=='failed')$job['status']='needs_review';unset($stage['lease']);
            notify_event($state,$id.'-review-'.$review['revision'],!empty($review['cards'])?'case_review':'photos',$review['id']);
            foreach($review['photos'] as $person=>$item){
                if(!empty($job['approved_photos'][$person]))continue;
                foreach($item['candidates'] ?? [] as $candidate)if(($candidate['kind'] ?? '')==='photo'&&empty($candidate['square_asset'])&&empty($candidate['rejected'])){
                    photo_request($state,['job'=>$id,'person'=>$person,'candidate'=>$candidate['id'],'action'=>'recrop','hint'=>'Prepare a square portrait showing the entire head with headroom and shoulders where possible.']);break;
                }
            }
        }
        return ['needs_review'=>$missing];
    }
    if($op==='video_action_claim'&&$role==='upload'){
        $action=&$job['video_actions'][$input['action_id']];
        if(!$action||$action['status']!=='starting'||!hash_equals($action['dispatch_token'] ?? '',(string)$input['dispatch_token']))return null;
        $action['status']='running';$action['lease']=bin2hex(random_bytes(24));$action['expires']=time()+180;
        return ['job'=>$job,'action'=>$action];
    }
    if($op==='video_action_finish'&&$role==='upload'){
        $action=&$job['video_actions'][$input['action_id']];
        if(!$action||($action['expires'] ?? 0)<=time()||!hash_equals($action['lease'] ?? '',(string)$input['lease']))throw new WorkflowConflict('Stale video action');
        $action['status']=!empty($input['success'])?'complete':'failed';unset($action['lease'],$action['dispatch_token']);
        if(!empty($input['success'])){
            if($action['kind']==='publish')$job['privacy']='public';
            if($action['kind']==='title')$job['title']=$action['title'];
            try{podcast_youtube_link($job);}catch(Throwable $e){event($state,$id,'Podcast video link export failed; YouTube action succeeded');}
            event($state,$id,$action['kind']==='publish'?'Video published':'YouTube title updated');
        }return true;
    }
    if($op==='video_action_dispatch'&&$role==='dispatcher'){
        if(!work_enabled($state,$job))return null;
        foreach($job['video_actions'] ?? [] as $action)if(in_array($action['status'],['starting','running'],true))return null;
        foreach($job['video_actions'] ?? [] as $aid=>$action){
            if($action['status']!=='queued')continue;
            $action['status']='starting';$action['expires']=time()+180;$action['dispatch_token']=bin2hex(random_bytes(24));
            $job['video_actions'][$aid]=$action;return $action;
        }return null;
    }
    throw new WorkflowConflict('Review access denied');
}

function cards_pending(array $job): bool {
    if(in_array($job['card_import']['status']??'',['uploading','queued','starting','running','waiting_for_metadata','needs_rebind','failed'],true))return true;
    return !empty($job['review']['cards'])&&($job['cards_approved_revision'] ?? '')!==($job['review']['card_revision'] ?? '');
}

function reconcile_reviews(array &$state): void {
    foreach($state['jobs'] as $id=>&$job){
        if(!empty($job['research_attention']))continue;
        if(($job['stages']['enrich']['status'] ?? '')!=='needs_review'||empty($job['review']))continue;
        $pending=array_filter(array_keys($job['review']['photos'] ?? []),fn($key)=>empty($job['approved_photos'][$key]));
        if($pending||cards_pending($job))continue;
        if(!empty($job['annotation_revision_only'])){
            $job['stages']['enrich']['status']='complete';$job['stages']['enrich']['progress']=1;$job['stages']['enrich']['finished_at']=gmdate('c');$job['status']='complete';
            event($state,$id,'Revised card selections saved; existing video retained. A new render is a separate action.');
            reconcile_recoveries($state);
            continue;
        }
        $job['stages']['enrich']['status']='pending';
        if($job['status']==='needs_review')$job['status']=count(array_filter($job['stages'],fn($s)=>in_array($s['status'],['starting','running'],true)))?'running':'queued';
        event($state,$id,'Case review approved; metadata finalization queued');
    }
}

function review_command(array &$state,array $input): array {
    $id=(string)($input['job'] ?? '');$job=&$state['jobs'][$id];
    if(!$job)throw new WorkflowConflict('Unknown recording');
    $action=$input['command'] ?? '';
    $scope=$action==='cards'?'cards':(str_starts_with($action,'photo')?'photo':(in_array($action,['title','publish'],true)?'title':'all'));
    review_check($job,$input,$scope,(string)($input['person']??($job['photo_requests'][$input['request']??'']['person']??'')));
    if($action==='photo_request')return photo_request($state,$input);
    if($action==='photo_retry'){
        $request=&$job['photo_requests'][(string)$input['request']];
        if(!$request||$request['status']!=='failed'||$job['status']==='cancelled'||$job['stages']['plan']['status']!=='pending')throw new WorkflowConflict('Photo request changed');
        $request['status']='queued';unset($request['error'],$request['lease'],$request['dispatch_token']);return $request;
    }
    if($action==='cards'){
        if(in_array($job['card_import']['status']??'',['uploading','queued','starting','running','waiting_for_metadata'],true))throw new WorkflowConflict('Wait for the imported card previews');
        if($job['stages']['plan']['status']!=='pending'&&empty($job['annotation_revision_only']))throw new WorkflowConflict('Rendering inputs are frozen');
        $choices=$input['selections'] ?? null;$ids=array_column($job['review']['cards'] ?? [],'id');
        if(!is_array($choices)||count($choices)!==count($ids)||array_diff(array_keys($choices),$ids)||array_diff($ids,array_keys($choices)))throw new WorkflowConflict('Select show or hide for every card');
        foreach($choices as $value)if(!is_bool($value))throw new WorkflowConflict('Invalid card selection');
        if(($job['card_selections']??null)!==$choices)review_touch($job,'cards');
        $job['card_selections']=$choices;$job['cards_approved_revision']=$job['review']['card_revision'];event($state,$id,'Annotation card selections approved');
        reconcile_reviews($state);return ['status'=>$job['status']];
    }
    if($action==='asset_retry'){
        if(($job['asset_publication']['status'] ?? '')!=='failed')throw new WorkflowConflict('Portrait publisher has not failed');
        $job['asset_publication']=['status'=>'queued'];
    }elseif($action==='photo'){
        $person=(string)$input['person'];$cid=(string)$input['candidate'];$photo=$job['review']['photos'][$person] ?? null;
        $choice=null;foreach($photo['candidates'] ?? [] as $candidate)if($candidate['id']===$cid)$choice=$candidate;
        if(!$choice||empty($choice['portrait_uri'])||empty($choice['sha256']))throw new InvalidArgumentException('Unknown photo candidate');
        if(!empty($choice['rejected']))throw new WorkflowConflict('This image was rejected');
        if(($choice['kind'] ?? '')==='photo'&&($choice['origin'] ?? '')!=='curated_cache'&&empty($choice['square_asset']))throw new WorkflowConflict('Wait for the vision crop');
        foreach($job['photo_requests'] ?? [] as $r)if($r['person']===$person&&in_array($r['status'],['queued','starting','running'],true))throw new WorkflowConflict('Wait for the photo revision');
        if($job['stages']['plan']['status']!=='pending')throw new WorkflowConflict('Rendering inputs are frozen');
        if(($job['approved_photos'][$person]['id']??null)!==$choice['id'])review_touch($job,'photo',$person);
        $job['approved_photos'][$person]=$choice;
        $job['asset_publication']=['status'=>'queued'];
        event($state,$id,'Photo approved for '.$photo['name']);
        $pending=array_filter(array_keys($job['review']['photos']),fn($key)=>empty($job['approved_photos'][$key]));
        if(!$pending&&!cards_pending($job)&&$job['stages']['enrich']['status']==='needs_review'){
            $job['stages']['enrich']['status']='pending';
            if($job['status']==='needs_review')$job['status']=count(array_filter($job['stages'],fn($s)=>in_array($s['status'],['starting','running'],true)))?'running':'queued';
        }
    }elseif(in_array($action,['title','publish'],true)){
        if($action==='title'){
            if(in_array($job['stages']['upload']['status'],['starting','running'],true))throw new WorkflowConflict('Wait until the upload finishes before changing its title');
            if(array_key_exists('title',$input)){
                if(!is_string($input['title']))throw new InvalidArgumentException('Invalid title');
                $title=trim($input['title']);
                if($title===''||mb_strlen($title)>100||preg_match('/[<>\x00-\x1f\x7f]/u',$title))throw new InvalidArgumentException('Invalid title');
            }else{
                $index=(int)($input['index'] ?? -1);$candidate=$job['review']['titles'][$index] ?? null;
                if(!$candidate)throw new InvalidArgumentException('Unknown title');
                $title=$candidate['title'];
            }
            foreach($job['video_actions'] ?? [] as $previous)if($previous['kind']==='title'&&in_array($previous['status'],['queued','starting','running'],true)&&$previous['title']!==$title)throw new WorkflowConflict('Wait until the current title update finishes');
            if(($job['selected_title']??null)!==$title)review_touch($job,'title');
            $job['selected_title']=$title;
            if(empty($job['stages']['upload']['result']['video_id'])){$job['title']=$title;event($state,$id,'Video title saved');return ['status'=>'selected'];}
        }
        $upload=$job['stages']['upload']['result'] ?? [];
        if($job['stages']['upload']['status']!=='complete'||empty($upload['postprocessing_complete'])||empty($upload['video_id']))throw new WorkflowConflict('Upload post-processing is incomplete');
        if($action==='publish'&&$job['privacy']!=='unlisted')throw new WorkflowConflict('Video is not unlisted');
        $key=hash('sha256',json_encode([$id,$action,$job['selected_title'] ?? '',$upload['video_id']]));
        if(($job['video_actions'][$key]['status'] ?? '')==='failed')unset($job['video_actions'][$key]);
        if($action==='title'&&($job['video_actions'][$key]['status'] ?? '')==='complete'&&$job['title']!==$job['selected_title'])unset($job['video_actions'][$key]);
        $job['video_actions'][$key] ??= ['id'=>$key,'kind'=>$action,'status'=>'queued','video_id'=>$upload['video_id'],
            'title'=>$job['selected_title'] ?? $job['title'],'revision'=>$job['review']['revision']];
    }else throw new InvalidArgumentException('Unknown review command');
    return ['status'=>$job['status']];
}
