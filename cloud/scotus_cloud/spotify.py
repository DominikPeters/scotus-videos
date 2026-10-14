"""Spotify web-session authentication and the verified nonhosted delivery API."""
import base64
from datetime import date
import hashlib
import json
import re
import secrets
import time

import requests

CLIENT_ID = '05a1371ee5194c27860b3ff3ff3979d2'
BASE = 'https://generic.wg.spotify.com/podcasters/v0'
MEDIA = 'https://media-importer.spotify.com'


class SpotifyAuthRequired(RuntimeError): pass
class SpotifyError(RuntimeError): pass


def valid_id(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[A-Za-z0-9]{22}', value))


def validate_credentials(value):
    if not isinstance(value, dict): raise ValueError('Expected Spotify credential JSON')
    if not (value.get('refresh_token') or (value.get('sp_dc') and value.get('sp_key'))):
        raise ValueError('Spotify needs sp_dc and sp_key cookies, or a refresh_token')
    if any(not isinstance(v,str) or not v or len(v)>8192 for k,v in value.items() if k in ('sp_dc','sp_key','refresh_token','access_token')):
        raise ValueError('Invalid Spotify credential')
    return {k:v for k,v in value.items() if k in ('sp_dc','sp_key','refresh_token','access_token','expires_at')}


class Spotify:
    def __init__(self, google, dashboard, secret, show_id, session=None):
        if not valid_id(show_id): raise ValueError('Invalid Spotify show')
        self.google, self.dashboard, self.secret, self.show_id = google, dashboard, secret, show_id
        self.session = session or requests.Session()
        self.token = None

    def authenticate(self):
        if self.token: return self.token
        value=json.loads(self.google.secret(self.secret))
        if value.get('access_token') and float(value.get('expires_at',0))>time.time()+300:
            self.token=value['access_token'];return self.token
        lock=self.dashboard.call('auth_claim',name='spotify')
        if not lock: raise SpotifyError('Spotify credentials are being renewed; retry shortly')
        try:
            value=json.loads(self.google.secret(self.secret))
            if value.get('access_token') and float(value.get('expires_at',0))>time.time()+300:
                self.token=value['access_token'];return self.token
            tokens=None
            if value.get('refresh_token'):
                response=self.session.post('https://accounts.spotify.com/api/token',data={
                    'grant_type':'refresh_token','refresh_token':value['refresh_token'],'client_id':CLIENT_ID},timeout=15)
                if response.ok: tokens=response.json()
            if tokens is None:
                if not value.get('sp_dc') or not value.get('sp_key'): raise SpotifyAuthRequired('Reconnect Spotify in the dashboard')
                verifier=secrets.token_urlsafe(48);state=secrets.token_hex(16)
                challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
                response=self.session.get('https://accounts.spotify.com/oauth2/v2/auth',params={
                    'response_type':'code','client_id':CLIENT_ID,'scope':'streaming ugc-image-upload user-read-email user-read-private',
                    'redirect_uri':'https://podcasters.spotify.com','code_challenge':challenge,'code_challenge_method':'S256',
                    'state':state,'response_mode':'web_message','prompt':'none'},
                    cookies={'sp_dc':value['sp_dc'],'sp_key':value['sp_key']},timeout=15)
                match=re.search(r'const authorizationResponse\s*=\s*(.*?);',response.text,re.S)
                if not response.ok or not match: raise SpotifyAuthRequired('Spotify sign-in needs renewal')
                import yaml
                result=yaml.safe_load(match.group(1));auth=result.get('response',{})
                if auth.get('state')!=state or not auth.get('code'): raise SpotifyAuthRequired('Spotify sign-in needs renewal')
                response=self.session.post('https://accounts.spotify.com/api/token',data={
                    'grant_type':'authorization_code','client_id':CLIENT_ID,'code':auth['code'],
                    'redirect_uri':'https://podcasters.spotify.com','code_verifier':verifier},timeout=15)
                if not response.ok: raise SpotifyAuthRequired('Spotify token renewal failed')
                tokens=response.json()
            value.update(access_token=tokens['access_token'],expires_at=time.time()+float(tokens['expires_in']))
            if tokens.get('refresh_token'):
                value['refresh_token']=tokens['refresh_token']
                value.pop('sp_dc',None);value.pop('sp_key',None)
            self.dashboard.call('auth_check',name='spotify',token=lock)
            saved=self.google.add_secret_version(self.secret,json.dumps(value).encode())
            self.google.retire_secret_versions(self.secret,saved)
            self.token=value['access_token'];return self.token
        finally: self.dashboard.call('auth_release',name='spotify',token=lock)

    def headers(self):
        return {'Authorization':'Bearer '+self.authenticate(),'Accept':'application/json',
                'Origin':'https://creators.spotify.com','Referer':'https://creators.spotify.com/'}

    def request(self, method, path, *, media=False, **kwargs):
        response=self.session.request(method,(MEDIA if media else BASE)+path,headers=self.headers(),timeout=15,allow_redirects=False,**kwargs)
        if response.status_code==401: raise SpotifyAuthRequired('Reconnect Spotify in the dashboard')
        if response.status_code==429: raise SpotifyError('Spotify rate limit; retry later')
        if not response.ok: raise SpotifyError('Spotify API HTTP '+str(response.status_code))
        return response.json() if response.content else {}

    def metadata(self, episode):
        if not valid_id(episode): raise ValueError('Invalid Spotify episode')
        value=self.request('GET','/episodes/'+episode+'/metadata')
        if value.get('id')!=episode or value.get('show',{}).get('id')!=self.show_id:
            raise SpotifyError('Spotify episode belongs to a different show')
        return value

    def find_episode(self, job):
        marker='['+job['docket']+']'
        result=self.request('GET','/shows/'+self.show_id+'/episodes',params={
            'start':job['argument_date'],'end':date.today().isoformat(),'page':1,'size':50,
            'sortBy':'releaseDate','sortOrder':'descending','filter':marker})
        candidates=[x for x in result.get('episodes',[]) if marker in (x.get('name') or x.get('title') or '')]
        verified=[]
        for candidate in candidates[:5]:
            if str(candidate.get('releaseDate',''))[:10]!=job['argument_date']: continue
            episode=candidate.get('id') or candidate.get('episodeId')
            if not valid_id(episode): continue
            metadata=self.metadata(episode)
            if marker not in metadata.get('name',''): continue
            duration=float(metadata.get('duration',0))/1000
            if job.get('duration_seconds') and abs(duration-float(job['duration_seconds']))>5: continue
            verified.append(metadata)
        if len(verified)>1: raise SpotifyError('Multiple matching Spotify episodes; choose the episode ID in the dashboard')
        return verified[0] if verified else None

    def upload_status(self, upload_id):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',upload_id): raise ValueError('Invalid upload ID')
        return self.request('GET','/v1/uploadstatus/'+upload_id,media=True)

    def reserve_upload(self, episode):
        return self.request('POST','/episodes/'+episode+'/generateUploadId',json={
            'episodeId':episode,'showId':self.show_id,'episodeUri':'spotify:episode:'+episode})['uploadId']

    def publish(self, episode, upload_id):
        metadata=self.metadata(episode)
        return self.request('POST','/episodes/'+episode+'/publish',json={'uploadId':upload_id,
            'isExplicit':bool(metadata.get('isExplicit',False)),'isEighteenPlus':bool(metadata.get('isEighteenPlus',False))})
