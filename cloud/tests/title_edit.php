<?php
require dirname(__DIR__).'/dashboard/private/state.php';
function check(bool $ok,string $message):void{if(!$ok)throw new RuntimeException($message);}
function rejected(callable $fn):void{try{$fn();}catch(Throwable $error){return;}throw new RuntimeException('Invalid title accepted');}
$s=initial_state();$job=add_job($s,['docket'=>'25-735','argument_date'=>'2026-10-05','case_name'=>'Fixture','audio_url'=>'https://www.supremecourt.gov/a.mp3','pdf_url'=>'https://www.supremecourt.gov/t.pdf']);$id=$job['id'];$revision=str_repeat('b',64);
$s['jobs'][$id]['review']=['revision'=>$revision,'titles'=>[['title'=>'Recommended']],'photos'=>[]];
$base=['job'=>$id,'revision'=>$revision,'command'=>'title'];
review_command($s,$base+['title'=>'  My edited title  ']);check($s['jobs'][$id]['title']==='My edited title','Custom title not saved before upload');
foreach(['',str_repeat('x',101),'Invalid <title>',"Title\nwith newline",['array']] as $invalid)rejected(function()use(&$s,$base,$invalid){review_command($s,$base+['title'=>$invalid]);});
$s['jobs'][$id]['stages']['upload']=['status'=>'complete','result'=>['video_id'=>'fH3tO7gyx64','postprocessing_complete'=>true]];
review_command($s,$base+['title'=>'New YouTube title']);$key=array_key_last($s['jobs'][$id]['video_actions']);$action=$s['jobs'][$id]['video_actions'][$key];check($action['kind']==='title'&&$action['title']==='New YouTube title'&&$action['video_id']==='fH3tO7gyx64','Wrong title update action');
review_command($s,$base+['title'=>'New YouTube title']);check(count($s['jobs'][$id]['video_actions'])===1,'Repeated save duplicated action');
rejected(function()use(&$s,$base){review_command($s,$base+['title'=>'Competing title']);});
$s['jobs'][$id]['video_actions'][$key]['status']='complete';$s['jobs'][$id]['title']='New YouTube title';
review_command($s,$base+['title'=>'My edited title']);$second=array_key_last($s['jobs'][$id]['video_actions']);$s['jobs'][$id]['video_actions'][$second]['status']='complete';$s['jobs'][$id]['title']='My edited title';
review_command($s,$base+['title'=>'New YouTube title']);check($s['jobs'][$id]['video_actions'][$key]['status']==='queued','Returning to an earlier title did not update YouTube');
echo "Custom title checks passed: validation, saved draft, upload update, deduplication and reverting a prior title.\n";
