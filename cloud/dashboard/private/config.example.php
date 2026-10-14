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
];
