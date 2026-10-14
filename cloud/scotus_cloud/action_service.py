"""Private small HTTP service for explicit owner-requested YouTube metadata actions."""
import json
from pathlib import Path
from .google import Google
from .remote import Dashboard
from .youtube import video_action


def make_app(settings,google_factory=Google):
    dashboard=Dashboard(settings['dashboard_url'],settings['worker_key'],'upload')
    def app(environ,start_response):
        result={};status='200 OK'
        try:
            if environ.get('REQUEST_METHOD')!='POST' or environ.get('PATH_INFO')!='/action':raise ValueError('Unknown request')
            length=int(environ.get('CONTENT_LENGTH') or 0)
            if not 0<length<=2048:raise ValueError('Invalid request size')
            request=json.loads(environ['wsgi.input'].read(length))
            # Cloud Run IAM permits only the controller; never publicly callable.
            if request.get('probe'):result={'ready':True}
            else:
                claim=dashboard.call('video_action_claim',job=request['job'],action_id=request['action'],dispatch_token=request['token'])
                if claim:
                    success=False
                    try:
                        video_action(claim['job'],claim['action'],settings,google_factory(settings['project']),dashboard);success=True
                    finally:dashboard.call('video_action_finish',job=request['job'],action_id=request['action'],lease=claim['action']['lease'],success=success)
                    result={'complete':True}
                else:result={'claimed':False}
        except Exception:
            status='503 Service Unavailable';result={'error':'YouTube action did not complete; inspect its dashboard status before retrying.'}
        body=json.dumps(result).encode();start_response(status,[('Content-Type','application/json'),('Content-Length',str(len(body))),('Cache-Control','no-store')]);return [body]
    return app


def load_app():return make_app(json.loads(Path('/secrets/worker/config.json').read_text()))
