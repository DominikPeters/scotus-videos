<?php
declare(strict_types=1);
// Instagram has its own redirect path; the provider never comes from its query.
$_GET['provider'] = 'instagram';
require __DIR__ . '/oauth-callback.php';
