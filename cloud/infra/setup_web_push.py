"""Create the Web Push (VAPID) key pair once and add it to the private control config.

The private key stays in the control config (Secret Manager after `deploy_control.py setup`);
only the public key goes into the dashboard's config.php as 'push_public_key'.
Existing keys are kept: replacing them would silently invalidate every registered device.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scotus_cloud.webpush import generate_keys


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--config', type=Path, required=True, help='Private control config JSON')
    cli.add_argument('--subject', default='https://scotusstats.com/youtube/', help='Contact URL sent to push services')
    args = cli.parse_args()
    config = json.loads(args.config.read_text())
    if not config.get('web_push'):
        private, public = generate_keys()
        config['web_push'] = {'private_key': private, 'public_key': public, 'subject': args.subject}
        args.config.write_text(json.dumps(config, indent=2) + '\n')
        print('Added a new key pair to', args.config)
    else:
        print('Keeping the existing key pair in', args.config)
    print('Add to the dashboard config.php:')
    print(f"    'push_public_key' => '{config['web_push']['public_key']}',")
    print('Then upload the control config: python3 infra/deploy_control.py setup --config ... --state ...')


if __name__ == '__main__': main()
