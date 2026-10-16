<?php
require __DIR__.'/../dashboard/private/state.php';
$config=['control_url'=>'https://test.run.app'];$calls=[];$committed=false;
function cloud_request(array $config,string $operation,array $data=[],int $timeout=50): mixed {
    global $calls,$committed;
    if(!$committed)throw new RuntimeException('Push called before transaction committed');
    $calls[]=[$operation,$timeout];return [];
}
$s=['notifications'=>[]];
notify_event($s,'spotify','spotify','case');
notify_event($s,'question','question','repair');
if($calls)throw new RuntimeException('Push waited inside the state transaction');
$committed=true;
register_shutdown_function(function(){
    global $calls;
    if($calls!==[['notifications',15]])throw new RuntimeException('Events did not trigger exactly one immediate bounded delivery');
    echo "Passed immediate notification wake-up for all event types after transaction completion.\n";
});
