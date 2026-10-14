"""Generic ntfy notices link to passkey-protected reviews, never approval tokens."""
import json
from urllib.request import Request,urlopen


MESSAGES={'case_review':'A recording needs your annotation card and image sign-off.', 'photos':'A recording needs photo review.','question':'Codex has a recovery question for you.',
          'ready':'A video is ready for your publication decision.','test':'Dashboard notifications are connected.',
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


def drain_notifications(dashboard,settings):
    for _ in range(3):
        notice=dashboard.call('notification_claim')
        if not notice: break
        sent=False
        try:send_notice(settings,notice['kind'],notice['target']);sent=True
        finally:dashboard.call('notification_finish',id=notice['id'],token=notice['token'],sent=sent)
