<?php
require __DIR__.'/../dashboard/private/state.php';
function check($value,$message){if(!$value)throw new RuntimeException($message);}
$s=initial_state();$record=['docket'=>'25-5343','argument_date'=>'2026-10-13','case_name'=>'Beaird v. United States','source_page'=>'https://www.supremecourt.gov/oral_arguments/audio/2026/25-5343','audio_url'=>'https://www.supremecourt.gov/media/audio/mp3files/25-5343.mp3','pdf_url'=>'https://www.supremecourt.gov/oral_arguments/argument_transcripts/2026/25-5343_test.pdf'];
$s['source_watches']['one']=$record+['status'=>'scheduled','starts_at'=>gmdate('c',time()+100),'ends_at'=>gmdate('c',time()+500)];
check(worker_update($s,['op'=>'source_watch_claim','watch'=>'one'],'dispatcher')===false,'Started before window');
$s['source_watches']['one']['starts_at']=gmdate('c',time()-100);
check(worker_update($s,['op'=>'source_watch_claim','watch'=>'one'],'dispatcher')['checks']===1,'Failed to claim');
check(worker_update($s,['op'=>'source_watch_claim','watch'=>'one'],'dispatcher')===false,'Duplicate polling');
$r=worker_update($s,['op'=>'source_watch_result','watch'=>'one','recording'=>$record],'dispatcher');
check($s['paused']===true,'Unpaused general discovery');
check($s['jobs'][$r['job']]['run_requested']===true,'Did not request automatic start');
check($s['jobs'][$r['job']]['privacy']==='unlisted','Changed publication policy');
worker_update($s,['op'=>'source_watch_result','watch'=>'one','recording'=>$record],'dispatcher');
check(count($s['jobs'])===1,'Duplicate recording');
check(worker_update($s,['op'=>'source_watch_claim','watch'=>'one'],'dispatcher')===false,'Kept polling after found');
$s['source_watches']['late']=$record+['status'=>'scheduled','starts_at'=>gmdate('c',time()-500),'ends_at'=>gmdate('c',time()-1)];
check(worker_update($s,['op'=>'source_watch_claim','watch'=>'late'],'dispatcher')===false,'Polled after end');
check($s['source_watches']['late']['status']==='expired','Did not expire');
echo "Source watch checks passed\n";
