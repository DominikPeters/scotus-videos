<?php
require dirname(__DIR__).'/dashboard/private/state.php';
function check($ok,$why){if(!$ok)throw new RuntimeException($why);}
$s=initial_state();$empty=worker_update($s,['op'=>'discovery_context'],'dispatcher');check(is_object($empty['calendar'])&&is_object($empty['jobs']),'Empty JSON maps must be objects');$s['paused']=false;$s['discovery_after']=time()+1800;
check(worker_update($s,['op'=>'discovery_claim','seconds'=>600],'dispatcher')===true,'Old normal interval suppressed fast window');
check(worker_update($s,['op'=>'discovery_claim','seconds'=>600],'dispatcher')===false,'Duplicate poll within interval');
worker_update($s,['op'=>'discovery_calendar','calendar'=>['date'=>'2026-10-14','groups'=>[['25-459']]]],'dispatcher');
check(worker_update($s,['op'=>'discovery_context'],'dispatcher')['calendar']['groups']===[['25-459']],'Calendar cache lost');
$s['paused']=true;check(worker_update($s,['op'=>'discovery_claim','seconds'=>600],'dispatcher')===false,'Paused discovery ran');
echo "Discovery schedule state checks passed.\n";
