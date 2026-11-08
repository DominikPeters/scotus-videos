"""Store a dedicated setup-token in the existing research group; print no token.

Run `claude setup-token` interactively, then paste its token at the hidden prompt.
No default profile is changed and no worker or build is started.
"""
import argparse
import getpass
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from infra.managed_secrets import cli_cloud
from scotus_cloud.claude_runner import oauth_value
from scotus_cloud.secret_store import SecretStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default='possible-cycle-237715')
    args = parser.parse_args()
    token = getpass.getpass('Dedicated Claude setup-token (hidden): ') if sys.stdin.isatty() else sys.stdin.read(16385).strip()
    raw = json.dumps({'oauth_token': token}).encode(); oauth_value(raw)
    SecretStore(cli_cloud(args.project)).replace('scotus-video-claude', raw)
    print(json.dumps({'credential': 'claude', 'group': 'scotus-research', 'stored': True, 'workers_started': False}))


if __name__ == '__main__': main()
