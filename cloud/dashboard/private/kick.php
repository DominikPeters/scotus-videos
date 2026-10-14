<?php
// Fixed background CLI task: no user-selected command or exported credentials.
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }
require __DIR__.'/connections.php';
$config=require __DIR__.'/config.php';
try { cloud_request($config,'dispatch'); } catch(Throwable $error) { /* Timer retries. */ }
