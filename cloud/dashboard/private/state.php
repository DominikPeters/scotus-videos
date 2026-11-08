<?php
declare(strict_types=1);
class WorkflowConflict extends RuntimeException {}
require_once __DIR__ . '/recovery.php';
require_once __DIR__ . '/reviews.php';
require_once __DIR__ . '/clips.php';
require_once __DIR__ . '/photos.php';
require_once __DIR__ . '/podcast.php';
require_once __DIR__ . '/statistics.php';
require_once __DIR__ . '/cleanup.php';
require_once __DIR__ . '/spotify.php';
require_once __DIR__ . '/push.php';
require_once __DIR__ . '/research.php';
require_once __DIR__ . '/attempts.php';
require_once __DIR__ . '/maintenance.php';
require_once __DIR__ . '/card_import.php';
require_once __DIR__ . '/deployment.php';

/** All worker updates merge under this lock, then replace the JSON atomically. */
function transaction(string $name, callable $change): mixed {
    global $privateDir;
    $lock = fopen($privateDir . '/' . $name . '.lock', 'c');
    if (!$lock || !flock($lock, LOCK_EX)) throw new RuntimeException('State unavailable');
    try {
        $path = $privateDir . '/' . $name . '.json';
        $state = is_file($path) ? json_decode(file_get_contents($path), true, 512, JSON_THROW_ON_ERROR) : [];
        $result = $change($state);
        $temporary = tempnam($privateDir, '.state-');
        chmod($temporary, 0600);
        $encoded = json_encode($state, JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
        $stream = fopen($temporary, 'wb');
        if (!$stream || fwrite($stream, $encoded) !== strlen($encoded)) {
            if ($stream) fclose($stream);
            unlink($temporary); throw new RuntimeException('State write failed');
        }
        fflush($stream);
        if (function_exists('fsync')) fsync($stream);
        fclose($stream);
        if (!rename($temporary, $path)) throw new RuntimeException('State replace failed');
        return $result;
    } finally { flock($lock, LOCK_UN); fclose($lock); }
}

function initial_state(): array {
    return ['schema_version' => 1, 'paused' => true, 'jobs' => [], 'events' => [], 'nonces' => []];
}

function public_state(array $state,bool $internal=false): array {
    global $config;
    $state = json_decode(json_encode($state, JSON_THROW_ON_ERROR), true, 512, JSON_THROW_ON_ERROR);
    if(!empty($state['deployment_hold'])){$state['paused']=true;$state['deployment_message']='A deployment is in progress; processing will resume when it completes.';}
    unset($state['nonces'], $state['auth_leases'], $state['credential_logins'], $state['login_starts']);
    unset($state['notifications']);
    unset($state['statistics']['token'],$state['statistics']['data_uri']);
    // Endpoints and keys stay private; the page sees which devices are registered.
    $state['push']=['badge'=>attention_count($state),'public_key'=>(string)($config['push_public_key'] ?? ''),'devices'=>array_values(array_map(
        fn($s)=>array_intersect_key($s,array_flip(['id','label','created_at','last_sent_at'])),$state['push_subscriptions'] ?? []))];
    unset($state['push_subscriptions']);
    $state['spotify_enabled']=!empty($config['spotify_enabled']);
    foreach($state['jobs'] as &$item)if(isset($item['spotify']))unset($item['spotify']['lease'],$item['spotify']['dispatch_token'],$item['spotify']['claim_id'],$item['spotify']['expires']);
    foreach($state['jobs'] as &$item)if(isset($item['asset_publication']))unset($item['asset_publication']['lease'],$item['asset_publication']['dispatch_token']);
    foreach($state['jobs'] as &$item)if(isset($item['clips']))foreach($item['clips'] as &$clip){if(isset($clip['instagram']))$clip['instagram']['caption_locked']=!empty($clip['instagram_checkpoint']);unset($clip['lease'],$clip['dispatch_token'],$clip['upload'],$clip['tiktok_checkpoint'],$clip['instagram_checkpoint'],$clip['source_plan'],$clip['audio_uri']);}
    foreach($state['jobs'] as &$item)if(isset($item['video_actions']))foreach($item['video_actions'] as &$action)unset($action['lease'],$action['dispatch_token']);
    foreach($state['jobs'] as &$item)if(isset($item['photo_requests']))foreach($item['photo_requests'] as &$request)unset($request['lease'],$request['dispatch_token']);
    if (isset($state['recoveries'])) foreach ($state['recoveries'] as &$rec) {
        unset($rec['lease'],$rec['dispatch_token'],$rec['session_uri'],$rec['rollout_path'],$rec['actions']);
    }
    foreach ($state['jobs'] as &$job) {
        review_versions($job);
        unset($job['review']['legacy_revision'],$job['review']['legacy_versions']);
        unset($job['card_research']);
        unset($job['dispatch_token']);if(isset($job['chunk_cleanup']))unset($job['chunk_cleanup']['lease'],$job['chunk_cleanup']['expires']);
        foreach ($job['stages'] as &$stage) {
            unset($stage['lease'], $stage['dispatch_token'], $stage['checkpoint']);
            if (isset($stage['tasks'])) foreach ($stage['tasks'] as &$task) unset($task['lease']);
        }
    }
    // The dispatcher needs launch receipts and import inputs to reconcile crashes.
    // Browser polling receives only the current import's reviewable status.
    foreach($state['jobs'] as &$job){
        if(!$internal&&isset($job['card_import']))$job['card_import']=array_intersect_key($job['card_import'],array_flip(['id','status','card_count','created_at','finished_at','progress','error']));
    }
    unset($job);
    $strip=function(array &$value)use(&$strip,$internal):void{
        foreach($value as $key=>&$child)if(is_array($child)){
            if($key==='_launch'){if($internal)unset($child['token_hash']);else unset($value[$key]);}
            else $strip($child);
        }
    };
    $strip($state);return $state;
}

function reconcile_expired(array &$state): void {
    foreach($state['jobs'] as &$clipJob)foreach($clipJob['clips']??[] as $clipKey=>$clipValue)if(in_array($clipValue['status'],['starting','rendering','uploading'],true)&&($clipValue['expires']??0)<time()){
        $clipJob['clips'][$clipKey]['status']='failed';$clipJob['clips'][$clipKey]['error']='The clip worker expired. Retry preserves any saved YouTube upload identity.';unset($clipJob['clips'][$clipKey]['lease'],$clipJob['clips'][$clipKey]['dispatch_token']);
    }

    foreach($state['source_watches'] ?? [] as $id=>$watch)if(!in_array($watch['status'],['found','expired'],true)&&time()>=strtotime($watch['ends_at']))$state['source_watches'][$id]['status']='expired';
    reconcile_reviews($state);
    photo_reconcile($state);
    spotify_reconcile($state);
    foreach ($state['jobs'] as $id => &$job) {
        if (!in_array($job['status'], ['queued', 'running','needs_review'], true)) continue;
        foreach ($job['stages'] as $name => &$stage) {
            $expired = $stage['status'] === 'starting' && strtotime($stage['started_at'] ?? 'now') < time() - 600;
            $targets = $stage['tasks'] ?? [$stage];
            foreach ($targets as $target) {
                if (($target['status'] ?? '') === 'running' && ($target['lease']['expires'] ?? 0) <= time()) $expired = true;
            }
            if (!$expired) continue;
            if(!empty($stage['_launch'])||!empty($stage['cloud_operation']))continue;
            $stage['status'] = 'failed'; $stage['error'] = 'worker_failed';
            unset($stage['dispatch_token'], $stage['lease']); $job['status'] = 'failed';
            event($state, $id, $name . ': worker stopped reporting progress');
            break;
        }
    }
    foreach($state['jobs'] as $id=>&$job){
        foreach($job['video_actions'] ?? [] as $aid=>$action)if(empty($action['_launch'])&&in_array($action['status'],['starting','running'],true)&&($action['expires'] ?? 0)<=time()){
            $job['video_actions'][$aid]['status']='failed';unset($job['video_actions'][$aid]['lease'],$job['video_actions'][$aid]['dispatch_token']);event($state,$id,'Video action stopped reporting; review before retry');
        }
        if(empty($job['asset_publication']['_launch'])&&in_array($job['asset_publication']['status'] ?? '',['starting','running'],true)&&($job['asset_publication']['expires'] ?? 0)<=time()){
            $job['asset_publication']['status']='failed';unset($job['asset_publication']['lease'],$job['asset_publication']['dispatch_token']);event($state,$id,'Portrait commit needs review');
        }
    }
    reconcile_recoveries($state);
}

function event(array &$state, string $job, string $message): void {
    $state['events'][] = ['at' => gmdate('c'), 'job' => $job, 'message' => $message];
    $state['events'] = array_slice($state['events'], -200);
}

function add_job(array &$state, array $input): array {
    $docket = trim((string)($input['docket'] ?? ''));
    $date = (string)($input['argument_date'] ?? '');
    $recording = (string)($input['recording'] ?? 'argument-1');
    if (!preg_match('/^\d{2}(?:-\d+|[A-Z]\d+)$/D', $docket) ||
        !preg_match('/^\d{4}-\d{2}-\d{2}$/D', $date) ||
        !preg_match('/^[a-z0-9-]{1,40}$/D', $recording)) throw new InvalidArgumentException('Invalid recording identity');
    $parsed = DateTimeImmutable::createFromFormat('!Y-m-d', $date);
    if (!$parsed || $parsed->format('Y-m-d') !== $date) throw new InvalidArgumentException('Invalid argument date');
    $id = $date . '-' . $docket . '-' . $recording;
    if (isset($state['jobs'][$id])) return $state['jobs'][$id];
    foreach (['pdf_url', 'audio_url'] as $key) {
        $url = (string)($input[$key] ?? '');
        $parts = parse_url($url);
        if (!$parts || ($parts['scheme'] ?? '') !== 'https' ||
            !in_array($parts['host'] ?? '', ['www.supremecourt.gov', 'supremecourt.gov'], true) ||
            isset($parts['user']) || isset($parts['pass']) || isset($parts['port'])) {
            throw new InvalidArgumentException('Use official Court PDF and audio URLs');
        }
    }
    $stages = [];
    foreach (['prepare', 'enrich', 'align', 'plan', 'render', 'assemble', 'upload'] as $stage) {
        $stages[$stage] = ['status' => 'pending', 'attempt' => 0, 'progress' => 0];
    }
    $job = ['id' => $id, 'docket' => $docket, 'argument_date' => $date,
            'recording' => $recording, 'title' => mb_substr((string)($input['title'] ?? $docket), 0, 100),
            'case_name' => mb_substr((string)($input['case_name'] ?? $docket), 0, 300),
            'pdf_url' => $input['pdf_url'], 'audio_url' => $input['audio_url'],
            'status' => 'queued', 'created_at' => gmdate('c'), 'updated_at' => gmdate('c'),
            'privacy' => 'unlisted', 'stages' => $stages];
    $state['jobs'][$id] = $job;
    event($state, $id, 'Recording queued');
    return $job;
}

function work_enabled(array $state, array $job): bool {
    return empty($state['deployment_hold'])&&(!$state['paused'] || !empty($job['run_requested']));
}

function workflow_stage_order(): array {
    return ['prepare','align','enrich','plan','render','assemble','upload'];
}

/** Reserve model access at dispatch, including workers not yet holding auth. */
function codex_work_reserved(array $state): bool {
    if(($state['auth_leases']['codex']['expires'] ?? 0)>time()||photo_active($state))return true;
    foreach($state['jobs'] as $job)if($job['status']!=='cancelled'&&in_array($job['stages']['enrich']['status'] ?? '',['starting','running'],true))return true;
    foreach($state['recoveries'] ?? [] as $rec)if(in_array($rec['status'],['starting','running'],true)&&($rec['expires'] ?? 0)>time())return true;
    return in_array($state['statistics']['status'] ?? '',['starting','running'],true)&&($state['statistics']['expires'] ?? 0)>time();
}

function removed_render_chunks(array $job): array {
    $deleted=$job['chunk_cleanup']['deleted_indices'] ?? [];$missing=[];
    foreach($job['stages']['render']['tasks'] ?? [] as $index=>$task){
        if(!empty($task['result']['video_deleted_at'])||in_array($index,$deleted,true))$missing[]=$index;
    }
    return $missing;
}

function command(array &$state, array $input): array {
    $action = $input['command'] ?? '';
    if($action==='stats_check'){$state['statistics']['requested']=true;unset($state['statistics']['retry_after']);return ['status'=>'queued'];}
    if($action==='stats_answer'){
        $key=(string)$input['case'];$answer=trim((string)$input['answer']);
        if(!isset($state['statistics']['questions'][$key])||$answer===''||mb_strlen($answer)>4000)throw new InvalidArgumentException('Invalid statistics answer');
        $state['statistics']['answers'][$key]=$answer;unset($state['statistics']['questions'][$key]);$state['statistics']['requested']=true;return ['status'=>'queued'];
    }
    if (in_array($action, ['pause', 'resume'], true)) {
        $state['paused'] = $action === 'pause';
        event($state, '', $state['paused'] ? 'New work paused' : 'New work resumed');
        return ['paused' => $state['paused']];
    }
    $id = $input['job'] ?? '';
    if (!isset($state['jobs'][$id])) throw new InvalidArgumentException('Unknown recording');
    $job =& $state['jobs'][$id];
    if($action==='upload_corrected')return upload_corrected_recording($state,$id);
    if($action==='research_resume'){
        if(empty($job['research_attention'])||$job['stages']['enrich']['status']!=='needs_review')throw new WorkflowConflict('Research is not waiting for a decision');
        $phase=$job['research_attention']['phase']??'';
        if(in_array($phase,['haiku','terra','editor','review'],true)&&isset($job['card_research']['checkpoint']['plan']['hybrid'])){
            $hybrid=&$job['card_research']['checkpoint']['plan']['hybrid'];
            if($phase==='editor'&&($hybrid['calls']['editor']??0)>0&&empty($input['allow_opus_retry']))throw new WorkflowConflict('Explicitly authorize another Opus pass');
            $hybrid['calls'][$phase]=0;$hybrid['tool_calls'][$phase]=0;
            $hybrid['authorized_retries'][$phase]=($hybrid['authorized_retries'][$phase]??0)+1;
            $job['card_research']['version']++;unset($job['card_research']['operation_id']);
        }
        unset($job['research_attention'],$job['stages']['enrich']['retry_after']);$job['stages']['enrich']['status']='pending';$job['status']='queued';$job['run_requested']=true;
        event($state,$id,'Owner resumed saved card research');
    } elseif ($action === 'start') {
        if ($job['status'] !== 'queued') throw new InvalidArgumentException('Only queued recordings can be started');
        if (empty($job['run_requested'])) {
            $job['run_requested'] = true;
            event($state, $id, 'Recording start requested');
        }
    } elseif ($action === 'cancel') {
        unset($job['run_requested']);
        $job['status'] = 'cancelled';
        foreach ($job['stages'] as &$stage) {
            if ($stage['status'] !== 'complete') { $stage['status'] = 'cancelled'; unset($stage['lease']); }
        }
        event($state, $id, 'Cancellation requested');
    } elseif ($action === 'retry') {
        if (!in_array($job['status'], ['failed', 'cancelled'], true)) throw new InvalidArgumentException('Only failed or cancelled work can be retried');
        if (($job['stages']['upload']['error'] ?? '') === 'upload_uncertain') throw new InvalidArgumentException('Upload needs reconciliation before retry');
        // A manual retry must restore deleted inputs before attempting assembly.
        $missing=removed_render_chunks($job);
        if($job['stages']['assemble']['status']!=='complete'&&$missing){
            if(($job['chunk_cleanup']['expires'] ?? 0)>time())throw new RuntimeException('Wait for chunk cleanup to finish before retrying');
            foreach($missing as $index)$job['stages']['render']['tasks'][$index]=['status'=>'pending','progress'=>0];
            $job['stages']['render']['status']='pending';unset($job['chunk_cleanup']);
        }
        foreach ($job['stages'] as &$stage) {
            if ($stage['status'] !== 'complete' && !in_array($stage['status'],['starting','running','needs_review'],true)) {
                $stage['status'] = 'pending'; unset($stage['lease'], $stage['error'], $stage['dispatch_token'],$stage['cloud_operation'],$stage['cloud_operation_recorded_at']);
                if (isset($stage['tasks'])) foreach ($stage['tasks'] as &$task) {
                    if ($task['status'] !== 'complete') { $task['status'] = 'pending'; $task['progress'] = 0; unset($task['lease']); }
                }
            }
        }
        $job['status'] = count(array_filter($job['stages'],fn($s)=>$s['status']==='needs_review'))?'needs_review':'queued'; event($state, $id, 'Incomplete work queued again');
    } else { throw new InvalidArgumentException('Unknown command'); }
    $job['updated_at'] = gmdate('c');
    return ['id' => $id, 'status' => $job['status']];
}

function worker_update(array &$state, array $input, string $role): mixed {
    $op = $input['op'] ?? '';
    if($op==='rerender')return rerender_recording($state,$input,$role);
    if($op==='deployment_rebase')return deployment_rebase($state,$input,$role);
    if($role==='dispatcher'&&in_array($op,['deployment_hold','deployment_release'],true)){
        $id=(string)($input['release_id']??'');if(!preg_match('/^worker-[a-zA-Z0-9-]{1,60}$/D',$id))throw new InvalidArgumentException('Invalid deployment');
        if(!empty($state['deployment_hold'])&&$state['deployment_hold']['id']!==$id)throw new WorkflowConflict('Another deployment is in progress');
        if($op==='deployment_hold')$state['deployment_hold']=['id'=>$id];else unset($state['deployment_hold']);return ['held'=>$op==='deployment_hold','user_paused'=>$state['paused']];
    }
    if(str_starts_with($op,'card_import_'))return card_import_operation($state,$input,$role);
    if(str_starts_with($op,'source_refresh_'))return source_refresh_operation($state,$input,$role);
    if(str_starts_with($op,'launch_'))return launch_operation($state,$input,$role);
    if(in_array($op,['research_load','research_save'],true))return research_operation($state,$input,$role);
    if(in_array($op,['stats_dispatch','stats_start','stats_update','stats_dispatched','stats_dispatch_failed','stats_execution_closed'],true))return statistics_operation($state,$input,$role);
    if(in_array($op,['chunk_cleanup_claim','chunk_cleanup_result'],true))return chunk_cleanup_operation($state,$input,$role);
    if(in_array($op,['podcast_export','podcast_export_status','transcript_export','podcast_artwork'],true))return podcast_operation($state,$input,$role);
    if($role==='dispatcher'&&$op==='source_watch_claim'){
        $id=(string)($input['watch'] ?? '');$watch=&$state['source_watches'][$id];
        if(!$watch || in_array($watch['status'],['found','expired'],true))return false;
        $now=time();
        if($now>=strtotime($watch['ends_at'])){$watch['status']='expired';event($state,'','Source watch expired: '.$watch['case_name']);return false;}
        if($now<strtotime($watch['starts_at'])||$now<($watch['next_check_at'] ?? 0))return false;
        $watch['status']='polling';$watch['last_checked_at']=gmdate('c');$watch['next_check_at']=$now+350;
        $watch['checks']=($watch['checks'] ?? 0)+1;return $watch;
    }
    if($role==='dispatcher'&&$op==='source_watch_result'){
        $id=(string)($input['watch'] ?? '');$watch=&$state['source_watches'][$id];
        if(!$watch)throw new RuntimeException('Unknown source watch');
        if($watch['status']==='found')return ['found'=>true,'job'=>$watch['job']];
        $watch['last_error']=$input['error'] ?? null;
        $record=$input['recording'] ?? null;
        if(!$record)return ['found'=>false];
        if($record['docket']!==$watch['docket']||$record['argument_date']!==$watch['argument_date'])throw new RuntimeException('Watched recording differs');
        $job=add_job($state,$record);
        if($job['status']==='queued')command($state,['command'=>'start','job'=>$job['id']]);
        $watch['status']='found';$watch['found_at']=gmdate('c');$watch['job']=$job['id'];
        event($state,$job['id'],'Scheduled source watch found audio and transcript; automatic start requested');
        return ['found'=>true,'job'=>$job['id']];
    }
    if(str_starts_with($op,'clip_'))return clip_operation($state,$input,$role);
    if(str_starts_with($op,'spotify_'))return spotify_operation($state,$input,$role);
    if(str_starts_with($op,'photo_'))return photo_operation($state,$input,$role);
    if(in_array($op,['notification_claim','notification_finish','asset_publish_dispatch','asset_publish_claim','asset_publish_finish','asset_portrait_export','review_context','card_context','review_candidate_add','enrichment_review','video_action_claim','video_action_finish','video_action_dispatch'],true))return review_operation($state,$input,$role);
    if ($op==='recoveries' || str_starts_with($op,'recovery_')) return recovery_operation($state,$input,$role);
    if($role==='enrich'&&$op==='editorial_library'){
        $photos=[];$titles=[];
        foreach($state['jobs'] as $item){
            foreach($item['approved_photos'] ?? [] as $person=>$candidate){$name=$item['review']['photos'][$person]['name'] ?? '';if($name)$photos[$name]=$candidate;}
            if(!empty($item['stages']['upload']['result']['video_id']))$titles[]=['video_id'=>$item['stages']['upload']['result']['video_id'],'title'=>$item['title']];
        }return ['photos'=>(object)$photos,'titles'=>$titles];
    }
    if($role==='dispatcher'&&$op==='discovery_context')return ['paused'=>$state['paused'],'calendar'=>$state['discovery_calendar'] ?? (object)[],'calendar_retry_after'=>$state['discovery_calendar_retry_after'] ?? 0,'jobs'=>(object)array_map(fn($job)=>array_intersect_key($job,array_flip(['docket','argument_date','audio_url','pdf_url'])),$state['jobs'])];
    if($role==='dispatcher'&&$op==='discovery_calendar'){
        if(isset($input['calendar'])){$state['discovery_calendar']=$input['calendar'];unset($state['discovery_calendar_retry_after']);}
        else{$state['discovery_calendar_retry_after']=time()+3600;event($state,'','Argument calendar check failed; normal discovery continues.');}
        return true;
    }
    if($role==='dispatcher'&&$op==='discovery_claim'){
        if($state['paused'])return false;
        $seconds=max(300,min(3600,(int)($input['seconds'] ?? 1800)));
        $last=$state['discovery_last_check'] ?? 0;
        if(intdiv($last,$seconds)===intdiv(time(),$seconds))return false;
        $state['discovery_last_check']=time();$state['discovery_after']=time()+$seconds;return true;
    }
    if($role==='dispatcher'&&$op==='discovery_add'){
        $added=0;foreach(array_slice($input['records'] ?? [],0,200) as $record){
            $identity=$record['argument_date'].'-'.$record['docket'];
            if(in_array($identity,$input['uploaded'] ?? [],true))continue;
            $before=count($state['jobs']);add_job($state,$record);$added+=count($state['jobs'])-$before;
        }return ['added'=>$added];
    }
    if($op==='upload_audit_context'&&$role==='upload'){
        $job=$state['jobs'][$input['job']] ?? null;if(!$job)throw new RuntimeException('Unknown recording');
        $found=false;foreach($state['recoveries'] ?? [] as $rec)if($rec['job']===$job['id']&&($rec['actions'][$input['action_id']]['kind'] ?? '')==='upload_audit')$found=true;
        if(!$found)throw new RuntimeException('Unknown upload audit');return $job;
    }
    if ($role === 'dispatcher' && $op === 'snapshot') { reconcile_expired($state); return public_state($state,true); }
    if ($role === 'dispatcher' && $op === 'reserve_control_nonce') {
        $nonce = (string)($input['nonce'] ?? '');
        if (!preg_match('/^[a-f0-9]{32}$/D', $nonce) || isset($state['nonces']['control-' . $nonce])) throw new RuntimeException('Request already used');
        $state['nonces']['control-' . $nonce] = time(); return true;
    }
    if ($role === 'dispatcher' && $op === 'login_begin') return login_begin($state, $input);
    if (in_array($role, ['dispatcher', 'codex'], true) && in_array($op, ['login_update', 'login_check'], true)) {
        $id = (string)($input['id'] ?? '');
        $login =& $state['credential_logins'][$id];
        if (!$login || !hash_equals($login['token_hash'], hash('sha256', (string)($input['token'] ?? '')))) throw new RuntimeException('Unknown sign-in attempt');
        expire_login($login);
        if (!in_array($login['status'], ['starting', 'pending'], true)) return ['status' => $login['status']];
        if ($op === 'login_update') {
            $status = $input['status'] ?? '';
            if (!in_array($status, ['pending', 'complete', 'failed'], true)) throw new InvalidArgumentException('Invalid sign-in status');
            $login['status'] = $status;
            if ($status === 'pending') {
                if (($input['verification_url'] ?? '') !== 'https://auth.openai.com/codex/device' ||
                    !preg_match('/^[A-Z0-9-]{6,20}$/D', (string)($input['user_code'] ?? ''))) throw new InvalidArgumentException('Invalid device instructions');
                $login['verification_url'] = $input['verification_url']; $login['user_code'] = $input['user_code'];
            } else { unset($login['verification_url'], $login['user_code']); }
        }
        return ['status' => $login['status']];
    }
    if (in_array($op, ['auth_claim', 'auth_check', 'auth_release'], true)) {
        $name = $input['name'] ?? '';
        if (!in_array($name, ['youtube', 'codex', 'claude', 'github','spotify','instagram','tiktok'], true) ||
            !($role === 'dispatcher' || ($role==='enrich'&&$name==='claude') || ($role==='spotify'&&$name==='spotify') || ($role === 'upload' && in_array($name,['youtube','tiktok','instagram'],true)) || ($role==='assets'&&$name==='github') || (in_array($role,['codex','recovery','enrich','stats'],true) && $name === 'codex'))) throw new RuntimeException('Credential access denied');
        $state['auth_leases'] ??= [];
        $saved = $state['auth_leases'][$name] ?? null;
        if ($op === 'auth_claim') {
            $identity=(string)($input['claim_id'] ?? '');
            if($identity!==''&&!preg_match('/^[a-f0-9]{32}$/D',$identity))throw new InvalidArgumentException('Invalid auth claim identity');
            if ($saved && $saved['expires'] > time()) {
                if($identity!==''&&($saved['role'] ?? '')===$role&&hash_equals($saved['claim_id'] ?? '',$identity))return $saved['token'];
                return null;
            }
            $token = bin2hex(random_bytes(24));
            $state['auth_leases'][$name] = ['token' => $token, 'expires' => time() + 180, 'role' => $role,'claim_id'=>$identity];
            return $token;
        }
        if (!$saved || $saved['expires'] <= time() || $saved['role'] !== $role ||
            !hash_equals($saved['token'], (string)($input['token'] ?? ''))) throw new RuntimeException('Credential lease expired or replaced');
        if ($op === 'auth_release') unset($state['auth_leases'][$name]);
        else $state['auth_leases'][$name]['expires'] = time() + 180;
        return true;
    }
    $id = $input['job'] ?? '';
    if (!isset($state['jobs'][$id])) throw new InvalidArgumentException('Unknown recording');
    $job =& $state['jobs'][$id];
    $stageName = $input['stage'] ?? '';
    if (!isset($job['stages'][$stageName])) throw new InvalidArgumentException('Unknown stage');
    $stage =& $job['stages'][$stageName];
    $stageNames = array_keys($job['stages']);
    $index = array_search($stageName, $stageNames, true);
    $handoffStage=['assemble'=>'upload','prepare'=>'enrich'][$stageName] ?? null;
    if($role==='dispatcher' && $op==='execution_record'){
        if(!hash_equals($stage['dispatch_token'] ?? '',(string)($input['dispatch_token'] ?? '')))return false;
        $operation=(string)($input['operation'] ?? '');
        if(!preg_match('#^projects/[a-z0-9-]+/locations/[a-z0-9-]+/operations/[a-zA-Z0-9-]+$#D',$operation))throw new InvalidArgumentException('Invalid cloud operation');
        $stage['cloud_operation']=$operation;$stage['cloud_operation_recorded_at']=gmdate('c');
        if(isset($input['cloud_job'])){if(!preg_match('/^scotus-video-[a-z0-9-]+$/D',(string)$input['cloud_job']))throw new InvalidArgumentException('Invalid cloud job');$stage['cloud_job']=$input['cloud_job'];}
        if($handoffStage&&!empty($stage['handoff_id'])&&in_array($job['stages'][$handoffStage]['status'],['starting','running'],true)){$job['stages'][$handoffStage]['cloud_operation']=$operation;$job['stages'][$handoffStage]['cloud_operation_recorded_at']=gmdate('c');if(isset($stage['cloud_job']))$job['stages'][$handoffStage]['cloud_job']=$stage['cloud_job'];}
        return true;
    }
    if($role==='dispatcher' && $op==='execution_closed'){
        if(($stage['cloud_operation'] ?? '')!==($input['operation'] ?? '') ||
           !in_array($stage['status'],['starting','running'],true)||$job['status']==='cancelled')return false;
        if(isset($stage['_launch'])&&(!empty($stage['checkpoint']['video_id'])||empty($stage['checkpoint']['creation_pending']))&&($stage['administrative_retries']??0)<3){
            $stage['administrative_retries']=($stage['administrative_retries']??0)+1;
            foreach($stage['tasks']??[] as $n=>$task)if($task['status']!=='complete'){$stage['tasks'][$n]['status']='pending';unset($stage['tasks'][$n]['lease']);}
            $stage['status']='pending';$job['status']='queued';unset($stage['lease'],$stage['dispatch_token'],$stage['cloud_operation']);
            event($state,$id,$stageName.': resuming the interrupted attempt; saved results retained');return true;
        }
        // The cloud execution is closed, so no remaining task can finish safely.
        foreach($stage['tasks'] ?? [] as $n=>$task)if($task['status']!=='complete'){
            $stage['tasks'][$n]['status']='failed';unset($stage['tasks'][$n]['lease']);
        }
        $error=!empty($stage['checkpoint']['creation_pending'])&&empty($stage['checkpoint']['video_id'])?'upload_uncertain':'worker_failed';
        unset($stage['lease']);$stage['status']='failed';$stage['error']=$error;$job['status']='failed';
        $job['updated_at']=gmdate('c');
        $message='The cloud execution ended before all phase results were reported. Completed chunks are preserved; only unfinished work needs retry.';
        $rid=recovery_failure($state,$id,$stageName,$error,['fingerprint'=>hash('sha256','cloud_execution_closed'),'message'=>$message]);
        notify_event($state,$rid.'-cloud-'.$input['operation'],'recovery',$rid);
        recovery_log($state,$rid,'diagnosis',$message);event($state,$id,$stageName.': cloud execution ended with unfinished work');return true;
    }
    if ($role === 'dispatcher' && $op === 'dispatch') {
        if(($stage['retry_after']??0)>time())return null;
        if($stageName==='enrich'&&in_array($job['card_import']['status']??'',['queued','starting','running'],true))return null;
        // Enrichment includes annotation previews, which require aligned timings.
        if($stageName==='enrich'&&$job['stages']['align']['status']!=='complete')return null;
        if($stageName==='enrich'&&codex_work_reserved($state))return null;
        if($stageName==='assemble'&&removed_render_chunks($job))return null;
        if (!work_enabled($state, $job) || in_array($job['status'], ['cancelled', 'failed', 'complete'], true)) return null;
        if ($job['status']==='needs_review' && $stageName!=='align') return null;
        if ($stageName==='align') {
            if ($job['stages']['prepare']['status']!=='complete') return null;
        } elseif ($index && $job['stages'][$stageNames[$index - 1]]['status'] !== 'complete') return null;
        if ($stageName==='plan' && $job['stages']['enrich']['status']!=='complete') return null;
        foreach ($job['stages'] as $name=>$other) if ($name!==$stageName && in_array($other['status'],['starting','running'],true) && !(in_array($name,['enrich','align'],true)&&in_array($stageName,['enrich','align'],true))) return null;
        if ($stage['status'] !== 'pending') return null;
        unset($stage['cloud_operation'],$stage['cloud_operation_recorded_at'],$stage['cloud_job']);
        $baseline=(string)($input['release_id'] ?? $input['baseline_sha256'] ?? '');
        $release=$job['workflow_releases'][$stageName] ?? $state['reusable_repairs'][$baseline][$stageName] ?? $job['workflow_release'] ?? null;
        if($release)$stage['workflow_release']=$release;else unset($stage['workflow_release']);
        $stage['status'] = 'starting'; $stage['attempt']++;
        $stage['dispatch_token'] = bin2hex(random_bytes(24));
        $stage['started_at'] = gmdate('c'); if($job['status']!=='needs_review')$job['status'] = 'running';
        if ($stageName === 'render') {
            $count = (int)($job['stages']['plan']['result']['chunks'] ?? 0);
            if ($count < 1 || $count > 1000) throw new RuntimeException('Invalid render plan');
            if (!isset($stage['tasks']) || count($stage['tasks']) !== $count) $stage['tasks'] = array_fill(0, $count, ['status' => 'pending', 'progress' => 0]);
        }
        event($state, $id, 'Starting ' . $stageName);
        return ['job' => $job, 'dispatch_token' => $stage['dispatch_token'],'workflow_release'=>$release];
    }
    if ($role === 'dispatcher' && $op === 'dispatch_failed') {
        if (!hash_equals($stage['dispatch_token'] ?? '', (string)($input['dispatch_token'] ?? ''))) throw new RuntimeException('Stale dispatch');
        $stage['status'] = 'failed'; $stage['error'] = 'Cloud execution could not be started'; $job['status'] = 'failed';
        recovery_failure($state,$id,$stageName,'worker_failed');
        event($state, $id, 'Cloud execution could not be started'); return true;
    }
    if ($role !== $stageName) throw new RuntimeException('Worker role differs from stage');
    if (strlen($stage['dispatch_token'] ?? '') !== 48 || !hash_equals($stage['dispatch_token'], (string)($input['dispatch_token'] ?? ''))) throw new RuntimeException('Stale dispatch');
    if ($job['status'] === 'cancelled') return ['cancelled' => true];
    $target =& $stage;
    if ($stageName === 'render') {
        $task = (int)($input['task'] ?? -1);
        if (!isset($stage['tasks'][$task])) throw new InvalidArgumentException('Unknown render task');
        $target =& $stage['tasks'][$task];
    }
    $now = time();
    if ($op === 'claim') {
        // Fence stale launches made before the dependency gate was installed.
        // Deferring a launch is not a worker failure and must not start recovery.
        if($stageName==='enrich'&&$job['stages']['align']['status']!=='complete'){
            if(in_array($target['status'],['starting','running'],true)){
                $target['status']='pending';
                unset($target['lease'],$target['dispatch_token'],$target['cloud_operation'],$target['cloud_operation_recorded_at'],$target['cloud_job']);
                event($state,$id,'Research waiting for completed alignment');
            }
            return null;
        }
        if ($job['status'] === 'failed' && !(in_array($stageName,['enrich','align'],true)&&in_array($target['status'],['starting','running'],true))) return null;
        if ($target['status'] === 'complete') return ['complete' => true, 'result' => $target['result'] ?? null];
        $claimId=(string)($input['claim_id'] ?? '');
        if($claimId!==''&&!preg_match('/^[a-f0-9]{32}$/D',$claimId))throw new InvalidArgumentException('Invalid claim identity');
        if (isset($target['lease']) && $target['lease']['expires'] > $now) {
            if($claimId!=='' && hash_equals($target['lease']['claim_id'] ?? '',$claimId)){
                $target['lease']['expires']=$now+180;return ['lease'=>$target['lease']['token'],'job'=>$job];
            }
            return null;
        }
        $token = bin2hex(random_bytes(24));
        $target['lease'] = ['token' => $token, 'expires' => $now + 180,'claim_id'=>$claimId];
        if($stageName==='render')$target['started_at']=gmdate('c');
        $target['status'] = 'running'; $stage['status'] = 'running';
        return ['lease' => $token, 'job' => $job];
    }
    if($op==='finish'&&$handoffStage&&($target['status'] ?? '')==='complete'&&!empty($input['handoff_id'])&&hash_equals($target['handoff_id'] ?? '',(string)$input['handoff_id'])){
        $next=$job['stages'][$handoffStage];return ['next'=>in_array($next['status'],['starting','running'],true)?['stage'=>$handoffStage,'job'=>$job,'dispatch_token'=>$next['dispatch_token']]:null];
    }
    if (!isset($target['lease']) || $target['lease']['expires'] <= $now ||
        !hash_equals($target['lease']['token'], (string)($input['lease'] ?? ''))) throw new RuntimeException('Worker lease expired or replaced');
    if(in_array($op,['enrichment_checkpoint','research_defer'],true)){
        if($stageName!=='enrich'||$role!=='enrich')throw new WorkflowConflict('Card research access denied');
        if($op==='enrichment_checkpoint'){
            $uri=(string)($input['enrichment_uri']??'');if(!preg_match('#^gs://[a-z0-9.-]+/enrichment/'.preg_quote($id,'#').'/metadata-[a-f0-9]{64}\.json$#D',$uri))throw new InvalidArgumentException('Invalid editorial checkpoint');
            $stage['result']['enrichment_uri']=$uri;return true;
        }
        $kind=(string)($input['kind']??'provider');$message=mb_substr((string)($input['message']??'Research is waiting'),0,600);
        $manual=in_array($kind,['auth','setup','decision'],true);
        $stage['status']=$manual?'needs_review':'pending';$stage['retry_after']=time()+max(60,min(86400,(int)($input['retry_after']??900)));
        $job['status']=$manual?'needs_review':'queued';
        if($manual)$job['research_attention']=['kind'=>$kind,'message'=>$message,'phase'=>(string)($input['phase']??''),
            'another_editor_pass'=>($input['phase']??'')==='editor'&&($job['card_research']['checkpoint']['plan']['hybrid']['calls']['editor']??0)>0];
        if($manual)notify_event($state,$id.'-research-'.($input['phase']??'setup').'-'.($job['card_research']['version']??0),'case_review',$job['review']['id']??$id.'-review',$id);
        unset($stage['lease'],$stage['dispatch_token']);event($state,$id,'Card research: '.$message);return true;
    }
    if ($op === 'heartbeat') {
        $target['lease']['expires'] = $now + 180;
        $target['progress'] = max($target['progress'], min(1, max(0, (float)($input['progress'] ?? 0))));
        if ($stageName === 'render') $stage['progress'] = array_sum(array_column($stage['tasks'], 'progress')) / count($stage['tasks']);
        $job['updated_at'] = gmdate('c');
        return ['cancelled' => false];
    }
    if ($op === 'finish') {
        if($stageName==='upload'&&empty($input['result']['postprocessing_complete']))throw new RuntimeException('Upload post-processing incomplete');
        $target['status'] = 'complete'; $target['progress'] = 1;
        $target['finished_at']=gmdate('c');
        $target['result'] = $input['result'] ?? []; unset($target['lease']);
        if ($stageName !== 'render' || count(array_filter($stage['tasks'], fn($t) => $t['status'] !== 'complete')) === 0) {
            $stage['status'] = 'complete'; $stage['progress'] = 1; $stage['finished_at'] = gmdate('c');
            if ($stageName === 'upload') {
                if(empty($target['result']['postprocessing_complete']))throw new RuntimeException('Upload post-processing incomplete');
                $job['title']=$target['result']['title'] ?? $job['selected_title'] ?? $job['stages']['enrich']['result']['title'] ?? $job['title'];
                $privacy=$target['result']['privacy'] ?? 'unlisted';
                if(in_array($privacy,['public','unlisted','private'],true))$job['privacy']=$privacy;
                if(!empty($job['render_revision']['upload_requested_at'])&&($job['render_revision']['upload_sha256']??'')===($job['stages']['assemble']['result']['sha256']??''))$job['render_revision']['upload_matches_current']=true;
                $job['status'] = 'complete';notify_event($state,$id.'-ready-'.($target['result']['video_id'] ?? ''),'ready',$job['review']['id'] ?? '',$id);
            }
            event($state, $id, $stageName . ' complete');
            if($stageName==='assemble'&&($job['render_revision']['status']??'')==='queued'){
                $job['render_revision']['status']='complete';$job['render_revision']['finished_at']=gmdate('c');
                $job['status']='complete';event($state,$id,'Corrected MP4 is ready to download. The existing YouTube upload is unchanged.');
            }
            reconcile_recoveries($state);
        }
    } elseif ($op === 'note'){
        $message=(string)($input['message'] ?? '');if(mb_strlen($message)>1000)throw new RuntimeException('Worker note too long');event($state,$id,$message);
    } elseif ($op === 'checkpoint' && $stageName === 'upload') {
        $target['checkpoint'] = $input['checkpoint'] ?? [];
    } elseif ($op === 'fail') {
        if(($input['error']??'')==='transport'&&isset($stage['_launch'])){
            if(!empty($target['checkpoint']['creation_pending'])&&empty($target['checkpoint']['video_id']))$input['error']='upload_uncertain';
            else{$target['status']='pending';unset($target['lease']);$stage['status']='running';event($state,$id,$stageName.': connection interrupted; resuming saved work when the execution closes');return true;}
        }
        // Fixed error categories avoid leaking credentials or model output.
        $allowed = ['auth_required', 'invalid_inputs', 'alignment_review', 'worker_failed', 'upload_uncertain'];
        $error = in_array($input['error'] ?? '', $allowed, true) ? $input['error'] : 'worker_failed';
        $target['status'] = 'failed'; $stage['status'] = 'failed'; $stage['error'] = $error;
        $job['status'] = 'failed'; unset($target['lease']); event($state, $id, $stageName . ': ' . str_replace('_', ' ', $error));
        recovery_failure($state,$id,$stageName,$error,$input['diagnostic'] ?? []);
    } else { throw new InvalidArgumentException('Unknown worker operation'); }
    $job['updated_at'] = gmdate('c');
    if($op==='finish'&&$handoffStage&&!empty($input['continue_'.$handoffStage])){
        if(!work_enabled($state,$job))return ['next'=>null];
        $identity=(string)($input['handoff_id'] ?? '');
        if(!preg_match('/^[a-f0-9]{32}$/D',$identity))throw new InvalidArgumentException('Invalid phase handoff');
        $stage['handoff_id']=$identity;$next=&$job['stages'][$handoffStage];
        $baseline=(string)($input['release_id'] ?? $input['baseline_sha256'] ?? '');
        $patched=$job['workflow_releases'][$handoffStage] ?? $state['reusable_repairs'][$baseline][$handoffStage] ?? $job['workflow_release'] ?? null;
        if($next['status']!=='pending'||$patched||($handoffStage==='enrich'&&($job['stages']['align']['status']!=='complete'||codex_work_reserved($state))))return ['next'=>null];
        $next['status']='starting';$next['attempt']++;$next['started_at']=gmdate('c');$next['dispatch_token']=bin2hex(random_bytes(24));
        if(isset($stage['_launch'])){$next['_launch']=$stage['_launch'];$next['_launch']['owner']=['kind'=>'stage','job'=>$id,'stage'=>$handoffStage];}
        if(isset($stage['cloud_operation'])){$next['cloud_operation']=$stage['cloud_operation'];$next['cloud_operation_recorded_at']=gmdate('c');}if(isset($stage['cloud_job']))$next['cloud_job']=$stage['cloud_job'];
        event($state,$id,'Starting '.$handoffStage.' in the '.$stageName.' worker');
        return ['next'=>['stage'=>$handoffStage,'job'=>$job,'dispatch_token'=>$next['dispatch_token']]];
    }
    return true;
}

function expire_login(array &$login): void {
    if (in_array($login['status'], ['starting', 'pending'], true) && $login['expires'] <= time()) {
        $login['status'] = 'expired'; unset($login['verification_url'], $login['user_code']);
    }
}

function login_begin(array &$state, array $input): array {
    $owner = (string)($input['owner'] ?? '');
    if (!preg_match('/^[a-f0-9]{64}$/D', $owner)) throw new InvalidArgumentException('Invalid owner');
    $state['credential_logins'] ??= []; $state['login_starts'] ??= [];
    $state['login_starts'] = array_values(array_filter($state['login_starts'], fn($at) => $at > time() - 86400));
    if (count($state['login_starts']) >= min(3, max(1, (int)($input['daily_limit'] ?? 3)))) throw new RuntimeException('Daily sign-in limit reached');
    foreach ($state['credential_logins'] as &$existing) {
        expire_login($existing);
        if (in_array($existing['status'], ['starting', 'pending'], true)) throw new RuntimeException('Sign-in already running');
    }
    $state['credential_logins'] = array_filter($state['credential_logins'], fn($saved) => $saved['expires'] > time() - 86400);
    $id = bin2hex(random_bytes(16)); $token = bin2hex(random_bytes(24));
    $state['credential_logins'][$id] = ['id' => $id, 'owner' => $owner, 'token_hash' => hash('sha256', $token),
        'created_at' => gmdate('c'), 'expires' => time() + 840, 'status' => 'starting'];
    $state['login_starts'][] = time();
    return ['id' => $id, 'token' => $token];
}

function login_status(array &$state, string $owner, bool $cancel = false): ?array {
    $found = null;
    foreach ($state['credential_logins'] ?? [] as $id => $saved) {
        if (!hash_equals($saved['owner'], $owner)) continue;
        $login =& $state['credential_logins'][$id]; expire_login($login);
        if ($cancel && in_array($login['status'], ['starting', 'pending'], true)) {
            $login['status'] = 'cancelled'; unset($login['verification_url'], $login['user_code']);
        }
        $found = $login; unset($found['owner'], $found['token_hash']);
        $found['created_at'] ??= gmdate('c', $found['expires'] - 840);
    }
    return $found;
}
