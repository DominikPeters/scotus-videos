<?php
// Run directly with PHP. Uses only a fresh temporary state directory.
$privateDir = sys_get_temp_dir() . '/scotus-connection-tests-' . bin2hex(random_bytes(8));
mkdir($privateDir, 0700);
require dirname(__DIR__) . '/dashboard/private/state.php';
require dirname(__DIR__) . '/dashboard/private/connections.php';
function check(bool $valid, string $message): void { if (!$valid) throw new RuntimeException($message); }
function rejected(callable $fn): void { try { $fn(); } catch (Throwable $error) { return; } throw new RuntimeException('Invalid action accepted'); }
try {
    $id = str_repeat('a',32); $cookie = str_repeat('b',48);
    transaction('connections', function (&$flows) use ($id, $cookie) { $flows[$id] = ['provider'=>'youtube','expires'=>time()+600,'phase'=>'start','cookie_hash'=>hash('sha256',$cookie)]; });
    rejected(fn()=>claim_connection($id,'youtube','start',str_repeat('c',48)));
    rejected(fn()=>claim_connection($id,'github','start',$cookie));
    check(claim_connection($id,'youtube','start',$cookie)['provider']==='youtube','Valid callback failed');
    rejected(fn()=>claim_connection($id,'youtube','start',$cookie));
    $state=initial_state(); $owner=str_repeat('d',64);
    $login=login_begin($state,['owner'=>$owner]);
    rejected(function() use (&$state,$owner) { login_begin($state,['owner'=>$owner]); });
    rejected(function() use (&$state,$login) { worker_update($state,['op'=>'login_update','id'=>$login['id'],'token'=>'wrong','status'=>'complete'],'codex'); });
    worker_update($state,['op'=>'login_update','id'=>$login['id'],'token'=>$login['token'],'status'=>'pending','verification_url'=>'https://auth.openai.com/codex/device','user_code'=>'ABCD-1234'],'codex');
    check(login_status($state,str_repeat('e',64))===null,'Device code exposed to another session');
    check(!str_contains(json_encode(public_state($state)),'ABCD-1234'),'Device code leaked into progress JSON');
    check(!isset(login_status($state,$owner)['token_hash']),'Internal token exposed');
    login_status($state,$owner,true);
    check(worker_update($state,['op'=>'login_update','id'=>$login['id'],'token'=>$login['token'],'status'=>'complete'],'codex')['status']==='cancelled','Cancelled sign-in was resurrected');
    for($i=0;$i<2;$i++){login_begin($state,['owner'=>$owner]);login_status($state,$owner,true);}
    rejected(function() use (&$state,$owner) { login_begin($state,['owner'=>$owner]); });
    echo "Passed callback cookie/state/replay, isolated device codes, cancellation fencing and daily start limit.\n";
} finally {
    foreach(glob($privateDir.'/*') as $path)unlink($path);
    rmdir($privateDir);
}
