<?php
/** Called only after YouTube confirms publication, never for review uploads. */
function podcast_youtube_link(array $job): void {
    if(($job['privacy'] ?? '')!=='public')return;
    $video=$job['stages']['upload']['result']['video_id'] ?? '';
    if(!preg_match('/^[A-Za-z0-9_-]{11}$/D',$video))return;
    global $privateDir,$podcastYoutubePublicDir;
    $folder=$podcastYoutubePublicDir ?? dirname($privateDir).'/scotusstats/podcast/youtube';
    if(!is_dir($folder)&&!mkdir($folder,0755,true))throw new RuntimeException('Video index directory unavailable');
    $year=(int)substr($job['argument_date'],0,4);$month=(int)substr($job['argument_date'],5,2);
    $entry=['term'=>(string)($month>=10?$year:$year-1),'docket'=>$job['docket'],'argument_date'=>$job['argument_date'],
        'video_id'=>$video,'title'=>$job['title'] ?? $job['case_name'] ?? '',
        'url'=>'https://www.youtube.com/watch?v='.$video,'published_at'=>gmdate('c')];
    // Keep the public file inside the index lock, preventing older concurrent writes.
    transaction('podcast-youtube-index',function(&$index)use($entry,$folder){
        $index['schema_version']=1;
        $index['recordings'][$entry['argument_date'].'-'.$entry['docket']]=$entry;
        podcast_write($folder.'/index.json',json_encode($index,JSON_UNESCAPED_SLASHES|JSON_THROW_ON_ERROR));
    });
}

function podcast_write(string $path,string $data):void{
    $tmp=tempnam(dirname($path),'.podcast-');if(file_put_contents($tmp,$data)!==strlen($data)){unlink($tmp);throw new RuntimeException('Podcast export write failed');}chmod($tmp,0644);
    if(!rename($tmp,$path))throw new RuntimeException('Podcast export write failed');
}
function podcast_operation(array &$state,array $input,string $role):mixed{
    if($role!=='dispatcher')throw new RuntimeException('Podcast export requires dispatcher');
    $id=(string)($input['job'] ?? '');if(!isset($state['jobs'][$id]))throw new RuntimeException('Unknown recording');
    $job=&$state['jobs'][$id];
    if($input['op']==='podcast_export_status'){
        if(isset($input['error'])){$job['podcast_alignment']['error']=$input['error'];$job['podcast_alignment']['error_source_uri']=$input['source_uri'];$job['podcast_alignment']['retry_after']=time()+900;return true;}
        if(($job['podcast_alignment']['revision'] ?? '')!==$input['revision'])throw new RuntimeException('Export revision changed');
        $job['podcast_alignment']['dispatched']=true;unset($job['podcast_alignment']['error']);
        event($state,$id,'Podcast workflow triggered');return true;
    }
    if(in_array($input['op'],['transcript_export','podcast_artwork'],true))return shared_transcript_operation($state,$input);
    if(($job['stages']['plan']['status'] ?? '')!=='complete'||($job['stages']['plan']['result']['podcast_artwork_uri'] ?? '')!==$input['source_uri'])throw new RuntimeException('Plan changed');
    $payload=$input['payload'];$revision=$input['revision'];
    if(!is_string($payload)||strlen($payload)>1800000||!preg_match('/^[a-f0-9]{64}$/D',$revision)||hash('sha256',$payload)!==$revision)throw new RuntimeException('Invalid export hash');
    $data=json_decode($payload,true,512,JSON_THROW_ON_ERROR);
    if(($data['recording_id'] ?? '')!==$id||($data['schema_version'] ?? 0)!==1||!isset($data['audio'],$data['sections']))throw new RuntimeException('Invalid export');
    global $privateDir,$podcastPublicDir;
    $folder=$podcastPublicDir ?? dirname($privateDir).'/scotusstats/podcast/alignment';
    if(!is_dir($folder)&&!mkdir($folder,0755,true))throw new RuntimeException('Export directory unavailable');
    $image=base64_decode($input['artwork_base64'] ?? '',true);$info=$image===false?false:getimagesizefromstring($image);
    if(($data['artwork']['sha256'] ?? '')!==($job['stages']['plan']['result']['podcast_artwork_sha256'] ?? ''))throw new RuntimeException('Plan artwork changed');
    if(!$info||strlen($image)>350000||$info[0]!==1500||$info[1]!==1500||$info[2]!==IMAGETYPE_JPEG||hash('sha256',$image)!==($data['artwork']['sha256'] ?? ''))throw new RuntimeException('Invalid episode artwork');
    $artwork=$id.'-'.$data['artwork']['sha256'].'.jpg';podcast_write($folder.'/'.$artwork,$image);
    $filename=$id.'-'.$revision.'.json';podcast_write($folder.'/'.$filename,$payload);
    $entry=['recording_id'=>$id,'revision'=>$revision,'term'=>$data['term'],'docket'=>$data['docket'],'argument_date'=>$data['argument_date'],
            'case_name'=>$data['case_name'],'artwork_url'=>'https://scotusstats.com/podcast/alignment/'.$artwork,'artwork_sha256'=>$data['artwork']['sha256'],'url'=>'https://scotusstats.com/podcast/alignment/'.$filename];
    $index=transaction('podcast-index',function(&$index)use($id,$entry){$index['schema_version']=1;$index['recordings'][$id]=$entry;return $index;});
    podcast_write($folder.'/index.json',json_encode($index,JSON_UNESCAPED_SLASHES|JSON_THROW_ON_ERROR));
    $job['podcast_alignment']=['revision'=>$revision,'source_uri'=>$input['source_uri'],'url'=>$entry['url'],'dispatched'=>false];
    event($state,$id,'Validated alignment exported for podcast');return $job['podcast_alignment'];
}

/** Shared transcript bytes are immutable; artwork changes only the index entry. */
function shared_transcript_operation(array &$state,array $input): array {
    $id=$input['job'];$job=&$state['jobs'][$id];
    global $privateDir,$podcastPublicDir;
    $folder=$podcastPublicDir ?? dirname($privateDir).'/scotusstats/podcast/alignment';
    if(!is_dir($folder)&&!mkdir($folder,0755,true))throw new RuntimeException('Export directory unavailable');
    if($input['op']==='transcript_export'){
        if(($job['stages']['align']['status'] ?? '')!=='complete'||($job['stages']['align']['result']['transcript_uri'] ?? '')!==$input['source_uri'])throw new RuntimeException('Alignment changed');
        $payload=$input['payload'];$revision=$input['revision'];
        if(!is_string($payload)||strlen($payload)>1800000||!preg_match('/^[a-f0-9]{64}$/D',$revision)||hash('sha256',$payload)!==$revision)throw new RuntimeException('Invalid export hash');
        $data=json_decode($payload,true,512,JSON_THROW_ON_ERROR);
        if(($data['recording_id'] ?? '')!==$id||($data['schema_version'] ?? 0)!==1||($data['docket'] ?? '')!==$job['docket']||($data['argument_date'] ?? '')!==$job['argument_date']||($data['audio']['url'] ?? '')!==$job['audio_url']||!isset($data['sections']))throw new RuntimeException('Invalid export identity');
        $filename=$id.'-'.$revision.'.json';podcast_write($folder.'/'.$filename,$payload);
        $entry=['recording_id'=>$id,'revision'=>$revision,'term'=>$data['term'],'docket'=>$data['docket'],'argument_date'=>$data['argument_date'],'case_name'=>$data['case_name'],'url'=>'https://scotusstats.com/podcast/alignment/'.$filename];
        transaction('podcast-index',function(&$index)use($id,$entry,$folder){$index['schema_version']=1;$index['recordings'][$id]=$entry;podcast_write($folder.'/index.json',json_encode($index,JSON_UNESCAPED_SLASHES|JSON_THROW_ON_ERROR));});
        $job['podcast_alignment']=['revision'=>$revision,'source_uri'=>$input['source_uri'],'url'=>$entry['url'],'dispatched'=>false];
        event($state,$id,'Aligned transcript published for podcast, player and statistics');
    }else{
        $saved=$job['podcast_alignment'] ?? [];$plan=$job['stages']['plan'];
        if(($saved['revision'] ?? '')!==$input['revision']||($plan['status'] ?? '')!=='complete'||($plan['result']['podcast_artwork_uri'] ?? '')!==$input['source_uri'])throw new RuntimeException('Plan or transcript changed');
        $image=base64_decode($input['artwork_base64'] ?? '',true);$info=$image===false?false:getimagesizefromstring($image);$hash=$plan['result']['podcast_artwork_sha256'];
        if(!$info||strlen($image)>350000||$info[0]!==1500||$info[1]!==1500||$info[2]!==IMAGETYPE_JPEG||hash('sha256',$image)!==$hash)throw new RuntimeException('Invalid episode artwork');
        $filename=$id.'-'.$hash.'.jpg';podcast_write($folder.'/'.$filename,$image);
        transaction('podcast-index',function(&$index)use($id,$saved,$hash,$filename,$folder){
            if(($index['recordings'][$id]['revision'] ?? '')!==$saved['revision'])throw new RuntimeException('Export revision changed');
            $index['recordings'][$id]['artwork_url']='https://scotusstats.com/podcast/alignment/'.$filename;$index['recordings'][$id]['artwork_sha256']=$hash;
            podcast_write($folder.'/index.json',json_encode($index,JSON_UNESCAPED_SLASHES|JSON_THROW_ON_ERROR));
        });
        $job['podcast_alignment']['artwork_source_uri']=$input['source_uri'];$job['podcast_alignment']['dispatched']=false;
        event($state,$id,'Podcast artwork attached to shared transcript index');
    }
    return $job['podcast_alignment'];
}
