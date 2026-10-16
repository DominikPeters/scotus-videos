"""Deliver outbox notices: encrypted Web Push to registered devices, generic ntfy otherwise.

Web Push payloads are end-to-end encrypted to each device, so they may name the case and
say what it needs. The ntfy topic is public, so ntfy notices stay generic and only link to
the passkey-protected dashboard. Neither ever carries approval tokens.
"""
import json,time
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request,urlopen

from . import webpush


MESSAGES={'case_review':'A recording needs your annotation card and image sign-off.', 'photos':'A recording needs photo review.','question':'Codex has a recovery question for you.',
          'failure':'Processing needs your attention. Open the dashboard.', 'ready':'A video is ready for your publication decision.','test':'Dashboard notifications are connected.',
          'recovery':'Video processing needs recovery. Open the dashboard for progress.',
          'spotify':'Spotify delivery has an update. Open the dashboard for its status.'}


def send_notice(settings,kind,target=''):
    if kind not in MESSAGES: raise ValueError('Unknown notification kind')
    url=settings['dashboard_url']
    if target: url+='#'+('recovery=' if kind in ('question','recovery') else 'review=')+target
    body={'topic':'scotus_youtube_alerts_dp','title':'Scotus videos','message':MESSAGES[kind],
          'click':url,'actions':[{'action':'view','label':'Open dashboard','url':url}]}
    with urlopen(Request('https://ntfy.sh',json.dumps(body).encode(),{'Content-Type':'application/json'}),timeout=10) as response:
        if response.status!=200: raise RuntimeError('Notification delivery failed')


def push_notice(settings,notice,timeout=3):
    """Bounded parallel delivery; one device's failure never abandons the others."""
    def send(subscription):
        try:return subscription['id'],webpush.send(subscription,notice['payload'],settings['web_push'],timeout=timeout)
        except (ValueError,KeyError):return subscription['id'],'failed'
    with ThreadPoolExecutor(max_workers=min(8,len(notice['subscriptions']))) as pool:
        results=list(pool.map(send,notice['subscriptions']))
    return ([id for id,result in results if result=='sent'],[id for id,result in results if result=='gone'])


def drain_notifications(dashboard,settings,notice_id=None):
    results=[]
    deadline=time.monotonic()+8
    for _ in range(3):
        if time.monotonic()>=deadline:break
        notice=dashboard.call('notification_claim',**({'notice_id':notice_id} if notice_id else {}))
        if not notice:break
        sent=False;delivered,gone=[],[]
        try:
            if notice.get('subscriptions') and settings.get('web_push'):
                delivered,gone=push_notice(settings,notice,timeout=max(.1,min(3,deadline-time.monotonic())))
            elif settings.get('ntfy_fallback_enabled',False):
                send_notice(settings,notice['kind'],notice['target']);sent=True
        finally:
            dashboard.call('notification_finish',id=notice['id'],token=notice['token'],sent=sent,
                           delivered=delivered,gone=gone,web_push=bool(settings.get('web_push')))
        results.append({'id':notice['id'],'delivered':len(delivered),'expired':len(gone)})
        if notice_id:break
    return results
