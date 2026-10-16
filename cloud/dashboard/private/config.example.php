<?php
// Generate actual keys during private deployment. Do not commit config.php.
return [
    'origin' => 'https://scotusstats.com',
    'rp_id' => 'scotusstats.com',
    'cookie_path' => '/youtube/',
    'setup_hash' => 'sha256 of a random one-time setup token',
    'setup_expires' => 0,
    'control_url' => '',
    'control_key' => '',
    'worker_keys' => [],
    // VAPID public key from infra/setup_web_push.py; empty disables Web Push.
    'push_public_key' => '',
    // The matching private key belongs only in the control Secret Manager config.
];
