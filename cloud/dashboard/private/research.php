<?php
declare(strict_types=1);
function research_operation(array &$state,array $input,string $role): mixed {
 $job=&$state['jobs'][$input['job']??''];
 if(!$job||$role!=='enrich')throw new RuntimeException('Research access denied');
 $stage=$job['stages']['enrich'];
 if($stage['status']!=='running'||($stage['lease']['expires']??0)<=time()||!hash_equals($stage['lease']['token']??'',(string)($input['lease']??'')))throw new RuntimeException('Stale research worker');
 $saved=$job['card_research']??['version'=>0,'checkpoint'=>null];
 if($input['op']==='research_load')return $saved;
 if($input['op']!=='research_save')throw new RuntimeException('Unknown research operation');
 $operation=(string)($input['operation_id']??'');
 if(!preg_match('/^[a-f0-9]{32}$/D',$operation))throw new InvalidArgumentException('Invalid checkpoint write');
 if(($saved['operation_id']??'')===$operation)return ['version'=>$saved['version']];
 if($saved['version']!==($input['version']??null))throw new RuntimeException('A newer research checkpoint exists');
 $checkpoint=$input['checkpoint']??null;
 if(!is_array($checkpoint)||strlen(json_encode($checkpoint,JSON_THROW_ON_ERROR))>1572864)throw new InvalidArgumentException('Research checkpoint exceeds its limit');
 $checkpoint['events']=array_slice($checkpoint['events']??[],-100);
 $job['card_research']=['version'=>$saved['version']+1,'operation_id'=>$operation,'checkpoint'=>$checkpoint];
 return ['version'=>$job['card_research']['version']];
}
