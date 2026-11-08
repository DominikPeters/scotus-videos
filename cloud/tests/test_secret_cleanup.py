"""Retention must preserve credentials and fail closed on unknown references."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('cleanup', Path(__file__).resolve().parents[1] / 'infra/secret_cleanup.py')
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)
NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)
SECRET = {'name': 'projects/123/secrets/scotus-test'}

def version(n, state='ENABLED', days=20):
    return {'name': SECRET['name']+'/versions/'+str(n), 'state': state,
            'createTime': (NOW-timedelta(days=days)).isoformat(), 'etag': str(n)}

class RetentionTests(unittest.TestCase):
    def test_only_current_enabled_version_survives(self):
        rows = [version(1), version(2), version(3)]
        self.assertEqual(cleanup.candidates(SECRET, rows, set()), rows[:2][::-1])

    def test_recent_versions_are_not_kept_as_history(self):
        rows = [version(1, days=1), version(2, 'DESTROYED'), version(3)]
        self.assertEqual(cleanup.candidates(SECRET, rows, set()), [rows[0]])

    def test_old_alias_or_deployment_pin_aborts_cleanup(self):
        rows = [version(n) for n in range(1, 6)]
        with self.assertRaises(ValueError):
            cleanup.candidates({**SECRET, 'versionAliases': {'stable': '1'}}, rows, set())
        with self.assertRaises(ValueError):
            cleanup.candidates(SECRET, rows, {('scotus-test', '2')})
        self.assertEqual(len(cleanup.candidates(SECRET, rows, {('scotus-test', '5')})), 4)

    def test_v1_mounted_and_environment_references_with_annotation_alias(self):
        resource = {'metadata': {'annotations': {'run.googleapis.com/secrets': 'alias:projects/123/secrets/scotus-test'}},
                    'spec': {'volumes': [{'secret': {'secretName': 'alias', 'items': [{'key': '7'}]}}],
                             'containers': [{'env': [{'valueFrom': {'secretKeyRef': {'name': 'alias', 'key': '8'}}}]}]}}
        self.assertEqual(cleanup.protected_versions(resource), {('scotus-test', '7'), ('scotus-test', '8')})

    def test_latest_is_preserved_by_retention_and_unknown_alias_fails_closed(self):
        self.assertEqual(cleanup.protected_versions({'secretKeyRef': {'name': 'scotus-test', 'key': 'latest'}}), set())
        with self.assertRaises(ValueError):
            cleanup.protected_versions({'secretKeyRef': {'name': 'scotus-test', 'key': 'unresolved'}})

    def test_explicitly_retired_temporary_state_can_be_empty(self):
        rows = [version(1, 'DISABLED'), version(2, 'DISABLED')]
        self.assertEqual(len(cleanup.candidates(SECRET, rows, set(), empty=True)), 2)
        with self.assertRaises(ValueError):
            cleanup.candidates(SECRET, [version(1)], set(), empty=True)

    def test_disabled_or_destroyed_newest_version_aborts_cleanup(self):
        for state in ('DISABLED', 'DESTROYED'):
            with self.assertRaises(ValueError):
                cleanup.candidates(SECRET, [version(1), version(2, state)], set())

if __name__ == '__main__': unittest.main()
