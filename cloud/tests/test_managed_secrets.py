import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock,patch
from infra import managed_secrets as managed
from infra.migrate_secrets import resource_plan,reader_map,validate_images
from scotus_cloud.secret_store import GROUPS


class DeploymentSecretTests(unittest.TestCase):
    def setUp(self):
        self.mode=patch.object(managed,'enabled',return_value=True);self.mode.start();self.addCleanup(self.mode.stop)
        self.cloud=patch.object(managed,'cli_cloud');self.cloud.start();self.addCleanup(self.cloud.stop)
        self.factory=patch.object(managed,'SecretStore');self.store=self.factory.start().return_value;self.addCleanup(self.factory.stop)
        self.store.read.return_value=b'{"control_url":"https://controller.run.app","region":"us-central1"}'

    def test_payload_is_never_forwarded_to_gcloud_arguments(self):
        self.store.replace.return_value='projects/123/secrets/scotus-publishing/versions/2'
        with patch.object(managed.subprocess,'run') as run:
            result=managed.run_gcloud(['gcloud','secrets','versions','add','scotus-video-youtube','--data-file=-','--project=p'],
                                      input=b'{"refresh_token":"private"}',capture_output=True)
        run.assert_not_called()
        self.store.replace.assert_called_once_with('scotus-video-youtube',b'{"refresh_token":"private"}')
        self.assertNotIn(b'private',result.stdout)

    def test_logical_access_returns_payload_without_response_wrapper(self):
        self.store.read.return_value=b'{"token":"private"}'
        result=managed.run_gcloud(['gcloud','secrets','versions','access','latest','--secret=scotus-video-youtube','--project=p','--format=json'],text=True)
        self.assertEqual(result.stdout,'{"token":"private"}')

    def test_configuration_grants_do_not_expose_internal_bundle_to_workers(self):
        with patch.object(managed.subprocess,'run') as run:
            managed.run_gcloud(['gcloud','secrets','add-iam-policy-binding','scotus-video-render-config','--member=serviceAccount:renderer@p','--role=roles/secretmanager.secretAccessor','--project=p'])
        run.assert_not_called()

    def test_controller_settings_replacement_preserves_broker_readers(self):
        self.store.update.return_value='version'
        managed.run_gcloud(['gcloud','secrets','versions','add','scotus-video-control-config','--data-file=-','--project=p'],input=b'{"control_key":"new"}')
        patcher=self.store.update.call_args.args[1]
        result=json.loads(patcher(b'{"runtime_readers":{"renderer@p":["scotus-video-render-config"]},"control_key":"old"}'))
        self.assertEqual(result['control_key'],'new')
        self.assertEqual(result['project'],'p')
        self.assertEqual(result['runtime_readers'],{'renderer@p':['scotus-video-render-config']})

    def test_worker_config_mount_becomes_authenticated_broker_reference(self):
        with patch.object(managed.subprocess,'run',return_value=subprocess.CompletedProcess([],0,b'',b'')) as run:
            managed.run_gcloud(['gcloud','run','jobs','deploy','render','--project=p','--service-account=renderer@p',
                               '--set-secrets=/secrets/worker/config.json=scotus-video-render-config:latest','--update-env-vars=THREADS=4'])
        parts=run.call_args.args[0]
        self.assertIn('--clear-secrets',parts)
        self.assertTrue(any(p.startswith('--update-env-vars=THREADS=4,SCOTUS_SECRET_BUNDLES=1') for p in parts))
        self.assertFalse(any('worker_key' in p or 'CONFIG_JSON' in p for p in parts))
        self.assertTrue(any('SCOTUS_RUNTIME_CONFIG=scotus-video-render-config' in p for p in parts))
        self.store.update.assert_called_once()

    def test_controller_uses_identity_bootstrap_without_a_secret_mount(self):
        with patch.object(managed.subprocess,'run') as run:
            managed.run_gcloud(['gcloud','run','deploy','control','--project=p','--service-account=controller@p',
                               '--set-secrets=/secrets/control/config.json=scotus-video-control-config:latest'])
        self.assertIn('--clear-secrets',run.call_args.args[0])
        self.assertTrue(any('GOOGLE_CLOUD_PROJECT=p' in part for part in run.call_args.args[0]))
        self.store.update.assert_not_called()

    def test_research_writer_gets_no_publishing_permissions(self):
        with patch.object(managed,'grant_writer') as grant:
            managed.run_gcloud(['gcloud','secrets','add-iam-policy-binding','scotus-video-codex','--project=p',
                               '--member=serviceAccount:research@p','--role=roles/secretmanager.secretVersionAdder'])
        grant.assert_called_once_with('p','scotus-research','serviceAccount:research@p','gcloud')

    def test_legacy_mode_does_not_change_a_deployment(self):
        command=['gcloud','run','jobs','deploy','render','--project=p','--set-secrets=/path=scotus-video-render-config:latest']
        with patch.object(managed,'enabled',return_value=False),patch.object(managed.subprocess,'run') as run:
            managed.run_gcloud(command,capture_output=True)
        run.assert_called_once_with(command,capture_output=True)


class MigrationTests(unittest.TestCase):
    def resource(self,name,entry,account='renderer@p',image=None):
        return {'metadata':{'name':name,'labels':{'cloud.googleapis.com/location':'us-central1'}},
                'spec':{'template':{'spec':{'serviceAccountName':account,'containers':[{'image':image or 'us-central1-docker.pkg.dev/p/scotus-videos/pipeline@sha256:'+'a'*64}],
                'volumes':[{'secret':{'secretName':entry,'items':[{'key':'latest'}]}}] if entry else []}}}}
    def test_plan_preserves_scoped_configs_and_moves_instagram_off_controller_identity(self):
        rows=[self.resource('render','scotus-video-render-config'),self.resource('scotus-video-instagram-clips','scotus-video-upload-config','scotus-video-control@p')]
        plan=resource_plan([],rows)
        self.assertEqual(plan[1]['account'],'scotus-video-upload@p')
        self.assertEqual(reader_map(plan),{'renderer@p':['scotus-video-render-config'],'scotus-video-upload@p':['scotus-video-upload-config']})
    def test_prebuilt_images_must_be_new_and_in_the_same_project(self):
        plan=resource_plan([],[self.resource('render','scotus-video-render-config')]);old=plan[0]['image']
        for value in (old,'foreign/image@sha256:'+'b'*64,'us-central1-docker.pkg.dev/p/scotus-videos/pipeline:latest'):
            with self.assertRaises(ValueError):validate_images(plan,{old:value})
        validate_images(plan,{old:'us-central1-docker.pkg.dev/p/scotus-videos/pipeline@sha256:'+'b'*64})
    def test_already_migrated_controller_is_understood_for_final_verification(self):
        item=self.resource('scotus-video-control','scotus-internal','controller@p')
        item['spec']['template']['spec']['containers'][0]['env']=[{'name':'SCOTUS_RUNTIME_CONFIG','value':'scotus-video-control-config'},{'name':'SCOTUS_SECRET_BUNDLES','value':'1'}]
        plan=resource_plan([item],[])
        self.assertTrue(plan[0]['bundle_mode']);self.assertEqual(plan[0]['legacy_mounts'],[])
    def test_duplicate_legacy_volumes_for_the_same_config_are_collapsed(self):
        item=self.resource('render','scotus-video-render-config')
        item['spec']['template']['spec']['volumes']*=2
        import copy
        item['spec']['template']['spec']['volumes']=[copy.deepcopy(v) for v in item['spec']['template']['spec']['volumes']]
        for i,v in enumerate(item['spec']['template']['spec']['volumes']):v['name']='old-config-'+str(i)
        plan=resource_plan([],[item])[0]
        self.assertEqual(plan['config_entry'],'scotus-video-render-config')
        self.assertEqual(plan['legacy_volume_names'],['old-config-0','old-config-1'])
    def test_pilot_receives_a_scoped_configuration_for_bundle_access_and_safe_probe(self):
        item=self.resource('scotus-video-tiktok-pilot','scotus-video-upload-config','uploader@p')
        item['spec']['template']['spec'].pop('volumes')
        self.assertEqual(resource_plan([],[item])[0]['config_entry'],'scotus-video-upload-config')

    def test_failed_image_import_is_terminal_without_a_completion_timestamp(self):
        from infra.registry_cleanup import execution_active
        self.assertFalse(execution_active({'status':{'conditions':[{'type':'Completed','status':'False'}]}}))
        self.assertTrue(execution_active({'status':{'conditions':[{'type':'Completed','status':'Unknown'}]}}))
        self.assertFalse(execution_active({'status':{'completionTime':'now'}}))

    def test_pinned_configuration_requires_review(self):
        item=self.resource('render','scotus-video-render-config');item['spec']['template']['spec']['volumes'][0]['secret']['items'][0]['key']='1'
        with self.assertRaises(ValueError):resource_plan([],[item])

if __name__=='__main__':unittest.main()
