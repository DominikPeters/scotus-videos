<?php
declare(strict_types=1);

ini_set('display_errors', '0');
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: no-referrer');
header('X-Frame-Options: DENY');

function reply(mixed $result, int $status = 200): never {
    http_response_code($status);
    echo json_encode(['ok' => $status < 400, $status < 400 ? 'result' : 'error' => $result], JSON_THROW_ON_ERROR);
    exit;
}
function decode64(string $value): string {
    $result = base64_decode(strtr($value, '-_', '+/'), true);
    if ($result === false) throw new InvalidArgumentException('Invalid credential encoding');
    return $result;
}
class DashboardAuthDenied extends RuntimeException {}
function origin_check(array $config): void {
    if (($_SERVER['HTTP_ORIGIN'] ?? '') !== $config['origin']) throw new DashboardAuthDenied('Origin mismatch');
}
function csrf_check(): void {
    if (!hash_equals($_SESSION['csrf'] ?? 'missing', $_SERVER['HTTP_X_CSRF_TOKEN'] ?? '')) throw new DashboardAuthDenied('Session check failed');
}
function client_origin(string $data, string $origin): void {
    $client = json_decode($data, true, 512, JSON_THROW_ON_ERROR);
    if (($client['origin'] ?? '') !== $origin || ($client['crossOrigin'] ?? false)) throw new DashboardAuthDenied('Passkey origin mismatch');
}

try {
    $privateDir = getenv('SCOTUS_DASHBOARD_PRIVATE_DIR') ?: (is_file(__DIR__ . '/private-path.php') ? require __DIR__ . '/private-path.php' : dirname(__DIR__) . '/private');
    $config = require $privateDir . '/config.php';
    require $privateDir . '/state.php';
    require $privateDir . '/connections.php';
    $action = $_GET['action'] ?? '';
    $method = $_SERVER['REQUEST_METHOD'];
    $limit=$action==='worker'?2097152:262144;
    $raw = file_get_contents('php://input', false, null, 0, $limit+1);
    if (strlen($raw) > $limit) reply('Request too large', 413);
    $input = $raw === '' ? [] : json_decode($raw, true, 512, JSON_THROW_ON_ERROR);

    if ($action === 'worker') {
        if ($method !== 'POST') reply('Method not allowed', 405);
        $role = $_SERVER['HTTP_X_SCOTUS_ROLE'] ?? '';
        $key = $config['worker_keys'][$role] ?? '';
        $timestamp = $_SERVER['HTTP_X_SCOTUS_TIME'] ?? '';
        $nonce = $_SERVER['HTTP_X_SCOTUS_NONCE'] ?? '';
        if (!$key || !ctype_digit($timestamp) || abs(time() - (int)$timestamp) > 300 ||
            !preg_match('/^[a-f0-9]{32}$/D', $nonce)) reply('Worker authentication failed', 401);
        $signed = implode("\n", [$timestamp, $nonce, 'POST', $_SERVER['REQUEST_URI'], hash('sha256', $raw)]);
        $expected = hash_hmac('sha256', $signed, $key);
        if (!hash_equals($expected, $_SERVER['HTTP_X_SCOTUS_SIGNATURE'] ?? '')) reply('Worker authentication failed', 401);
        $result = transaction('state', function (&$state) use ($input, $role, $nonce) {
            if (!$state) $state = initial_state();
            $state['nonces'] = array_filter($state['nonces'], fn($at) => $at > time() - 600);
            if (isset($state['nonces'][$nonce])) throw new RuntimeException('Request already used');
            $state['nonces'][$nonce] = time();
            return worker_update($state, $input, $role);
        });
        if((($input['op'] ?? '')==='stats_update'&&!empty($input['finish'])&&empty($input['failed']))||(($input['op'] ?? '')==='claim'&&in_array($role,['enrich','align'],true))||in_array($input['op'] ?? '',['finish','fail','enrichment_review','recovery_finish','video_action_finish','photo_finish','photo_fail','review_candidate_add'],true))kick_controller();
        reply($result);
    }

    $secure = str_starts_with($config['origin'], 'https://');
    if (!$secure && !in_array($config['rp_id'], ['localhost', '127.0.0.1'], true)) reply('HTTPS is required', 500);
    ini_set('session.use_strict_mode', '1');
    $sessionLifetime = 28 * 24 * 60 * 60;
    ini_set('session.gc_maxlifetime', (string)$sessionLifetime);
    session_name('scotus_video_session');
    session_save_path($privateDir . '/sessions');
    session_set_cookie_params(['lifetime' => $sessionLifetime, 'path' => $config['cookie_path'],
                              'secure' => $secure, 'httponly' => true, 'samesite' => 'Strict']);
    session_start();
    $_SESSION['csrf'] ??= bin2hex(random_bytes(24));
    if (!empty($_SESSION['signed_in']) && time() - ($_SESSION['last_active'] ?? 0) > $sessionLifetime) unset($_SESSION['signed_in']);
    if (!empty($_SESSION['signed_in'])) {
        $_SESSION['last_active'] = time();
        // Refresh the browser expiry along with the server's inactivity timer.
        setcookie(session_name(), session_id(), ['expires' => time() + $sessionLifetime,
            'path' => $config['cookie_path'], 'secure' => $secure, 'httponly' => true, 'samesite' => 'Strict']);
    }
    $credentials = is_file($privateDir . '/credentials.json') ? json_decode(file_get_contents($privateDir . '/credentials.json'), true, 512, JSON_THROW_ON_ERROR) : [];

    if ($action === 'session' && $method === 'GET') reply(['signed_in' => !empty($_SESSION['signed_in']),
        'enrollment_allowed' => !empty($_SESSION['enroll_until']) && $_SESSION['enroll_until'] > time(),
        'initialized' => !empty($credentials), 'csrf' => $_SESSION['csrf']]);
    if ($action === 'state' && $method === 'GET') {
        if (empty($_SESSION['signed_in'])) reply('Sign in required', 401);
        session_write_close();
        reply(transaction('state', function (&$state) { if (!$state) $state = initial_state(); reconcile_expired($state); return public_state($state); }));
    }
    if ($method !== 'POST') reply('Method not allowed', 405);
    origin_check($config); csrf_check();

    if ($action === 'bootstrap') {
        if ($credentials || time() > $config['setup_expires'] || !hash_equals($config['setup_hash'], hash('sha256', (string)($input['token'] ?? '')))) reply('Setup link is unavailable', 403);
        $_SESSION['enroll_until'] = time() + 600;
        reply(true);
    }
    if (in_array($action, ['register_options', 'register', 'login_options', 'login'], true)) {
        require_once $privateDir . '/vendor/autoload.php';
        $web = new lbuchs\WebAuthn\WebAuthn('Scotus videos', $config['rp_id'], ['none'], true);
        if ($action === 'register_options') {
            if (empty($_SESSION['signed_in']) && (empty($_SESSION['enroll_until']) || $_SESSION['enroll_until'] < time() || $credentials)) reply('Enrollment is unavailable', 403);
            $_SESSION['user_handle'] ??= bin2hex(random_bytes(32));
            $ids = array_map(fn($c) => decode64($c['id']), $credentials);
            $args = $web->getCreateArgs(hex2bin($_SESSION['user_handle']), 'dominik', 'Dominik', 120, true, true, null, $ids);
            $_SESSION['challenge'] = base64_encode($web->getChallenge()->getBinaryString());
            $_SESSION['challenge_at'] = time(); $_SESSION['challenge_kind'] = 'register';
            reply($args);
        }
        if ($action === 'login_options') {
            if (!$credentials) reply('The dashboard has not been set up', 403);
            $args = $web->getGetArgs([], 120, true, true, true, true, true, true);
            $_SESSION['challenge'] = base64_encode($web->getChallenge()->getBinaryString());
            $_SESSION['challenge_at'] = time(); $_SESSION['challenge_kind'] = 'login';
            reply($args);
        }
        if (empty($_SESSION['challenge']) || time() - ($_SESSION['challenge_at'] ?? 0) > 180 || $_SESSION['challenge_kind'] !== $action) reply('Passkey challenge expired', 403);
        $challenge = base64_decode($_SESSION['challenge']);
        unset($_SESSION['challenge'], $_SESSION['challenge_at'], $_SESSION['challenge_kind']);
        $clientData = decode64($input['clientDataJSON'] ?? ''); client_origin($clientData, $config['origin']);
        if ($action === 'register') {
            $authenticated = !empty($_SESSION['signed_in']);
            if (!$authenticated && (empty($_SESSION['enroll_until']) || $_SESSION['enroll_until'] < time())) reply('Enrollment expired', 403);
            $data = $web->processCreate($clientData, decode64($input['attestationObject'] ?? ''), $challenge, true, true);
            $id = rtrim(strtr(base64_encode($data->credentialId), '+/', '-_'), '=');
            transaction('credentials', function (&$saved) use ($data, $id, $authenticated) {
                if ($saved && !$authenticated) throw new RuntimeException('First passkey already registered');
                foreach ($saved as $credential) if ($credential['id'] === $id) throw new RuntimeException('Passkey already registered');
                $saved[] = ['id' => $id, 'key' => $data->credentialPublicKey,
                            'counter' => $data->signatureCounter ?? 0, 'created_at' => gmdate('c')];
            });
        } else {
            $id = $input['id'] ?? '';
            transaction('credentials', function (&$saved) use ($web, $input, $id, $clientData, $challenge) {
                foreach ($saved as &$credential) {
                    if ($credential['id'] !== $id) continue;
                    $web->processGet($clientData, decode64($input['authenticatorData'] ?? ''), decode64($input['signature'] ?? ''),
                                     $credential['key'], $challenge, $credential['counter'], true, true);
                    $credential['counter'] = $web->getSignatureCounter() ?? 0;
                    return;
                }
                throw new RuntimeException('Unknown passkey');
            });
        }
        session_regenerate_id(true); $_SESSION['signed_in'] = true; $_SESSION['last_active'] = time();
        $_SESSION['csrf'] = bin2hex(random_bytes(24)); unset($_SESSION['enroll_until']);
        reply(['csrf' => $_SESSION['csrf']]);
    }
    if (empty($_SESSION['signed_in'])) reply('Sign in required', 401);
    if ($action === 'logout') { session_destroy(); reply(true); }
    // Cloud requests must not serialize every request from this browser.
    session_write_close();
    if ($action === 'state') {
        $view=transaction('state',function(&$state){if(!$state)$state=initial_state();reconcile_expired($state);return public_state($state);});
        $revision=hash('sha256',json_encode($view,JSON_THROW_ON_ERROR));
        if(($input['revision'] ?? '')===$revision)reply(['_unchanged'=>true,'_revision'=>$revision]);
        $view['_revision']=$revision;reply($view);
    }
    if ($action === 'enqueue') reply(transaction('state', function (&$state) use ($input) { if (!$state) $state = initial_state(); return add_job($state, $input); }));
    if ($action === 'command') {
        $result=transaction('state',function(&$state)use($input){
            $result=command($state,$input);
            if(($input['command'] ?? '')==='retry')command($state,['command'=>'start','job'=>$input['job']]);
            return $result;
        });
        if(in_array($input['command'] ?? '',['resume','retry','start','stats_check','stats_answer'],true))try{cloud_request($config,'dispatch');}catch(Throwable $error){}
        reply($result);
    }
    if($action==='review'){
        $result=transaction('state',fn(&$state)=>review_command($state,$input));
        if(in_array($input['command'] ?? '',['publish','title'],true))try{cloud_request($config,'video_action',['job'=>$input['job']]);}catch(Throwable $error){}
        else kick_controller();
        reply($result);
    }
    if($action==='clip'){
        $result=transaction('state',fn(&$state)=>clip_command($state,$input));
        try{cloud_request($config,'clip_dispatch',['job'=>$input['job'],'clip'=>$result['id']]);}catch(Throwable $error){}
        reply($result);
    }
    if($action==='clip_download')reply(cloud_request($config,'clip_download',['job'=>$input['job'],'clip'=>$input['clip']]));
    if($action==='spotify'){
        $result=transaction('state',fn(&$state)=>spotify_command($state,$input));
        try{cloud_request($config,'spotify_dispatch',['job'=>$input['job']]);}catch(Throwable $error){}
        reply($result);
    }
    if($action==='notification_test'){
        // Goes through the outbox so it reaches every registered device, like real notices.
        $notice=transaction('state',function(&$state){$key='test-'.bin2hex(random_bytes(8));notify_event($state,$key,'test','');return hash('sha256',$key);});
        reply(cloud_request($config,'notification_test',['notice_id'=>$notice]));
    }
    if($action==='push_subscribe'){$result=transaction('state',fn(&$state)=>push_subscribe($state,$input));kick_controller();reply($result);}
    if($action==='push_unsubscribe')reply(transaction('state',fn(&$state)=>push_unsubscribe($state,$input)));
    if($action==='photo_add')reply(cloud_request($config,'photo_add',$input));
    if($action==='asset_data') {
        $uri=transaction('state',function(&$state)use($input){
            $job=$state['jobs'][$input['job'] ?? ''] ?? null;
            if(!$job)throw new InvalidArgumentException('Unknown recording');
            $kind=$input['kind'] ?? '';$uri=null;
            if($kind==='photo'){
                $choices=$job['review']['photos'][$input['person'] ?? '']['candidates'] ?? [];
                foreach($choices as $choice)if($choice['id']===($input['candidate'] ?? '')){
                    $uri=($input['variant'] ?? '')==='source'?($choice['source_preview_uri'] ?? $choice['preview_uri'] ?? null):($choice['preview_uri'] ?? null);break;
                }
            }elseif($kind==='frame')$uri=$job['stages']['render']['tasks'][0]['result']['preview_uri'] ?? null;
            elseif($kind==='card'){foreach($job['review']['cards'] ?? [] as $card)if($card['id']===($input['candidate'] ?? ''))$uri=($input['variant'] ?? '')==='frame'?$card['frame_uri']:$card['card_uri'];}
            elseif($kind==='thumbnail')$uri=$job['stages']['plan']['result']['thumbnail_preview_uri'] ?? null;
            if(!$uri)throw new InvalidArgumentException('Unknown preview');return $uri;
        });
        $cacheDir=$privateDir.'/preview-cache';if(!is_dir($cacheDir))mkdir($cacheDir,0700,true);
        $cache=$cacheDir.'/'.hash('sha256',$uri).'.json';
        if(is_file($cache))reply(json_decode(file_get_contents($cache),true,512,JSON_THROW_ON_ERROR));
        $value=cloud_request($config,'asset_data',['uri'=>$uri,'kind'=>$input['kind']]);
        $temporary=tempnam($cacheDir,'preview-');chmod($temporary,0600);
        file_put_contents($temporary,json_encode($value,JSON_THROW_ON_ERROR));rename($temporary,$cache);
        reply($value);
    }
    if ($action === 'recovery_answer') {
        $result=transaction('state', fn(&$state)=>recovery_answer($state,$input));
        try { cloud_request($config,'dispatch'); } catch (Throwable $error) { /* Durable queue survives a controller outage. */ }
        reply($result);
    }
    if ($action === 'recovery_command') {
        $result=transaction('state', fn(&$state)=>recovery_command($state,$input));
        if (($input['command'] ?? '')==='resume') try { cloud_request($config,'dispatch'); } catch (Throwable $error) {}
        reply($result);
    }
    $owner = hash('sha256', session_id());
    if ($action === 'connect_start') {
        $provider = (string)($input['provider'] ?? '');
        if ($provider === 'codex') reply(cloud_request($config, 'codex_login_start', ['owner' => $owner]));
        reply(begin_connection($config, $provider, $owner));
    }
    if (in_array($action, ['connect_status', 'connect_cancel'], true)) {
        reply(transaction('state', function (&$state) use ($owner, $action) {
            return login_status($state, $owner, $action === 'connect_cancel');
        }));
    }
    if (in_array($action, ['dispatch', 'secret_status', 'secret_replace', 'youtube_client_replace', 'instagram_client_replace', 'github_install','spotify_probe'], true)) {
        // Only expose the human-facing operations, never arbitrary controller commands.
        reply(cloud_request($config, $action, $action === 'github_install' ? [] : $input));
    }
    reply('Unknown action', 404);
} catch (InvalidArgumentException | JsonException $error) { reply('Invalid request', 400); }
catch (DashboardAuthDenied $error) { reply($error->getMessage(), 403); }
catch (Throwable $error) { reply('Connection temporarily unavailable; please try again', $action==='worker'?409:503); }
