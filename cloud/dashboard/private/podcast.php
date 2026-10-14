<?php
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
    if($job['stages']['align']['status']!=='complete'||($job['stages']['align']['result']['transcript_uri'] ?? '')!==$input['source_uri'])throw new RuntimeException('Alignment changed');
    $payload=$input['payload'];$revision=$input['revision'];
    if(!is_string($payload)||strlen($payload)>1800000||!preg_match('/^[a-f0-9]{64}$/D',$revision)||hash('sha256',$payload)!==$revision)throw new RuntimeException('Invalid export hash');
    $data=json_decode($payload,true,512,JSON_THROW_ON_ERROR);
    if(($data['recording_id'] ?? '')!==$id||($data['schema_version'] ?? 0)!==1||!isset($data['audio'],$data['sections']))throw new RuntimeException('Invalid export');
    global $privateDir,$podcastPublicDir;
    $folder=$podcastPublicDir ?? dirname($privateDir).'/scotusstats/podcast/alignment';
    if(!is_dir($folder)&&!mkdir($folder,0755,true))throw new RuntimeException('Export directory unavailable');
    $filename=$id.'-'.$revision.'.json';podcast_write($folder.'/'.$filename,$payload);
    $entry=['recording_id'=>$id,'revision'=>$revision,'term'=>$data['term'],'docket'=>$data['docket'],'argument_date'=>$data['argument_date'],
            'case_name'=>$data['case_name'],'url'=>'https://scotusstats.com/podcast/alignment/'.$filename];
    $index=transaction('podcast-index',function(&$index)use($id,$entry){$index['schema_version']=1;$index['recordings'][$id]=$entry;return $index;});
    podcast_write($folder.'/index.json',json_encode($index,JSON_UNESCAPED_SLASHES|JSON_THROW_ON_ERROR));
    $job['podcast_alignment']=['revision'=>$revision,'source_uri'=>$input['source_uri'],'url'=>$entry['url'],'dispatched'=>false];
    event($state,$id,'Validated alignment exported for podcast');return $job['podcast_alignment'];
}
