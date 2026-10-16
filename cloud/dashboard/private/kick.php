<?php
// Fixed background CLI task: no user-selected command or exported credentials.
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }
require __DIR__.'/connections.php';
$config=require __DIR__.'/config.php';
// Send notices independently of source discovery and potentially slow job reconciliation.
try { cloud_request($config,'notifications'); } catch(Throwable $error) { error_log('Scotus push wake-up failed; timer will retry.'); }
try { cloud_request($config,'dispatch'); } catch(Throwable $error) { /* Timer retries. */ }
