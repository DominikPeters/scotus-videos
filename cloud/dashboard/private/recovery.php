<?php
declare(strict_types=1);

function recovery_log(array &$state, string $id, string $kind, string $message): void {
    if (!in_array($kind, ['diagnosis','repair','validation','retry','question','note','system'], true)) throw new InvalidArgumentException('Invalid log kind');
    $message = trim($message);
    if ($message === '' || mb_strlen($message) > 4000) throw new InvalidArgumentException('Invalid recovery message');
    $state['recoveries'][$id]['log'][] = ['at'=>gmdate('c'),'kind'=>$kind,'message'=>$message];
    $state['recoveries'][$id]['log'] = array_slice($state['recoveries'][$id]['log'], -100);
    $state['recoveries'][$id]['updated_at'] = gmdate('c');
}

function recovery_failure(array &$state, string $jobId, string $stageName, string $error, array $diagnostic = []): string {
    $state['recoveries'] ??= [];
    $job =& $state['jobs'][$jobId]; $stage =& $job['stages'][$stageName];
    $revision = hash('sha256', json_encode([$job['pdf_url'],$job['audio_url'], $job['stages']['prepare']['result'] ?? null], JSON_THROW_ON_ERROR));
    $fingerprint = (string)($diagnostic['fingerprint'] ?? hash('sha256',$error));
    if (!preg_match('/^[a-f0-9]{64}$/D',$fingerprint)) $fingerprint = hash('sha256',$error);
    $id = substr(hash('sha256', $jobId.'|'.$stageName.'|'.$revision.'|'.$fingerprint),0,32);
    $previous=$stage['recovery_id'] ?? '';
    if (isset($state['recoveries'][$previous]) && $state['recoveries'][$previous]['input_revision']===$revision &&
        !in_array($state['recoveries'][$previous]['status'],['cancelled','repaired'],true)) $id=$previous;
    // A later run can fail in exactly the same way after a successful repair.
    // Keep that completed recovery as history and open a fresh incident.
    if(isset($state['recoveries'][$id])&&in_array($state['recoveries'][$id]['status'],['cancelled','repaired'],true))$id=bin2hex(random_bytes(16));
    if (!isset($state['recoveries'][$id])) {
        $state['recoveries'][$id] = ['id'=>$id,'job'=>$jobId,'stage'=>$stageName,'input_revision'=>$revision,
            'fingerprint'=>$fingerprint,'status'=>'queued','turns'=>0,'authorized_turn_limit'=>6,'failures'=>0,'created_at'=>gmdate('c'),
            'updated_at'=>gmdate('c'),'log'=>[],'questions'=>[],'actions'=>[]];
        recovery_log($state,$id,'system',$stageName.' failed ('.str_replace('_',' ',$error).'). Recovery queued.');
    }
    $rec =& $state['recoveries'][$id]; $rec['failures']++;
    if (!empty($diagnostic)) $rec['diagnostic'] = $diagnostic;
    $rec['error'] = $error; $stage['recovery_id'] = $id;
    if ($rec['status'] === 'waiting_for_stage') {
        $rec['status'] = $rec['turns'] < ($rec['authorized_turn_limit'] ?? 2) ? 'queued' : 'unresolved';
        recovery_log($state,$id,'retry','The stage failed again after the repair attempt.');
    }
    return $id;
}

function reconcile_recoveries(array &$state): void {
    $state['recoveries'] ??= [];
    foreach ($state['jobs'] as $jobId=>$job) {
        if ($job['status'] !== 'failed') continue;
        foreach ($job['stages'] as $name=>$stage) if ($stage['status'] === 'failed' &&
            (!isset($stage['recovery_id'])||in_array($state['recoveries'][$stage['recovery_id']]['status'] ?? '',['repaired','cancelled'],true))) {
            recovery_failure($state,$jobId,$name,(string)($stage['error'] ?? 'worker_failed'));
        }
    }
    foreach ($state['recoveries'] as $id=>&$rec) {
        if(!in_array($rec['status'],['cancelled','repaired'],true))$rec['authorized_turn_limit']=max(6,$rec['authorized_turn_limit'] ?? 2);
        $job=$state['jobs'][$rec['job']];$stage=$job['stages'][$rec['stage']];
        $current=($stage['recovery_id'] ?? '')===$id;
        $active=$rec['status']==='running' && !empty($rec['lease']) && ($rec['expires'] ?? 0)>time();
        if($job['status']!=='cancelled' && $current && $stage['status']==='complete' &&
           !in_array($rec['status'],['repaired','cancelled'],true) && !$active){
            $rec['status']='repaired';$rec['finished_at']=$stage['finished_at'] ?? gmdate('c');
            $rec['resolution']='The affected phase completed successfully with its normal checks. No further recovery action is needed.';
            foreach($rec['questions'] as &$question)if($question['status']==='pending'){
                $question['status']='dismissed';$question['reason']='The affected phase completed successfully.';
            }
            unset($question,$rec['lease'],$rec['dispatch_token'],$rec['expires']);
            recovery_log($state,$id,'validation',$rec['resolution']);
            if(!empty($rec['reusable_release'])){
                $candidate=$rec['reusable_release'];$baseline=$candidate['release_id']??$candidate['baseline_sha256'];
                foreach($candidate['stages'] ?? [$rec['stage']] as $affected)$state['reusable_repairs'][$baseline][$affected]=[...$candidate,'validated_job'=>$rec['job'],'validated_at'=>$rec['finished_at']];
                recovery_log($state,$id,'validation','The tested, input-independent fix is now a default for future '.$rec['stage'].' phases on this source version.');
            }
            event($state,$rec['job'],ucfirst($rec['stage']).' recovery resolved');continue;
        }
        if (empty($rec['_launch']) && in_array($rec['status'],['starting','running'],true) && ($rec['expires'] ?? 0) <= time()) {
            $rec['status'] = $rec['turns'] < ($rec['authorized_turn_limit'] ?? 2) ? 'queued' : 'unresolved';
            unset($rec['lease'],$rec['dispatch_token']);
            recovery_log($state,$id,'system','The repair worker stopped reporting progress. Saved conversation history will be reused.');
        }
        if($current && !empty($rec['retry_requested']) && in_array($rec['status'],['queued','unresolved','waiting_for_resource'],true) &&
           in_array($stage['status'],['pending','starting','running'],true)){
            $rec['status']='waiting_for_stage';
            recovery_log($state,$id,'retry','The phase retry is already queued or running. Recovery will be verified when it finishes.');
        }
        if ($current && $rec['status'] === 'waiting_for_stage') {
            if ($stage['status'] === 'failed') {
                $rec['status'] = $rec['turns'] < ($rec['authorized_turn_limit'] ?? 2) ? 'queued' : 'unresolved';
                recovery_log($state,$id,'retry','The affected stage still failed.');
            }
        }
        if ($job['status'] === 'cancelled' && $rec['status']!=='repaired') {
            $rec['status']='cancelled'; unset($rec['lease'],$rec['dispatch_token']);
        }
    }
    recovery_attention_notifications($state);
}

function recovery_attention_notifications(array &$state): void {
    foreach($state['recoveries'] ?? [] as $id=>$rec){
        if(!in_array($rec['status'],['unresolved','waiting_for_resource'],true))continue;
        $job=$state['jobs'][$rec['job']];
        if($job['status']==='cancelled'||($job['stages'][$rec['stage']]['recovery_id'] ?? '')!==$id||$job['stages'][$rec['stage']]['status']==='complete')continue;
        notify_event($state,$id.'-attention-'.$rec['status'].'-'.($rec['turns'] ?? 0),'failure',$id,$rec['job']);
    }
}

function recovery_lease(array &$state, array $input): array {
    $id = (string)($input['recovery'] ?? '');
    $rec = $state['recoveries'][$id] ?? null;
    if (!$rec || $rec['status'] !== 'running' || ($rec['expires'] ?? 0) <= time() ||
        !hash_equals($rec['lease'] ?? '', (string)($input['lease'] ?? ''))) throw new RuntimeException('Recovery lease expired or replaced');
    if (($state['jobs'][$rec['job']]['stages'][$rec['stage']]['recovery_id'] ?? '') !== $id) throw new RuntimeException('Recovery was superseded');
    if ($state['jobs'][$rec['job']]['status'] === 'cancelled') throw new RuntimeException('Recording cancelled');
    return $rec;
}

function recovery_budget(array &$state, string $action, float $amount, int $seconds): bool {
    if (!is_finite($amount) || $amount <= 0 || $amount > 1 || $seconds < 1 || $seconds > 14400) throw new InvalidArgumentException('Invalid repair reservation');
    $state['repair_budget'] ??= ['daily_limit_usd'=>1.0,'days'=>[],'reservations'=>[]];
    if (isset($state['repair_budget']['reservations'][$action])) return true;
    $zone = new DateTimeZone('Europe/Paris');
    $start = (new DateTimeImmutable('now'))->setTimezone($zone);
    $end = $start->modify('+'.($seconds+300).' seconds');
    $days = array_unique([$start->format('Y-m-d'),$end->format('Y-m-d')]);
    foreach ($days as $day) if (($state['repair_budget']['days'][$day] ?? 0)+$amount > 1.0+1e-9) return false;
    foreach ($days as $day) $state['repair_budget']['days'][$day] = round(($state['repair_budget']['days'][$day] ?? 0)+$amount,6);
    $state['repair_budget']['reservations'][$action] = ['days'=>$days,'usd'=>$amount,'at'=>time()];
    return true;
}

function recovery_answer(array &$state, array $input): array {
    $id=(string)($input['recovery'] ?? ''); $qid=(string)($input['question'] ?? '');
    $rec =& $state['recoveries'][$id];
    if (!$rec || $rec['status'] !== 'needs_input' || !isset($rec['questions'][$qid]) ||
        $rec['questions'][$qid]['status'] !== 'pending' || ($input['revision'] ?? '') !== $rec['input_revision']) throw new RuntimeException('Question is stale or already answered');
    $question =& $rec['questions'][$qid]; $choice=(string)($input['choice'] ?? ''); $text=trim((string)($input['text'] ?? ''));
    if ($choice !== '' && !in_array($choice,array_column($question['options'],'id'),true)) throw new InvalidArgumentException('Unknown choice');
    if (($choice === '' && $text === '') || mb_strlen($text)>4000) throw new InvalidArgumentException('An answer is required');
    if ($state['jobs'][$rec['job']]['status'] !== 'failed' ||
        ($state['jobs'][$rec['job']]['stages'][$rec['stage']]['recovery_id'] ?? '')!==$id) throw new RuntimeException('Recording changed');
    $question['status']='answered'; $question['answer']=['choice'=>$choice,'text'=>$text,'at'=>gmdate('c')];
    recovery_log($state,$id,'note','Operator answered: '.($choice !== '' ? $choice : $text));
    if (count(array_filter($rec['questions'],fn($q)=>$q['status']==='pending')) === 0) {
        $rec['status']='queued'; $rec['authorized_turn_limit']=min(8,$rec['turns']+2);
    }
    return ['id'=>$id,'status'=>$rec['status']];
}

function recovery_command(array &$state,array $input): array {
    reconcile_recoveries($state);
    $id=(string)($input['recovery'] ?? ''); $rec =& $state['recoveries'][$id];
    if (!$rec) throw new InvalidArgumentException('Unknown recovery');
    if (($input['command'] ?? '')==='stop') {
        if($rec['status']==='repaired')return ['status'=>'repaired'];
        $rec['status']='cancelled'; unset($rec['lease'],$rec['dispatch_token']);
        recovery_log($state,$id,'system','Operator stopped automatic recovery.');
    } elseif (($input['command'] ?? '')==='resume') {
        if (!in_array($rec['status'],['unresolved','waiting_for_resource'],true) ||
            $state['jobs'][$rec['job']]['status']!=='failed' || $rec['turns']>=8) throw new RuntimeException('Recovery cannot resume');
        $rec['operator_resumes']=($rec['operator_resumes'] ?? 0)+1; $rec['status']='queued';
        $rec['authorized_turn_limit']=min(8,$rec['turns']+2);
        recovery_log($state,$id,'system','Operator requested another bounded recovery turn.');
    } else throw new InvalidArgumentException('Unknown recovery command');
    return ['status'=>$rec['status']];
}

function recovery_operation(array &$state, array $input, string $role): mixed {
    $op=$input['op']; $id=(string)($input['recovery'] ?? '');
    if ($role==='dispatcher' && $op==='recoveries') { reconcile_recoveries($state); return (object)($state['recoveries'] ?? []); }
    if ($role==='dispatcher' && $op==='recovery_dispatch') {
        if(!empty($state['deployment_hold']))return null;
        reconcile_recoveries($state); $rec =& $state['recoveries'][$id];
        if(($state['jobs'][$rec['job']]['maintenance']['status']??'')==='waiting'&&($state['jobs'][$rec['job']]['maintenance']['retry_after']??0)>time())return null;
        if(codex_work_reserved($state))return null;
        if (!$rec || $rec['status']!=='queued' || !work_enabled($state,$state['jobs'][$rec['job']])) return null;
        if ($rec['turns']>=min(8,$rec['authorized_turn_limit'] ?? 2)) {
            $rec['status']='unresolved';recovery_attention_notifications($state); return null;
        }
        if(($rec['retry_after']??0)>time())return null;
        $key=$id.'-launch-'.(($rec['launches']??0)+1);
        if (!recovery_budget($state,$key,(float)$input['reserve_usd'],(int)$input['seconds'])) {
            $rec['status']='waiting_for_resource';recovery_attention_notifications($state); recovery_log($state,$id,'system','The $1 daily repair reservation limit has been reached.'); return null;
        }
        $rec['launches']=($rec['launches']??0)+1;
        $rec['status']='starting'; $rec['dispatch_token']=bin2hex(random_bytes(24)); $rec['expires']=time()+900;unset($rec['turn_started']);
        return $rec;
    }
    if($role==='dispatcher'&&$op==='recovery_tests_ready'){
        $rec=&$state['recoveries'][$id];
        if(!$rec||$rec['status']!=='waiting_for_tests'||($rec['pending_action'] ?? '')!==($input['action_id'] ?? ''))return false;
        if($state['jobs'][$rec['job']]['status']==='cancelled')return false;
        if(isset($input['report']))$rec['actions'][$input['action_id']]['completion_report']=$input['report'];
        $rec['status']='queued';unset($rec['pending_action']);
        recovery_log($state,$id,'validation',!empty($input['passed'])?'Isolated checks completed successfully; recovery will resume automatically.':'Isolated checks returned findings; recovery will resume automatically to inspect them.');
        return true;
    }
    if ($role==='dispatcher' && $op==='recovery_dispatch_failed') {
        $rec =& $state['recoveries'][$id];
        if (!$rec || !hash_equals($rec['dispatch_token'] ?? '',(string)$input['dispatch_token'])) throw new RuntimeException('Stale recovery dispatch');
        $rec['status']='waiting_for_resource'; unset($rec['dispatch_token']);
        recovery_log($state,$id,'system','The cloud repair execution could not be confirmed. It will not be launched again blindly.'); return true;
    }
    if ($role==='recovery' && $op==='recovery_claim') {
        $rec =& $state['recoveries'][$id];
        $identity=(string)($input['claim_id'] ?? '');
        if($identity!==''&&!preg_match('/^[a-f0-9]{32}$/D',$identity))throw new InvalidArgumentException('Invalid recovery claim identity');
        if($rec && $identity!=='' && $rec['status']==='running' && ($rec['expires'] ?? 0)>time() &&
           hash_equals($rec['dispatch_token'] ?? '',(string)($input['dispatch_token'] ?? '')) && hash_equals($rec['claim_id'] ?? '',$identity)){
            return ['recovery'=>$rec,'job'=>public_state(['jobs'=>[$rec['job']=>$state['jobs'][$rec['job']]]])['jobs'][$rec['job']]];
        }
        if (!$rec || $rec['status']!=='starting' || $rec['expires']<=time() ||
            !hash_equals($rec['dispatch_token'] ?? '',(string)($input['dispatch_token'] ?? ''))) return null;
        $rec['lease']=bin2hex(random_bytes(24)); $rec['status']='running'; $rec['expires']=time()+180;$rec['claim_id']=$identity;
        recovery_log($state,$id,'system','Repair worker started; reasoning has not begun.');
        return ['recovery'=>$rec,'job'=>public_state(['jobs'=>[$rec['job']=>$state['jobs'][$rec['job']]]])['jobs'][$rec['job']]];
    }
    if (!in_array($role,['dispatcher','recovery'],true)) throw new RuntimeException('Recovery access denied');
    $rec=recovery_lease($state,$input); $saved =& $state['recoveries'][$id];
    if($op==='recovery_turn_begin'){
        if(empty($saved['turn_started'])){$saved['turns']++;$saved['turn_started']=true;recovery_log($state,$id,'system','Repair reasoning turn '.$saved['turns'].' started.');}
        return ['turns'=>$saved['turns']];
    }
    if($op==='recovery_defer'){
        $saved['administrative_retries']=($saved['administrative_retries']??0)+1;
        $saved['status']=$saved['administrative_retries']>=3?'waiting_for_resource':'queued';$saved['retry_after']=time()+60;
        recovery_log($state,$id,'system','Repair worker deferred before reasoning; saved work retained.');
        unset($saved['lease'],$saved['dispatch_token'],$saved['expires']);return true;
    }
    if ($op==='recovery_check') { $saved['expires']=time()+180; return ['status'=>$saved['status']]; }
    if($op==='recovery_wait'){
        $key=(string)$input['action_id'];
        if(!isset($saved['actions'][$key])||!in_array($saved['actions'][$key]['kind'],['tests','probe','upload_audit'],true))throw new RuntimeException('Unknown pending recovery action');
        $saved['pending_action']=$key;
        return ['action'=>$key,'will_resume_automatically'=>true];
    }
    if ($op==='recovery_context' && $role==='dispatcher') return ['recovery'=>$rec,'job'=>$state['jobs'][$rec['job']]];
    if ($op==='recovery_log') { recovery_log($state,$id,(string)$input['kind'],(string)$input['message']); return true; }
    if ($op==='recovery_checkpoint') {
        if(!preg_match('/^sessions\/[a-zA-Z0-9_\/.-]+\.jsonl$/D',(string)($input['rollout_path'] ?? ''))||str_contains($input['rollout_path'],'..')||!str_starts_with((string)($input['session_uri'] ?? ''),'gs://'))throw new InvalidArgumentException('Invalid session checkpoint');
        foreach (['session_uri','thread_id','rollout_path'] as $field) if (isset($input[$field])) $saved[$field]=$input[$field];
        return true;
    }
    if ($op==='recovery_question') {
        $qid=(string)$input['question_id'];
        if (!preg_match('/^[a-zA-Z0-9_-]{1,64}$/D',$qid)) throw new InvalidArgumentException('Invalid question ID');
        $options=$input['options'] ?? [];
        if (!is_array($options) || count($options)>5 || mb_strlen((string)$input['message'])>4000) throw new InvalidArgumentException('Invalid question');
        $ids=[]; foreach($options as $option) {
            if (!preg_match('/^[a-zA-Z0-9_-]{1,64}$/D',(string)($option['id'] ?? '')) || in_array($option['id'],$ids,true) || mb_strlen((string)($option['label'] ?? ''))>300) throw new InvalidArgumentException('Invalid option');
            $ids[]=$option['id'];
        }
        if (!isset($saved['questions'][$qid])) {
            $saved['questions'][$qid]=['id'=>$qid,'message'=>(string)$input['message'],'options'=>$options,'status'=>'pending','created_at'=>gmdate('c')];
            recovery_log($state,$id,'question',(string)$input['message']);
            notify_event($state,$id.'-question-'.$qid,'question',$id);
        }
        return ['question'=>$qid];
    }
    if ($op==='recovery_action_claim' && $role==='dispatcher') {
        $key=(string)$input['action_id']; $hash=(string)$input['request_hash'];
        if (!preg_match('/^[a-f0-9]{64}$/D',$key) || !preg_match('/^[a-f0-9]{64}$/D',$hash)) throw new InvalidArgumentException('Invalid action identity');
        if (isset($saved['actions'][$key])) {
            if ($saved['actions'][$key]['request_hash']!==$hash) throw new RuntimeException('Action changed');
            return ['existing'=>$saved['actions'][$key]];
        }
        if (!recovery_budget($state,$key,(float)$input['reserve_usd'],(int)$input['seconds'])) return ['budget_exhausted'=>true];
        $saved['actions'][$key]=['request_hash'=>$hash,'status'=>'reserved','kind'=>$input['kind'],'created_at'=>gmdate('c')];
        return ['claimed'=>true];
    }
    if ($op==='recovery_action_result' && $role==='dispatcher') {
        $key=(string)$input['action_id'];
        if (!isset($saved['actions'][$key])) throw new RuntimeException('Unknown action');
        $saved['actions'][$key]['status']='recorded'; $saved['actions'][$key]['result']=$input['result']; return true;
    }
    if($op==='recovery_sources'&&$role==='dispatcher'){
        $job=&$state['jobs'][$rec['job']];
        if($rec['stage']!=='prepare'||$job['stages']['prepare']['status']!=='failed'||!empty($job['stages']['upload']['checkpoint']))throw new RuntimeException('Source refresh unavailable');
        foreach(['pdf_url','audio_url'] as $field){
            $url=parse_url((string)$input[$field]);if(($url['scheme'] ?? '')!=='https'||!in_array($url['host'] ?? '',['supremecourt.gov','www.supremecourt.gov'],true))throw new RuntimeException('Official sources required');
            $job[$field]=$input[$field];
        }
        $saved['input_revision']=hash('sha256',json_encode([$job['pdf_url'],$job['audio_url'],$job['stages']['prepare']['result'] ?? null],JSON_THROW_ON_ERROR));
        recovery_log($state,$id,'repair','Source links were checked against the official listing for the same argument.');return ['pdf_url'=>$job['pdf_url'],'audio_url'=>$job['audio_url'],'input_revision'=>$saved['input_revision']];
    }
    if($op==='recovery_adopt_upload'&&$role==='dispatcher'){
        $answer=$rec['questions']['upload-identity']['answer'] ?? [];
        $video=(string)$input['video_id'];
        if(($answer['choice'] ?? '')!==$video&&trim($answer['text'] ?? '')!==$video)throw new RuntimeException('Owner upload identity decision required');
        if(!preg_match('/^[a-zA-Z0-9_-]{11}$/D',$video)||$rec['stage']!=='upload')throw new RuntimeException('Invalid video identity');
        $job=&$state['jobs'][$rec['job']];$stage=&$job['stages']['upload'];
        if($stage['status']!=='failed')throw new RuntimeException('Upload changed');
        $stage['checkpoint']=['video_id'=>$video];$stage['error']='worker_failed';$saved['error']='worker_failed';
        recovery_log($state,$id,'validation','The owner-selected existing video was matched to the expected description. Remaining upload steps can resume.');return true;
    }
    if ($op==='recovery_retry' && $role==='dispatcher') {
        $job =& $state['jobs'][$rec['job']];
        if ($job['status']!=='failed') throw new RuntimeException('Recording changed');
        if ($rec['error']==='upload_uncertain') throw new RuntimeException('Upload reconciliation is required');
        $restart=(string)($input['restart_from'] ?? $rec['stage']);$names=workflow_stage_order();
        $from=array_search($restart,$names,true);$failed=array_search($rec['stage'],$names,true);
        if($from===false||$failed===false||$from>$failed)throw new RuntimeException('Invalid upstream restart');
        if($restart==='assemble'&&removed_render_chunks($job))throw new RuntimeException('Rendered chunks were removed. Retry from render with a render resource reservation before assembly.');
        $restoreChunks=!empty($input['restore_render_chunks']);
        if($restoreChunks&&($restart!=='render'||!removed_render_chunks($job)||in_array('render',$input['release_stages'] ?? [],true)))throw new RuntimeException('Invalid chunk restoration');
        if($restart!==$rec['stage']||in_array($restart,['prepare','align'],true)){
            $renderOnly=($job['render_revision']['status']??'')==='queued'&&in_array($restart,['plan','render','assemble'],true)&&in_array($rec['stage'],['plan','render','assemble'],true);
            if(!empty($job['stages']['upload']['checkpoint'])&&!$renderOnly)throw new RuntimeException('Existing uploads cannot be rewound');
            if($from<=array_search('enrich',$names,true)&&!empty($job['stages']['enrich']['result']['enrichment_uri']))$job['editorial_cache_uri']=$job['stages']['enrich']['result']['enrichment_uri'];
            $missing=removed_render_chunks($job);
            if($from<=array_search('assemble',$names,true)&&($job['chunk_cleanup']['expires'] ?? 0)>time())throw new RuntimeException('Wait for chunk cleanup before restarting upstream work');
            foreach(array_slice($names,$from) as $name){
                if($renderOnly&&$name==='upload')continue;
                $old=$job['stages'][$name];$job['stages'][$name]=['status'=>'pending','attempt'=>$old['attempt'] ?? 0,'progress'=>0];
                $previous=$old['recovery_id'] ?? '';
                if($previous!==$id&&isset($state['recoveries'][$previous])&&!in_array($state['recoveries'][$previous]['status'],['repaired','cancelled'],true)){
                    $obsolete=&$state['recoveries'][$previous];$obsolete['status']='cancelled';
                    unset($obsolete['lease'],$obsolete['dispatch_token'],$obsolete['expires']);
                    foreach($obsolete['questions'] as &$question)if($question['status']==='pending')$question['status']='dismissed';
                    unset($question,$obsolete);
                    recovery_log($state,$previous,'system','Superseded by upstream restart from '.$restart.'; dependent work will resume through normal dispatch.');
                }
                if($name==='render'&&$restoreChunks){
                    $job['stages'][$name]['tasks']=$old['tasks'];
                    foreach($missing as $index)$job['stages'][$name]['tasks'][$index]=['status'=>'pending','progress'=>0];
                }
            }
            if($from<=array_search('render',$names,true))unset($job['chunk_cleanup']);
            if($from<=array_search('enrich',$names,true))unset($job['cards_approved_revision']);
            $job['stages'][$rec['stage']]['recovery_id']=$id;
            recovery_log($state,$id,'repair','Restart from '.$restart.'; dependent artifacts invalidated. Existing photo approvals and title selection retained.');
        }
        $release=$input['release'] ?? null;
        if ($release) {
            $job['workflow_release']=$release;
            foreach($input['release_stages'] ?? [$rec['stage']] as $name)$job['workflow_releases'][$name]=$release;
        }
        if(!empty($input['reusable']))$saved['reusable_release']=$input['reusable'];
        $stage =& $job['stages'][$rec['stage']];
        if ($release && isset($stage['tasks'])) { foreach($stage['tasks'] as &$task) $task=['status'=>'pending','progress'=>0]; }
        command($state,['command'=>'retry','job'=>$rec['job']]);
        $saved['retry_requested']=true;
        recovery_log($state,$id,'retry','The affected stage was queued again. Normal checks must pass before recovery is complete.');
        return true;
    }
    if ($op==='recovery_finish') {
        $status=(string)$input['status'];
        if (!in_array($status,['repaired','needs_input','waiting_for_resource','waiting_for_stage','waiting_for_tests','unresolved'],true)) throw new InvalidArgumentException('Invalid recovery result');
        if($status==='waiting_for_tests'&&empty($saved['pending_action']))throw new RuntimeException('A pending action is required');
        $pending=count(array_filter($saved['questions'],fn($q)=>$q['status']==='pending'));
        if ($pending) $status='needs_input';
        if ($status==='needs_input' && !$pending) throw new RuntimeException('A question is required');
        if ($status==='repaired') {
            $stage=$state['jobs'][$rec['job']]['stages'][$rec['stage']];
            if (empty($saved['retry_requested']) && ($stage['status']!=='complete'||($stage['recovery_id'] ?? '')!==$id)) throw new RuntimeException('Repair has not been tested by the affected stage');
            $status='waiting_for_stage';
        }
        $saved['status']=$status; unset($saved['lease'],$saved['dispatch_token']);
        recovery_log($state,$id,'note',(string)$input['summary']);
        event($state,$rec['job'],'Recovery: '.(string)$input['summary']);
        reconcile_recoveries($state);
        return ['status'=>$saved['status']];
    }
    throw new InvalidArgumentException('Unknown recovery operation');
}
