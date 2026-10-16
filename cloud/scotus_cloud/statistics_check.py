"""Read a draft from stdin and exercise the same checks used at publication.

Copied into the Codex input directory beside the shared stats_core.py module.
This command performs no writes or network requests.
"""
import json
import sys
from pathlib import Path
sys.dont_write_bytecode=True
from jsonschema import validate
from stats_core import apply_coding


def check(value,folder):
    validate(value,json.loads((folder.parent/'schema.json').read_text()))
    material=json.loads((folder/'case.json').read_text())
    record=dict(material['case'])
    if value.get('decided_date') and record.get('argument_date') and value['decided_date']<record['argument_date']:
        raise ValueError('Merits decision date predates this argument; check whether the source describes an interlocutory order')
    apply_coding(record,value,json.loads((folder/'issues.json').read_text()),
                 json.loads((folder/'legal-provisions.json').read_text()),material['docket_url'])


def main():
    try:
        check(json.load(sys.stdin),Path(__file__).resolve().parent)
    except Exception as error:
        print('Check failed: '+getattr(error,'message',str(error))[:1200],file=sys.stderr)
        return 1
    print('Statistics draft passed schema, taxonomy, participation, vote and date checks.')
    return 0


if __name__=='__main__':sys.exit(main())
