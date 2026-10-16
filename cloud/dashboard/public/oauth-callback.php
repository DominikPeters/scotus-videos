<?php
declare(strict_types=1);
ini_set('display_errors', '0');
header('Cache-Control: no-store');
header('Referrer-Policy: no-referrer');
header("Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'");
header('X-Content-Type-Options: nosniff');

try {
    $connectionStep = 'callback';
    $privateDir = getenv('SCOTUS_DASHBOARD_PRIVATE_DIR') ?: require __DIR__ . '/private-path.php';
    $config = require $privateDir . '/config.php';
    require $privateDir . '/state.php';
    require $privateDir . '/connections.php';
    if ($_SERVER['REQUEST_METHOD'] !== 'GET') throw new RuntimeException('Invalid callback');
    $provider = (string)($_GET['provider'] ?? '');
    if (!in_array($provider, ['youtube', 'github', 'instagram'], true)) throw new RuntimeException('Invalid provider');
    $phase = $provider === 'github' && ($_GET['phase'] ?? '') === 'install' ? 'install' : 'start';
    $id = (string)($_GET['state'] ?? '');
    $connectionStep = 'state';
    $flow = claim_connection($id, $provider, $phase, (string)($_COOKIE['scotus_connect_' . $provider] ?? ''));
    if (isset($_GET['error'])) throw new RuntimeException('Sign-in declined');
    if ($provider === 'youtube') {
        cloud_request($config, 'youtube_exchange', ['code' => (string)($_GET['code'] ?? ''), 'verifier' => $flow['verifier']]);
    } elseif ($provider === 'instagram') {
        $connectionStep = 'exchange';
        cloud_request($config, 'instagram_exchange', ['code' => (string)($_GET['code'] ?? '')], 90);
    } elseif ($phase === 'start') {
        $app = cloud_request($config, 'github_exchange', ['code' => (string)($_GET['code'] ?? ''),
            'expected_setup_url' => callback_url($config, 'github') . '&phase=install&state=' . $id]);
        transaction('connections', function (&$saved) use ($id) { $saved[$id]['phase'] = 'install'; });
        header('Location: https://github.com/apps/' . rawurlencode($app['slug']) . '/installations/new?state=' . $id, true, 303);
        exit;
    } else {
        cloud_request($config, 'github_install', ['installation_id' => (string)($_GET['installation_id'] ?? '')]);
    }
    transaction('connections', function (&$saved) use ($id) { unset($saved[$id]); });
    flow_cookie($provider, '', time() - 3600, $config);
    header('Location: ' . $config['cookie_path'] . '#connected=' . $provider, true, 303);
} catch (Throwable $error) {
    if (($provider ?? '') === 'instagram' && isset($config)) {
        // Bounded diagnostics contain no codes, tokens, cookies or provider bodies.
        $safe = in_array($error->getMessage(), ['Connection expired', 'Sign-in declined', 'Invalid callback',
            'Invalid provider', 'Cloud connection could not be completed'], true) ? $error->getMessage() : get_class($error);
        transaction('connection-diagnostics', function (&$saved) use ($safe, $connectionStep) {
            $saved['instagram'] = ['at' => gmdate('c'), 'step' => $connectionStep, 'reason' => $safe];
        });
    }
    // Never reflect provider errors, codes or tokens into a page or application log.
    $path = isset($config) ? $config['cookie_path'] : '/youtube/';
    header('Location: ' . $path . '#connection=failed', true, 303);
}
