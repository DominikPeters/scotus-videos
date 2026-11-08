"""Durable launch intents: reconcile a missing acknowledgement by attempt ID."""
def launch(dashboard,google,settings,owner,cloud_job,env,tasks=1,**options):
 token=env.get('SCOTUS_DISPATCH_TOKEN') or env.get('SCOTUS_RECOVERY_TOKEN') or env.get('SCOTUS_PHOTO_TOKEN') or env.get('SCOTUS_ASSET_TOKEN') or env.get('SCOTUS_ACTION_TOKEN') or env.get('SCOTUS_CARD_IMPORT_TOKEN')
 intent=dashboard.call('launch_prepare',owner=owner,cloud_job=cloud_job,dispatch_token=token)
 if not intent.get('claimed'):return None
 env={**env,'SCOTUS_ATTEMPT_ID':intent['id']}
 try:operation=google.execute(settings['region'],cloud_job,env,tasks=tasks,**options)
 except Exception:
  dashboard.call('launch_uncertain',owner=owner,attempt=intent['id']);return None
 dashboard.call('launch_record',owner=owner,attempt=intent['id'],operation=operation)
 return operation

def intents(snapshot):
 for job in (snapshot.get('jobs') or {}).values():
  for item in job.get('stages',{}).values():
   if item.get('_launch') and item['status'] in ('starting','running'):yield item
  for kind in ('photo_requests','video_actions'):
   for item in job.get(kind,{}).values():
    if item.get('_launch') and item['status'] in ('starting','running'):yield item
  item=job.get('asset_publication',{})
  if item.get('_launch') and item['status'] in ('starting','running'):yield item
  item=job.get('card_import',{})
  if item.get('_launch') and item['status'] in ('starting','running'):yield item
 for item in (snapshot.get('recoveries') or {}).values():
  if item.get('_launch') and item['status'] in ('starting','running'):yield item

def reconcile(dashboard,google,settings,snapshot):
 for item in intents(snapshot):
  intent=item['_launch'];owner=intent['owner'];operation=item.get('cloud_operation')
  try:
   if operation:
    status=google.operation_status(operation)
    if status['done']:dashboard.call('launch_closed',owner=owner,attempt=intent['id'])
    continue
   execution=google.find_attempt_execution(settings['region'],intent['cloud_job'],intent['id'])
   if execution:
    dashboard.call('launch_record',owner=owner,attempt=intent['id'],operation=execution['name'])
    if execution['done']:dashboard.call('launch_closed',owner=owner,attempt=intent['id'])
   else:dashboard.call('launch_missing',owner=owner,attempt=intent['id'])
  except Exception:continue
