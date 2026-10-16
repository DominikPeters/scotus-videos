<?php
require __DIR__.'/../dashboard/private/state.php';
$privateDir=sys_get_temp_dir().'/scotus-video-links-'.bin2hex(random_bytes(5));mkdir($privateDir,0700);$podcastYoutubePublicDir=$privateDir.'/public';
$job=['docket'=>'25-170','argument_date'=>'2026-10-05','privacy'=>'unlisted','title'=>'Example','stages'=>['upload'=>['result'=>['video_id'=>'UZFnuBM0Zjc']]]];
podcast_youtube_link($job);
if(is_file($podcastYoutubePublicDir.'/index.json'))throw new RuntimeException('Unlisted video exposed');
$job['privacy']='public';podcast_youtube_link($job);podcast_youtube_link($job);
$index=json_decode(file_get_contents($podcastYoutubePublicDir.'/index.json'),true);
if(count($index['recordings'])!==1||$index['recordings']['2026-10-05-25-170']['term']!=='2026')throw new RuntimeException('Video identity differs');
$job['argument_date']='2026-04-01';podcast_youtube_link($job);
$index=json_decode(file_get_contents($podcastYoutubePublicDir.'/index.json'),true);
if($index['recordings']['2026-04-01-25-170']['term']!=='2025')throw new RuntimeException('Spring term differs');
echo "Podcast YouTube link checks passed\n";
