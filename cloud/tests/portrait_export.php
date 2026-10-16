<?php
require dirname(__DIR__).'/dashboard/private/state.php';
function check(bool $ok,string $message):void{if(!$ok)throw new RuntimeException($message);}
function rejected(callable $fn):void{try{$fn();}catch(Throwable $e){return;}throw new RuntimeException('Invalid portrait export accepted');}
$temporary=sys_get_temp_dir().'/scotus-portrait-test-'.bin2hex(random_bytes(5));mkdir($temporary);$statisticsPublicDir=$temporary.'/data';
$image="\xff\xd8\xffapproved JPEG fixture";$person='advocate_25_459_paul_d_clement';
$s=['jobs'=>['case'=>['asset_publication'=>['status'=>'running','expires'=>time()+60,'lease'=>'lease'],
    'approved_photos'=>[$person=>['sha256'=>hash('sha256',$image)]]]]];
$input=['op'=>'asset_portrait_export','job'=>'case','person'=>$person,'lease'=>'lease','image_base64'=>base64_encode($image)];
try{
    rejected(function()use(&$s,$input){worker_update($s,$input+[],'enrich');});
    rejected(function()use(&$s,$input){worker_update($s,array_replace($input,['lease'=>'wrong']),'assets');});
    rejected(function()use(&$s,$input){worker_update($s,array_replace($input,['person'=>'../escape']),'assets');});
    rejected(function()use(&$s,$input){worker_update($s,array_replace($input,['image_base64'=>base64_encode('other')]),'assets');});
    $result=worker_update($s,$input,'assets');$file=$temporary.'/img/advocates/'.$person.'.jpg';
    check(file_get_contents($file)===$image,'Approved portrait bytes changed');
    check($result['url']==='/img/advocates/'.$person.'.jpg','Speaker ID changed');
    worker_update($s,$input,'assets');check(file_get_contents($file)===$image,'Repeat export changed portrait');
    echo "Passed approved portrait export, exact ID, checksum, lease, role and path checks.\n";
}finally{
    @unlink($temporary.'/img/advocates/'.$person.'.jpg');@rmdir($temporary.'/img/advocates');@rmdir($temporary.'/img');@rmdir($temporary);
}
