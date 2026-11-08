import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from infra.deploy_release import running_pipeline_executions


class DeploymentScopeTests(unittest.TestCase):
    def test_only_running_jobs_using_the_replaced_image_delay_deployment(self):
        resources = [
            {'kind': 'job', 'name': 'enrich', 'image': 'host/scotus-videos/pipeline@sha256:old'},
            {'kind': 'job', 'name': 'statistics', 'image': 'host/scotus-videos/statistics@sha256:other'},
        ]
        def execution(name, job, completed=False):
            return {'metadata': {'name': name, 'labels': {'run.googleapis.com/job': job}},
                    'status': {'conditions': [{'type': 'Completed', 'status': 'True' if completed else 'Unknown'}]}}
        self.assertEqual(running_pipeline_executions(resources, [
            execution('stats-running', 'statistics'), execution('enrich-done', 'enrich', True),
            execution('enrich-running', 'enrich')]), ['enrich-running'])


if __name__ == '__main__':
    unittest.main()
