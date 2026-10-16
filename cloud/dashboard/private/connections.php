<?php
declare(strict_types=1);

/** Only the passkey-authenticated PHP server can call the cloud controller. */
function control_body(string $operation, array $data = []): string {
    // PHP encodes an empty array as []; controller operations require an object.
    return json_encode(['op' => $operation, 'data' => (object)$data], JSON_THROW_ON_ERROR);
}

function cloud_request(array $config, string $operation, array $data = [], int $timeout = 50): mixed {
    $url = rtrim($config['control_url'], '/') . '/v1/request';
    $parts = parse_url($url);
    if (($parts['scheme'] ?? '') !== 'https' || !str_ends_with($parts['host'] ?? '', '.run.app') || isset($parts['user']) || isset($parts['port'])) {
        throw new RuntimeException('Cloud control service is not connected');
    }
    $body = control_body($operation, $data);
    $timestamp = (string)time(); $nonce = bin2hex(random_bytes(16));
    $signed = implode("\n", [$timestamp, $nonce, 'POST', $parts['path'], hash('sha256', $body)]);
    $curl = curl_init($url);
    curl_setopt_array($curl, [CURLOPT_POST => true, CURLOPT_POSTFIELDS => $body, CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => $timeout, CURLOPT_FOLLOWLOCATION => false, CURLOPT_PROTOCOLS => CURLPROTO_HTTPS,
        CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'X-Scotus-Time: ' . $timestamp,
            'X-Scotus-Nonce: ' . $nonce, 'X-Scotus-Signature: ' . hash_hmac('sha256', $signed, $config['control_key'])]]);
    $response = curl_exec($curl); $status = curl_getinfo($curl, CURLINFO_RESPONSE_CODE); curl_close($curl);
    if ($response === false || $status >= 400) throw new RuntimeException('Cloud connection could not be completed');
    $decoded = json_decode($response, true, 512, JSON_THROW_ON_ERROR);
    if (!$decoded['ok']) throw new RuntimeException('Cloud connection could not be completed');
    return $decoded['result'];
}

function kick_controller(): void {
    global $privateDir,$config;
    if(empty($config['control_url']))return;
    // Coalesce simultaneous chunk completions, and dispatch after committed replies.
    $pending=$privateDir.'/work-wakeup.pending';touch($pending);chmod($pending,0600);
    static $scheduled=false;
    if($scheduled)return;
    $scheduled=true;
    register_shutdown_function(function()use($pending){
        global $config,$privateDir;
        if(session_status()===PHP_SESSION_ACTIVE)session_write_close();
        if(function_exists('fastcgi_finish_request'))fastcgi_finish_request();
        $lock=fopen($privateDir.'/work-wakeup.lock','c');
        if(!$lock)return;
        if(!flock($lock,LOCK_EX|LOCK_NB)){fclose($lock);return;}
        try{
            for($pass=0;$pass<3;$pass++){
                clearstatcache(true,$pending);
                if(!is_file($pending))break;
                unlink($pending);
                try{cloud_request($config,'dispatch');}
                catch(Throwable $error){touch($pending);error_log('Scotus work wake-up failed; queued work retained for timer retry.');break;}
            }
        }finally{flock($lock,LOCK_UN);fclose($lock);}
    });
}

function callback_url(array $config, string $provider): string {
    if ($provider === 'instagram') return $config['origin'] . $config['cookie_path'] . 'instagram-callback.php';
    return $config['origin'] . $config['cookie_path'] . 'oauth-callback.php?provider=' . $provider;
}

function flow_cookie(string $provider, string $value, int $expires, array $config): void {
    setcookie('scotus_connect_' . $provider, $value, ['expires' => $expires,
        'path' => $config['cookie_path'] . ($provider === 'instagram' ? 'instagram-callback.php' : 'oauth-callback.php'), 'secure' => str_starts_with($config['origin'], 'https://'),
        'httponly' => true, 'samesite' => 'Lax']);
}

/** OAuth callbacks have their own short-lived, SameSite=Lax cookie. The dashboard session stays Strict. */
function begin_connection(array $config, string $provider, string $owner): array {
    if (!in_array($provider, ['youtube', 'github', 'instagram'], true)) throw new InvalidArgumentException('Unknown provider');
    $id = bin2hex(random_bytes(16)); $cookie = bin2hex(random_bytes(24));
    $verifier = rtrim(strtr(base64_encode(random_bytes(48)), '+/', '-_'), '=');
    $flow = ['id' => $id, 'provider' => $provider, 'owner' => $owner, 'expires' => time() + 3600,
             'cookie_hash' => hash('sha256', $cookie), 'verifier' => $verifier, 'phase' => 'start'];
    transaction('connections', function (&$saved) use ($id, $flow, $owner, $provider) {
        $saved = array_filter($saved, fn($entry) => $entry['expires'] > time());
        foreach ($saved as $key => $entry) if ($entry['owner'] === $owner && $entry['provider'] === $provider) unset($saved[$key]);
        $saved[$id] = $flow;
    });
    flow_cookie($provider, $cookie, $flow['expires'], $config);
    if ($provider === 'instagram') {
        return cloud_request($config, 'instagram_authorize', ['state' => $id]);
    }
    if ($provider === 'youtube') {
        $result = cloud_request($config, 'youtube_authorize', ['state' => $id,
            'code_challenge' => rtrim(strtr(base64_encode(hash('sha256', $verifier, true)), '+/', '-_'), '=')]);
        return ['url' => $result['url']];
    }
    $existing = cloud_request($config, 'github_existing');
    $setup = callback_url($config, 'github') . '&phase=install&state=' . $id;
    if (!empty($existing['slug'])) {
        transaction('connections', function (&$saved) use ($id) { unset($saved[$id]); });
        flow_cookie($provider, '', time() - 3600, $config);
        return ['install_url' => 'https://github.com/apps/' . rawurlencode($existing['slug']) . '/installations/new'];
    }
    return ['form_url' => 'https://github.com/settings/apps/new?state=' . $id, 'manifest' => [
        'name' => 'Scotus video assets ' . substr($id, 0, 6),
        'url' => $config['origin'] . $config['cookie_path'],
        'redirect_url' => callback_url($config, 'github'), 'setup_url' => $setup,
        'hook_attributes' => ['url' => $config['origin'] . $config['cookie_path'], 'active' => false],
        'public' => false, 'default_permissions' => ['contents' => 'write'], 'default_events' => [],
        'request_oauth_on_install' => false,
        'description' => 'Save advocate images and their sources in DominikPeters/scotus-videos.',
    ]];
}

/** Check the state, provider, phase, expiry and browser cookie, then consume this callback before exchanging any code. */
function claim_connection(string $id, string $provider, string $phase, string $cookie): array {
    if (!preg_match('/^[a-f0-9]{32}$/D', $id) || !preg_match('/^[a-f0-9]{48}$/D', $cookie)) throw new RuntimeException('Connection expired');
    return transaction('connections', function (&$saved) use ($id, $provider, $phase, $cookie) {
        $flow = $saved[$id] ?? null;
        if (!$flow || $flow['expires'] <= time() || $flow['provider'] !== $provider || $flow['phase'] !== $phase ||
            !hash_equals($flow['cookie_hash'], hash('sha256', $cookie))) throw new RuntimeException('Connection expired');
        $saved[$id]['phase'] = 'processing';
        return $flow;
    });
}
