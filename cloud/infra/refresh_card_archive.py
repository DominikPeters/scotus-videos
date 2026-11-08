"""Export displayed trial cards as searchable examples, without private notes/assets."""
import argparse
import json
from pathlib import Path
import re
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trials', type=Path, default=Path(__file__).resolve().parents[2] / 'annotation-trial')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'prompts/card-archive')
    args = parser.parse_args(); cases = {'25-170': 'Suncor Energy v. Boulder County', '25-352': 'Younge v. Fulton Judicial Circuit District Attorney’s Office', '25-5930': 'Maxwell v. Dinis'}
    count = 0
    for docket, name in cases.items():
        cards = json.loads((args.trials / docket / 'cards.json').read_text())['cards']
        target = args.output / docket
        if target.exists(): shutil.rmtree(target)
        target.mkdir(parents=True)
        for card in cards:
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', card['id']): raise ValueError('Invalid example ID')
            cue = card.get('cue') or json.loads(card['cue_json'])
            example = {'docket': docket, 'case_name': name, 'id': card['id'], 'kind': cue['kind'],
                       'title': cue.get('heading') or cue.get('case', {}).get('name') or cue.get('glossary', {}).get('term') or card['id'],
                       'status': 'historical trial design, not approval or source evidence', 'cue': cue}
            (target / (card['id'] + '.json')).write_text(json.dumps(example, ensure_ascii=False, indent=2) + '\n')
            count += 1
    print(json.dumps({'cases': len(cases), 'examples': count}))


if __name__ == '__main__': main()
