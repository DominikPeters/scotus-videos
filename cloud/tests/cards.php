<?php
require dirname(__DIR__).'/dashboard/private/state.php';
function check($ok,$why){if(!$ok)throw new RuntimeException($why);}
$s=initial_state();$job=add_job($s,['docket'=>'25-735','argument_date'=>'2026-10-05','audio_url'=>'https://www.supremecourt.gov/a.mp3','pdf_url'=>'https://www.supremecourt.gov/t.pdf']);$id=$job['id'];$j=&$s['jobs'][$id];
$j['review']=['revision'=>str_repeat('a',64),'card_revision'=>str_repeat('b',64),'cards'=>[['id'=>'show','recommended'=>true],['id'=>'hide','recommended'=>false]],'photos'=>['lawyer'=>['name'=>'Lawyer','candidates'=>[['id'=>'photo','portrait_uri'=>'portrait','sha256'=>'hash','origin'=>'curated_cache']]]]];$j['stages']['enrich']['status']='needs_review';$j['status']='needs_review';
review_command($s,['job'=>$id,'revision'=>str_repeat('a',64),'command'=>'photo','person'=>'lawyer','candidate'=>'photo']);check($j['stages']['enrich']['status']==='needs_review','Photo approval bypassed cards');
review_command($s,['job'=>$id,'revision'=>str_repeat('a',64),'command'=>'cards','selections'=>['show'=>false,'hide'=>true]]);check($j['stages']['enrich']['status']==='pending','Combined approvals did not release enrichment');check($j['card_selections']===['show'=>false,'hide'=>true],'Owner choices lost');
$j['review']['revision']=str_repeat('c',64);check(!cards_pending($j),'Photo revision discarded card signoff');$j['review']['card_revision']=str_repeat('d',64);check(cards_pending($j),'Changed cards kept approval');
$j['stages']['plan']['status']='complete';try{review_command($s,['job'=>$id,'revision'=>str_repeat('c',64),'command'=>'cards','selections'=>['show'=>true,'hide'=>true]]);throw new Exception('Frozen cards changed');}catch(RuntimeException $e){}
echo "Card review checks passed: combined gate, owner presets, revision isolation and frozen inputs.\n";
