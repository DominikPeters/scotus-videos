import base64
from contextlib import contextmanager
import copy
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from scotus_cloud.secret_store import SecretStore, GROUPS, canonical, decode_bundle, encode_bundle, group_for, runtime_settings
from scotus_cloud.control import runtime_configuration


def encoded(value): return base64.b64encode(canonical(json.dumps(value).encode())).decode()


class FakeSession:
    def __init__(self, cloud): self.cloud=cloud
    def get(self, url, **kwargs):
        return Mock(status_code=200, headers={'x-goog-generation':str(self.cloud.generation)}, json=lambda:{'version':self.cloud.current})
    def post(self, url, **kwargs):
        if kwargs['params']['ifGenerationMatch'] != str(self.cloud.generation): return Mock(status_code=412)
        self.cloud.current=json.loads(kwargs['data'])['version'];self.cloud.generation+=1
        return Mock(status_code=200)


class FakeCloud:
    project = 'project'
    def __init__(self):
        self.versions = {'1':{'schema_version':1,'entries':{
            'scotus-video-youtube':{'data':encoded({'refresh_token':'old'}),'updated_at':'first'},
            'scotus-spotify-auth':{'data':encoded({'refresh_token':'spotify'}),'updated_at':'first'}}}}
        self.states = {'1':'ENABLED'}
        self.current = '1';self.generation=1;self.session=FakeSession(self)
        self.mutex = threading.Lock(); self.destroyed = []; self.fail_readback = False
    def request(self, method, url, **kwargs):
        if url.endswith(':access'):
            number = url.rsplit('/',1)[1].split(':')[0]
            if number == 'latest': number = str(max(map(int,self.versions)))
            if number == 'current': number = self.current
            raw = encode_bundle(self.versions[number])
            if self.fail_readback and number != '1': raw = b'corrupt'
            return {'name':'projects/123/secrets/scotus-publishing/versions/'+number,
                    'payload':{'data':base64.b64encode(raw).decode()}}
        if method == 'GET' and url.endswith('/scotus-publishing'):
            return {'etag':'secret-etag','versionAliases':{'current':self.current}}
        if method == 'PATCH':
            self.current = str(kwargs['json']['versionAliases']['current']);return {}
        if '/versions/' in url and method == 'GET':
            number = url.rsplit('/',1)[1]
            return {'state':self.states[number],'etag':'etag-'+number}
        if url.endswith(':addVersion'):
            number = str(max(map(int,self.versions))+1)
            self.versions[number] = decode_bundle(base64.b64decode(kwargs['json']['payload']['data']))
            self.states[number] = 'ENABLED'
            return {'name':'projects/123/secrets/scotus-publishing/versions/'+number}
        if url.endswith(':destroy'):
            number = url.split('/versions/')[1].split(':')[0]
            self.states[number] = 'DESTROYED'; self.destroyed.append(number); return {}
        return {'versions':[{'name':'projects/123/secrets/scotus-publishing/versions/'+n,
                             'state':s,'etag':'etag-'+n} for n,s in self.states.items()]}


class MemoryStore(SecretStore):
    @contextmanager
    def lock(self, group):
        with self.cloud.mutex: yield


class SecretStoreTests(unittest.TestCase):
    def test_related_updates_commit_one_version_and_identical_batch_is_a_noop(self):
        cloud=FakeCloud();store=MemoryStore(cloud)
        changes={'scotus-video-youtube':lambda old:b'{"refresh_token":"new"}',
                 'scotus-spotify-auth':lambda old:json.dumps({**json.loads(old),'show':'retained'}).encode()}
        store.update_many(changes)
        self.assertEqual(len(cloud.versions),2)
        self.assertEqual(json.loads(store.read('scotus-video-youtube')),{'refresh_token':'new'})
        self.assertEqual(json.loads(store.read('scotus-spotify-auth')),{'refresh_token':'spotify','show':'retained'})
        store.update_many(changes)
        self.assertEqual(len(cloud.versions),2);self.assertEqual(cloud.states,{'1':'DESTROYED','2':'ENABLED'})

    def test_identical_json_does_not_create_a_version(self):
        cloud=FakeCloud();store=MemoryStore(cloud)
        store.replace('scotus-video-youtube', b'{ "refresh_token" : "old" }')
        self.assertEqual(len(cloud.versions),1);self.assertEqual(cloud.destroyed,[])

    def test_verified_replacement_preserves_other_accounts_and_destroys_old_version(self):
        cloud=FakeCloud();store=MemoryStore(cloud)
        store.replace('scotus-video-youtube',b'{"refresh_token":"new"}')
        self.assertEqual(json.loads(store.read('scotus-spotify-auth')),{'refresh_token':'spotify'})
        self.assertEqual(json.loads(store.read('scotus-video-youtube')),{'refresh_token':'new'})
        self.assertEqual(cloud.destroyed,['1'])

    def test_failed_readback_retains_working_version(self):
        cloud=FakeCloud();cloud.fail_readback=True
        with self.assertRaisesRegex(RuntimeError,'read-back'):MemoryStore(cloud).replace('scotus-video-youtube',b'{"refresh_token":"new"}')
        self.assertEqual(cloud.states['1'],'ENABLED');self.assertEqual(cloud.destroyed,['2']);self.assertEqual(cloud.current,'1')

    def test_failed_activation_does_not_remove_working_value(self):
        cloud=FakeCloud();store=MemoryStore(cloud)
        store.activate=Mock(side_effect=RuntimeError('CAS rejected'))
        with self.assertRaisesRegex(RuntimeError,'CAS rejected'):
            store.replace('scotus-video-youtube',b'{"refresh_token":"new"}')
        self.assertEqual(cloud.current,'1')
        self.assertEqual(cloud.states,{'1':'ENABLED','2':'DESTROYED'})

    def test_uncertain_committed_activation_is_preserved_and_next_noop_retires_history(self):
        cloud=FakeCloud();store=MemoryStore(cloud)
        def uncertain(*args,**kwargs):
            cloud.current='2';cloud.generation=2
            raise RuntimeError('response lost')
        store.activate=uncertain
        with self.assertRaisesRegex(RuntimeError,'response lost'):
            store.replace('scotus-video-youtube',b'{"refresh_token":"new"}')
        self.assertEqual(cloud.current,'2');self.assertEqual(cloud.states['2'],'ENABLED')
        MemoryStore(cloud).replace('scotus-video-youtube',b'{"refresh_token":"new"}')
        self.assertEqual(cloud.states,{'1':'DESTROYED','2':'ENABLED'})
        self.assertEqual(len(cloud.versions),2)

    def test_concurrent_refreshes_merge_latest_bundle(self):
        cloud=FakeCloud();errors=[]
        def write(name,value):
            try:MemoryStore(cloud).replace(name,json.dumps({'refresh_token':value}).encode())
            except Exception as error:errors.append(error)
        threads=[threading.Thread(target=write,args=('scotus-video-youtube','youtube-new')),
                 threading.Thread(target=write,args=('scotus-spotify-auth','spotify-new'))]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(errors,[])
        store=MemoryStore(cloud)
        self.assertEqual(json.loads(store.read('scotus-video-youtube'))['refresh_token'],'youtube-new')
        self.assertEqual(json.loads(store.read('scotus-spotify-auth'))['refresh_token'],'spotify-new')
        self.assertEqual(list(cloud.states.values()).count('ENABLED'),1)

    def test_disabled_versions_also_get_destroyed(self):
        cloud=FakeCloud();cloud.states['1']='DISABLED'
        MemoryStore(cloud).replace('scotus-video-youtube',b'{"refresh_token":"new"}')
        self.assertEqual(cloud.states['1'],'DESTROYED')

    def test_remove_temporary_state_preserves_other_credentials(self):
        cloud=FakeCloud();store=MemoryStore(cloud);store.replace('scotus-video-youtube',None)
        self.assertFalse(store.status('scotus-video-youtube')['configured'])
        self.assertTrue(store.status('scotus-spotify-auth')['configured'])

    def test_prune_paginates_and_removes_unactivated_versions_under_lock(self):
        cloud=Mock(project='project');store=SecretStore(cloud)
        store.raw=Mock(return_value=(b'', 'projects/123/secrets/scotus-publishing/versions/3'))
        cloud.request.side_effect=[{'versions':[{'name':'projects/123/secrets/scotus-publishing/versions/1','state':'DISABLED','etag':'1'}],'nextPageToken':'next'},
                                   {'versions':[{'name':'projects/123/secrets/scotus-publishing/versions/4','state':'ENABLED','etag':'4'}]},{},{}]
        store.prune('scotus-publishing','projects/123/secrets/scotus-publishing/versions/3')
        self.assertEqual(cloud.request.call_args_list[1].kwargs['params']['pageToken'],'next')
        self.assertEqual(cloud.request.call_args.args[0],'POST')
        self.assertIn('/versions/4:destroy',cloud.request.call_args.args[1])

    def test_reader_retries_when_pointer_version_was_retired_during_read(self):
        cloud=Mock(project='project');store=SecretStore(cloud)
        store.pointer=Mock(side_effect=[('1','1'),('2','2'),('2','2')])
        cloud.request.side_effect=[RuntimeError('version retired'),{'name':'projects/123/secrets/scotus-publishing/versions/2','payload':{'data':base64.b64encode(b'new').decode()}}]
        self.assertEqual(store.raw('scotus-publishing')[0],b'new')
        self.assertIn('/versions/2:access',cloud.request.call_args.args[1])

    def test_activation_is_generation_guarded_and_does_not_contain_credentials(self):
        cloud=Mock(project='project');store=SecretStore(cloud);store.pointer=Mock(return_value=('1','19'))
        cloud.session.post.return_value=Mock(status_code=200)
        store.activate('scotus-publishing','projects/123/secrets/scotus-publishing/versions/2','projects/123/secrets/scotus-publishing/versions/1')
        request=cloud.session.post.call_args.kwargs
        self.assertEqual(request['params']['ifGenerationMatch'],'19')
        self.assertEqual(json.loads(request['data']),{'version':'2'})

    def test_actual_lock_is_conditional_and_released_on_failure(self):
        cloud=Mock(project='project');cloud.session.post.return_value=Mock(status_code=200)
        cloud.session.post.return_value.json.return_value={'generation':'7'}
        cloud.session.request.return_value=Mock(status_code=204)
        with self.assertRaises(ValueError):
            with SecretStore(cloud).lock('scotus-publishing'):raise ValueError('failure')
        self.assertEqual(cloud.session.post.call_args.kwargs['params']['ifGenerationMatch'],'0')
        self.assertEqual(cloud.session.request.call_args.kwargs['params']['ifGenerationMatch'],'7')

    def test_lock_failure_never_enters_write(self):
        cloud=Mock(project='project');cloud.session.post.return_value=Mock(status_code=403)
        with self.assertRaises(RuntimeError):
            with SecretStore(cloud).lock('scotus-publishing'):self.fail('entered denied lock')
        cloud.request.assert_not_called()

    def test_three_groups_are_explicit_and_unknown_secrets_fail_closed(self):
        self.assertEqual(group_for('scotus-video-control-config'),GROUPS[0])
        self.assertEqual(group_for('scotus-video-codex'),GROUPS[1])
        self.assertEqual(group_for('scotus-video-youtube'),GROUPS[2])
        with self.assertRaises(ValueError):group_for('unrecognised')
        with self.assertRaises(ValueError):encode_bundle({'schema_version':1,'entries':{'large':'x'*65536}})

    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_worker_cannot_request_control_or_another_workers_configuration(self, verify):
        verify.return_value={'email':'renderer@project','email_verified':True}
        settings={'control_url':'https://controller.run.app','runtime_readers':{'renderer@project':['scotus-video-render-config']}}
        cloud=Mock();cloud.secret.return_value=b'{"worker_key":"own-key"}'
        def request(name):
            raw=json.dumps({'name':name}).encode()
            return {'CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw),'HTTP_AUTHORIZATION':'Bearer token'}
        self.assertEqual(runtime_configuration(settings,cloud,request('scotus-video-render-config')),{'worker_key':'own-key'})
        for name in ('scotus-video-control-config','scotus-video-upload-config','scotus-video-youtube'):
            with self.assertRaises(PermissionError):runtime_configuration(settings,cloud,request(name))
        verify.assert_called_with('token',unittest.mock.ANY,audience='https://controller.run.app')

    @patch('google.oauth2.id_token.verify_oauth2_token',return_value={'email':'renderer@project','email_verified':False})
    def test_unverified_identity_is_rejected(self, verify):
        with self.assertRaises(PermissionError):runtime_configuration({'control_url':'url'},Mock(),{'HTTP_AUTHORIZATION':'Bearer token'})

    def test_controller_loads_internal_config_through_its_own_google_identity(self):
        with patch('scotus_cloud.google.Google') as google,patch('scotus_cloud.secret_store.SecretStore') as store:
            store.return_value.read.return_value=b'{"control_key":"private"}'
            with patch.dict(os.environ,{'SCOTUS_RUNTIME_CONFIG':'scotus-video-control-config','GOOGLE_CLOUD_PROJECT':'project'}):
                self.assertEqual(runtime_settings('/unused'),{'control_key':'private'})
            store.return_value.read.assert_called_once_with('scotus-video-control-config')
            google.assert_called_once_with('project')


if __name__=='__main__':unittest.main()
