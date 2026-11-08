<?php
declare(strict_types=1);

/** Resolve only a current, owner-visible preview; reads never rewrite workflow state. */
function preview_uri(string $privateDir,array $input):string {
 $lock=fopen($privateDir.'/state.lock','c');
 if(!$lock||!flock($lock,LOCK_SH))throw new RuntimeException('State unavailable');
 try{$state=json_decode(file_get_contents($privateDir.'/state.json'),true,512,JSON_THROW_ON_ERROR);}
 finally{flock($lock,LOCK_UN);fclose($lock);}
 $job=$state['jobs'][$input['job']??'']??null;if(!$job)throw new InvalidArgumentException('Unknown recording');
 $kind=$input['kind']??'';$uri=null;
 if($kind==='photo'){
  foreach($job['review']['photos'][$input['person']??'']['candidates']??[] as $choice)if($choice['id']===($input['candidate']??'')){
   $uri=($input['variant']??'')==='source'?($choice['source_preview_uri']??$choice['preview_uri']??null):($choice['preview_uri']??null);break;
  }
 }elseif($kind==='frame')$uri=$job['stages']['render']['tasks'][0]['result']['preview_uri']??null;
 elseif($kind==='card'){foreach($job['review']['cards']??[] as $card)if($card['id']===($input['candidate']??''))$uri=($input['variant']??'')==='frame'?$card['frame_uri']:$card['card_uri'];}
 elseif($kind==='thumbnail')$uri=$job['stages']['plan']['result']['thumbnail_preview_uri']??null;
 if(!$uri)throw new InvalidArgumentException('Unknown preview');return $uri;
}

function preview_value(string $privateDir,array $config,string $uri,string $kind):array {
 $cacheDir=$privateDir.'/preview-cache';if(!is_dir($cacheDir)&&!mkdir($cacheDir,0700,true)&&!is_dir($cacheDir))throw new RuntimeException('Preview cache unavailable');
 $cache=$cacheDir.'/'.hash('sha256',$uri).'.json';
 if(is_file($cache))return json_decode(file_get_contents($cache),true,512,JSON_THROW_ON_ERROR);
 $value=cloud_request($config,'asset_data',['uri'=>$uri,'kind'=>$kind]);
 $temporary=tempnam($cacheDir,'preview-');chmod($temporary,0600);
 file_put_contents($temporary,json_encode($value,JSON_THROW_ON_ERROR));rename($temporary,$cache);return $value;
}
