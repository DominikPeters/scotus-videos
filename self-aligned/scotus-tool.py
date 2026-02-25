#!/usr/bin/env python3
"""
SCOTUS Transcript Processing Tool
A terminal interface for processing Supreme Court oral argument transcripts.
"""

import os
import sys
import re
import json
import subprocess
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Please install required packages: pip install requests beautifulsoup4")
    sys.exit(1)

try:
    import questionary
    from questionary import Style, Choice
except ImportError:
    print("Please install questionary: pip install questionary")
    sys.exit(1)

# Custom style
custom_style = Style([
    ('qmark', 'fg:yellow bold'),
    ('question', 'bold'),
    ('answer', 'fg:green bold'),
    ('pointer', 'fg:yellow bold'),
    ('highlighted', 'fg:yellow bold'),
    ('selected', 'fg:green'),
    ('separator', 'fg:gray'),
    ('instruction', 'fg:gray italic'),
])

BASE_DIR = Path(__file__).parent.resolve()
SCOTUS_URL = "https://www.supremecourt.gov/"


def get_existing_cases():
    """Get list of existing case folders"""
    cases = []
    for item in BASE_DIR.iterdir():
        if item.is_dir() and re.match(r'^\d+[A-Z]?\d*-\d+$', item.name):
            cases.append(item.name)
    return sorted(cases, key=lambda x: (x.split('-')[0].lstrip('0') or '0', x), reverse=True)


def fetch_scotus_cases():
    """Fetch recent cases from SCOTUS website"""
    try:
        response = requests.get(SCOTUS_URL, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching SCOTUS website: {e}")
        return []

    soup = BeautifulSoup(response.text, 'html.parser')

    cases = []
    # Find oral arguments section
    oral_args_div = soup.find('div', id='ctl00_MainEditable_pnlOralArguments')
    if not oral_args_div:
        print("Could not find oral arguments section on page")
        return cases

    # Find all case entries
    for listline in oral_args_div.find_all('div', class_='listline'):
        case_name_span = listline.find('div', class_='casenamecolumn')
        if not case_name_span:
            continue

        case_text = case_name_span.get_text(strip=True)
        # Extract docket number from text like "Case Name (24-813)" or "Case Name (25A312)"
        docket_match = re.search(r'\((\d+[A-Z]?\d+-\d+|\d+[A-Z]\d+)\)', case_text)
        if not docket_match:
            continue

        docket = docket_match.group(1)
        case_name = case_text.replace(f'({docket})', '').strip()

        # Check for transcript and audio links
        button_col = listline.find('div', class_='buttoncolumn')
        transcript_link = None
        has_audio = False

        if button_col:
            for a in button_col.find_all('a'):
                href = a.get('href', '')
                if 'transcript' in href.lower() and href.endswith('.pdf'):
                    transcript_link = href
                if '/audio/' in href.lower():
                    has_audio = True

        cases.append({
            'docket': docket,
            'name': case_name,
            'transcript_url': transcript_link,
            'has_audio': has_audio,
        })

    return cases


def download_case_materials(case):
    """Download PDF and MP3 for a case"""
    docket = case['docket']
    case_dir = BASE_DIR / docket
    case_dir.mkdir(exist_ok=True)

    # Download transcript PDF
    if case['transcript_url']:
        pdf_url = case['transcript_url']
        if not pdf_url.startswith('http'):
            pdf_url = SCOTUS_URL.rstrip('/') + '/' + pdf_url.lstrip('/')

        # Extract PDF filename from URL
        pdf_filename = pdf_url.split('/')[-1]
        pdf_path = case_dir / pdf_filename

        print(f"Downloading transcript: {pdf_url}")
        try:
            response = requests.get(pdf_url, timeout=30)
            response.raise_for_status()
            pdf_path.write_bytes(response.content)
            print(f"  Saved to: {pdf_path}")
        except requests.RequestException as e:
            print(f"  Error downloading PDF: {e}")

    # Download MP3
    mp3_url = f"https://www.supremecourt.gov/media/audio/mp3files/{docket}.mp3"
    mp3_path = case_dir / f"{docket}.mp3"

    print(f"Downloading audio: {mp3_url}")
    try:
        response = requests.get(mp3_url, timeout=60)
        if response.status_code == 200:
            mp3_path.write_bytes(response.content)
            print(f"  Saved to: {mp3_path}")
        else:
            print(f"  MP3 not available (status {response.status_code})")
    except requests.RequestException as e:
        print(f"  Error downloading MP3: {e}")

    return docket


def run_convert_to_text(case):
    """Run the AppleScript to convert PDF to text"""
    case_dir = BASE_DIR / case

    # Find PDF file
    pdfs = list(case_dir.glob('*.pdf'))
    if not pdfs:
        print("No PDF file found in case folder")
        return False

    pdf_path = pdfs[0]
    txt_path = case_dir / f"{case}.txt"

    print(f"Converting {pdf_path.name} to text...")
    print("(This will open Adobe Acrobat Reader)")
    script_path = BASE_DIR / 'export-pdf-to-txt.scpt'

    if not script_path.exists():
        print(f"Error: AppleScript not found at {script_path}")
        return False

    result = subprocess.run(
        ['osascript', str(script_path), str(pdf_path), str(txt_path)],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        return False

    if txt_path.exists():
        print(f"Saved to: {txt_path}")
        return True
    else:
        print("Conversion may have failed - output file not found")
        return False


def run_parse_transcript(case):
    """Run the parser on the transcript"""
    print(f"Parsing transcript for {case}...")

    result = subprocess.run(
        ['python3', str(BASE_DIR / 'scotus-parser.py'), case],
        capture_output=True,
        text=True,
        cwd=BASE_DIR
    )

    # Print any output
    if result.stdout:
        print(result.stdout)

    # Print warnings to stderr
    if result.stderr:
        print(result.stderr)

    if result.returncode != 0:
        print(f"Parser failed with return code {result.returncode}")
        return False

    json_path = BASE_DIR / case / f"{case}.json"
    flat_path = BASE_DIR / case / f"{case}.flat.txt"

    if json_path.exists() and flat_path.exists():
        print(f"Created {case}/{case}.json and {case}/{case}.flat.txt")
        return True
    else:
        print("Parser may have failed - output files not found")
        return False


def run_gentle(case):
    """Run the gentle aligner"""
    case_dir = BASE_DIR / case
    mp3_path = case_dir / f"{case}.mp3"
    flat_path = case_dir / f"{case}.flat.txt"
    output_path = case_dir / f"{case}.timed.json"

    if not mp3_path.exists():
        print(f"Error: MP3 file not found: {mp3_path}")
        return False

    if not flat_path.exists():
        print(f"Error: Flat transcript not found: {flat_path}")
        print("Run 'Parse transcript' first.")
        return False

    # Check if gentle server is running
    print("Checking gentle server...")
    try:
        response = requests.get("http://localhost:8765/", timeout=2)
        if response.status_code != 200:
            raise requests.RequestException("Server not ready")
    except requests.RequestException:
        print("Gentle server not running. Starting gentle.app...")
        subprocess.run(['open', '-a', 'gentle'], check=False)

        # Wait for server to be ready
        print("Waiting for gentle server to start...")
        import time
        for i in range(30):
            try:
                response = requests.get("http://localhost:8765/", timeout=2)
                if response.status_code == 200:
                    print("Gentle server is ready.")
                    break
            except requests.RequestException:
                pass
            time.sleep(1)
        else:
            print("Error: Gentle server failed to start after 30 seconds")
            return False

    print(f"Running alignment on {case}...")
    print(f"  Audio: {mp3_path}")
    print(f"  Transcript: {flat_path}")
    print(f"  Output: {output_path}")
    print("(This may take several minutes for long recordings)")

    # Use curl for the alignment
    result = subprocess.run(
        [
            'curl', '-f',
            '-F', f'audio=@{mp3_path}',
            '-F', f'transcript=@{flat_path}',
            'http://localhost:8765/transcriptions?async=false',
            '-o', str(output_path),
            '--progress-bar'
        ],
        capture_output=False
    )

    if result.returncode != 0:
        print("Alignment failed")
        return False

    if output_path.exists() and output_path.stat().st_size > 0:
        # Show summary
        import json
        try:
            with open(output_path) as f:
                data = json.load(f)
            word_count = len(data.get('words', []))
            print(f"\nAlignment complete. Words aligned: {word_count}")
        except json.JSONDecodeError:
            print("\nAlignment complete (could not parse output for summary)")
        return True
    else:
        print("Alignment may have failed - output file empty or missing")
        return False


def load_oyez_cache():
    """Load the Oyez advocates cache."""
    cache_file = BASE_DIR / "oyez-advocates-cache.json"
    if not cache_file.exists():
        return {}
    try:
        with open(cache_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def parse_appearances_section(txt_path):
    """
    Parse the APPEARANCES section from transcript to extract attorney info.
    Returns a dict mapping last_name (lowercase) to parsed info.
    """
    try:
        with open(txt_path) as f:
            text = f.read()
    except IOError:
        return {}

    # Find APPEARANCES section
    appearances_match = re.search(
        r'APPEARANCES:(.*?)(?:C\s*O\s*N\s*T\s*E\s*N\s*T\s*S|ORAL ARGUMENT)',
        text,
        re.DOTALL | re.IGNORECASE
    )
    if not appearances_match:
        return {}

    appearances_text = appearances_match.group(1)
    results = {}

    # Pattern to match attorney entries like:
    # "GEN. D. JOHN SAUER, Solicitor General, ... on behalf of the Petitioners."
    # "AMIT AGARWAL, ESQUIRE, ... on behalf of the Respondents."
    # Match name, then look for "on behalf of" description
    lines = appearances_text.replace('\n', ' ').strip()

    # Split by common attorney prefixes to find entries
    entries = re.split(r'(?=(?:GEN\.|MR\.|MS\.|GENERAL)\s+[A-Z])', lines)

    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue

        # Try to extract name and description
        # Look for pattern: PREFIX NAME, TITLE, LOCATION; on behalf of PARTY
        behalf_match = re.search(r'on behalf of (?:the )?(\w+)', entry, re.IGNORECASE)
        description = f"for the {behalf_match.group(1).lower()}" if behalf_match else ""

        # Extract name - take everything before first comma or semicolon
        name_match = re.match(r'^(?:GEN\.|GENERAL|MR\.|MS\.)?\s*([A-Z][A-Z\s.]+?)(?:,|;|\s+ESQUIRE)', entry)
        if name_match:
            full_name = name_match.group(1).strip()
            # Clean up the name (convert from "D. JOHN SAUER" to "D. John Sauer")
            parts = full_name.split()
            cleaned_parts = []
            for part in parts:
                if len(part) <= 2 and part.endswith('.'):
                    cleaned_parts.append(part)  # Keep initials as-is
                else:
                    cleaned_parts.append(part.capitalize())
            full_name = ' '.join(cleaned_parts)

            # Extract last name (last word that's not an initial)
            last_name = None
            for part in reversed(parts):
                if not (len(part) <= 2 and part.endswith('.')):
                    last_name = part.capitalize()
                    break

            if last_name:
                key = last_name.lower()
                results[key] = {
                    "name": full_name,
                    "last_name": last_name,
                    "identifier": full_name.lower().replace(' ', '_').replace('.', ''),
                    "description": description,
                    "source": "transcript"
                }

    return results


def get_unknown_speakers(case):
    """Get speakers from parsed JSON that aren't justices (i.e., attorneys)."""
    json_path = BASE_DIR / case / f"{case}.json"
    if not json_path.exists():
        return []

    try:
        with open(json_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

    unknown = set()
    for turn in data:
        speaker = turn.get("speaker")
        if isinstance(speaker, str):
            unknown.add(speaker)

    return sorted(unknown)


def extract_last_name_from_speaker(speaker_str):
    """Extract last name from speaker string like 'GENERAL SAUER' or 'MR. AGARWAL'."""
    # Remove prefix
    name = re.sub(r'^(GENERAL|MR\.|MS\.|CHIEF JUSTICE|JUSTICE)\s*', '', speaker_str)
    # Return the remaining part (should be the last name)
    return name.strip()


def resolve_attorney_info(speaker_str, oyez_cache, appearances_info):
    """
    Find possible matches for an attorney from Oyez cache and APPEARANCES parsing.
    Returns list of possible matches.
    """
    last_name = extract_last_name_from_speaker(speaker_str)
    key = last_name.lower()

    matches = []

    # Check Oyez cache
    if key in oyez_cache:
        for entry in oyez_cache[key]:
            match = entry.copy()
            match["source"] = "oyez"
            matches.append(match)

    # Check APPEARANCES parsing
    if key in appearances_info:
        entry = appearances_info[key].copy()
        # Check if this is different from Oyez matches
        existing_ids = [m.get("identifier") for m in matches]
        if entry.get("identifier") not in existing_ids:
            matches.append(entry)

    return matches


def run_lineup(case):
    """Run the line-up tool to create the final audio JSON."""
    case_dir = BASE_DIR / case
    json_path = case_dir / f"{case}.json"
    timed_path = case_dir / f"{case}.timed.json"
    txt_path = case_dir / f"{case}.txt"

    # Check required files
    if not json_path.exists():
        print(f"Error: Parsed transcript not found: {json_path}")
        print("Run 'Parse transcript' first.")
        return False

    if not timed_path.exists():
        print(f"Error: Timed transcript not found: {timed_path}")
        print("Run 'Run gentle aligner' first.")
        return False

    # Find unknown speakers (attorneys)
    unknown_speakers = get_unknown_speakers(case)
    if not unknown_speakers:
        print("No attorneys found in transcript (only justices).")
        print("This is unusual - please check the parsed transcript.")
        return False

    print(f"Found {len(unknown_speakers)} attorney(s) to identify:")
    for s in unknown_speakers:
        print(f"  - {s}")
    print()

    # Load Oyez cache and parse APPEARANCES
    oyez_cache = load_oyez_cache()
    appearances_info = parse_appearances_section(txt_path) if txt_path.exists() else {}

    if appearances_info:
        print(f"Parsed {len(appearances_info)} attorney(s) from APPEARANCES section")
    if oyez_cache:
        print(f"Loaded {len(oyez_cache)} last names from Oyez cache")
    print()

    # Resolve each attorney
    speakers_config = {}

    for speaker_str in unknown_speakers:
        print(f"Resolving: {speaker_str}")
        matches = resolve_attorney_info(speaker_str, oyez_cache, appearances_info)

        if not matches:
            print("  No matches found in Oyez or APPEARANCES.")
            # Create a template for manual entry
            last_name = extract_last_name_from_speaker(speaker_str)
            matches = [{
                "name": f"[Enter full name for {last_name}]",
                "last_name": last_name,
                "identifier": last_name.lower().replace(' ', '_'),
                "description": "[Enter description, e.g., 'for the petitioner']",
                "source": "manual"
            }]

        # Let user select from matches
        if len(matches) == 1:
            selected = matches[0]
            print(f"  Found: {selected['name']} ({selected['source']})")
            confirm = questionary.confirm(
                f"  Use this? ({selected['name']}, {selected.get('description', 'no description')})",
                default=True,
                style=custom_style
            ).ask()
            if not confirm:
                selected = None
        else:
            choices = []
            for m in matches:
                label = f"{m['name']} - {m.get('description', 'no description')} [{m['source']}]"
                choices.append(Choice(label, value=m))
            choices.append(Choice("Enter manually", value=None))

            selected = questionary.select(
                f"  Select match for {speaker_str}:",
                choices=choices,
                style=custom_style
            ).ask()

        # Allow manual editing
        if selected is None:
            last_name = extract_last_name_from_speaker(speaker_str)
            selected = {
                "name": questionary.text(
                    "  Full name:",
                    default=last_name.title(),
                    style=custom_style
                ).ask(),
                "last_name": last_name.title(),
                "identifier": "",
                "description": questionary.text(
                    "  Description (e.g., 'for the petitioner'):",
                    style=custom_style
                ).ask() or ""
            }
            selected["identifier"] = selected["name"].lower().replace(' ', '_').replace('.', '')
            selected["last_name"] = selected["name"].split()[-1] if selected["name"] else last_name.title()

        # Offer to edit
        edit = questionary.confirm("  Edit this entry?", default=False, style=custom_style).ask()
        if edit:
            selected["name"] = questionary.text("  Name:", default=selected.get("name", ""), style=custom_style).ask()
            selected["last_name"] = questionary.text("  Last name:", default=selected.get("last_name", ""), style=custom_style).ask()
            selected["identifier"] = questionary.text("  Identifier:", default=selected.get("identifier", ""), style=custom_style).ask()
            selected["description"] = questionary.text("  Description:", default=selected.get("description", ""), style=custom_style).ask()

        # Store config (remove 'source' field)
        config_entry = {
            "name": selected["name"],
            "last_name": selected["last_name"],
            "identifier": selected["identifier"],
            "description": selected["description"],
        }
        speakers_config[speaker_str] = config_entry
        print(f"  Saved: {config_entry['name']} ({config_entry['identifier']})")
        print()

    # Generate the line-up.py file
    lineup_path = case_dir / "line-up.py"
    print(f"Generating {lineup_path}...")

    # Format the speakers dict
    speakers_str = "{\n"
    for speaker_key, info in speakers_config.items():
        speakers_str += f'    "{speaker_key}": {{\n'
        speakers_str += f'        "name": "{info["name"]}",\n'
        speakers_str += f'        "last_name": "{info["last_name"]}",\n'
        speakers_str += f'        "identifier": "{info["identifier"]}",\n'
        speakers_str += f'        "description": "{info["description"]}",\n'
        speakers_str += f'    }},\n'
    speakers_str += "}"

    lineup_code = f'''import json
import re

speakers = {speakers_str}

transcript = json.load(open('{case}.json'))
times = json.load(open('{case}.timed.json'))
words = times["words"]

offset = 0
word_index = 0
for turn in transcript:
    turn["times"] = []
    for paragraph in turn["paragraphs"]:
        while words[word_index]["startOffset"] < offset:
            word_index += 1
        first_word = paragraph.split()[0]
        # remove punctuation
        first_word = re.sub(r'[^\\w\\s]', '', first_word)
        found_word = words[word_index]["word"]
        # remove punctuation
        found_word = re.sub(r'[^\\w\\s]', '', found_word)
        if first_word != found_word:
            print(f"Warning: Expected {{first_word}}, found {{found_word}}")
        offset += len(paragraph) + 1 # +1 for newline
        # some words are not found in the timed transcript, so search for the next found timestamp
        found_word_index = word_index
        while "start" not in words[found_word_index]:
            found_word_index += 1
        turn["times"].append(round(words[found_word_index]["start"], 2))

# make oyez-compatible file

section_titles = set()
sections = []
global_text_blocks = []
for i, turn in enumerate(transcript):
    if turn["section"] not in section_titles:
        # new section
        section_titles.add(turn["section"])
        turns = []
        for turn_in_section in transcript[i:]:
            if turn_in_section["section"] == turn["section"]:
                speaker = turn_in_section["speaker"]
                if isinstance(speaker, str):
                    speaker = speakers[speaker]
                text_blocks = []
                for text, time in zip(turn_in_section["paragraphs"], turn_in_section["times"]):
                    text_block = {{
                        "text": text,
                        "start": time
                    }}
                    text_blocks.append(text_block)
                    global_text_blocks.append(text_block)
                turn_object = {{
                    "speaker": speaker,
                    "start": turn_in_section["times"][0],
                    "text_blocks": text_blocks
                }}
                turns.append(turn_object)
            else:
                break
        section = {{
            "title": turn["section"],
            "start": turn["times"][0],
            "turns": turns
        }}
        sections.append(section)
# go through all turns backwards to add end times
for i, turn in enumerate(global_text_blocks):
    if i < len(global_text_blocks) - 1:
        turn["stop"] = global_text_blocks[i + 1]["start"]
    else:
        turn["stop"] = round(words[-1]["end"],2)
oyez_object = {{
    "transcript": {{"sections": sections}}
}}

# Determine output filename (you may want to change this)
output_file = "{case}-audio.json"
json.dump(oyez_object, open(output_file, 'w'), indent=2)
print(f"Created {{output_file}}")
'''

    with open(lineup_path, 'w') as f:
        f.write(lineup_code)

    print(f"Created {lineup_path}")
    print()

    # Ask if user wants to run it
    run_it = questionary.confirm("Run line-up.py now?", default=True, style=custom_style).ask()
    if run_it:
        result = subprocess.run(
            ['python3', 'line-up.py'],
            cwd=case_dir,
            capture_output=True,
            text=True
        )
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
        if result.returncode == 0:
            print("Line-up complete!")
            return True
        else:
            print(f"Line-up failed with return code {result.returncode}")
            return False

    return True


def get_case_status(case):
    """Get the processing status of a case"""
    case_dir = BASE_DIR / case
    status = []

    if list(case_dir.glob('*.pdf')):
        status.append('PDF')
    if (case_dir / f'{case}.mp3').exists():
        status.append('MP3')
    if (case_dir / f'{case}.txt').exists():
        status.append('TXT')
    if (case_dir / f'{case}.json').exists():
        status.append('JSON')
    if (case_dir / f'{case}.flat.txt').exists():
        status.append('FLAT')
    if (case_dir / f'{case}.timed.json').exists():
        status.append('TIMED')
    if list(case_dir.glob('*-audio.json')):
        status.append('DONE')

    return status


def main():
    print("\n" + "=" * 50)
    print("  SCOTUS Transcript Processing Tool")
    print("=" * 50 + "\n")

    while True:
        # Q1: Existing or fetch?
        action = questionary.select(
            "What would you like to do?",
            choices=[
                "Work on existing case",
                "Fetch new cases from SCOTUS",
                "Exit"
            ],
            style=custom_style
        ).ask()

        if action == "Exit" or action is None:
            print("Goodbye!")
            break

        selected_case = None

        if action == "Work on existing case":
            # Q2: Select existing case
            cases = get_existing_cases()
            if not cases:
                print("No existing cases found.\n")
                continue

            choices = []
            for case in cases:
                status = get_case_status(case)
                status_str = f" [{', '.join(status)}]" if status else ""
                choices.append(f"{case}{status_str}")
            choices.append("← Back")

            choice = questionary.select(
                "Select a case:",
                choices=choices,
                style=custom_style
            ).ask()

            if choice == "← Back" or choice is None:
                continue

            selected_case = choice.split()[0]  # Extract case number

        else:  # Fetch new cases
            print("\nFetching cases from supremecourt.gov...")
            cases = fetch_scotus_cases()

            if not cases:
                print("No cases found or error fetching.\n")
                continue

            choices = []
            for case in cases:
                has_materials = case['transcript_url'] and case['has_audio']
                status = "✓" if has_materials else "✗"
                label = f"{status} {case['docket']}: {case['name']}"
                choices.append(Choice(
                    label,
                    value=case,
                    disabled=None if has_materials else "No transcript/audio yet"
                ))
            choices.append(Choice("← Back", value=None))

            choice = questionary.select(
                "Select a case to download:",
                choices=choices,
                style=custom_style
            ).ask()

            if choice is None or not isinstance(choice, dict):
                continue

            # Download the case
            print()
            selected_case = download_case_materials(choice)
            print()

        if not selected_case:
            continue

        # Q3: Tool selection loop
        while True:
            status = get_case_status(selected_case)
            status_str = f" [{', '.join(status)}]" if status else ""

            tool = questionary.select(
                f"Case {selected_case}{status_str} - Select tool:",
                choices=[
                    "Convert PDF to text",
                    "Parse transcript",
                    "Run gentle aligner",
                    "Line up",
                    "← Back to main menu"
                ],
                style=custom_style
            ).ask()

            if tool == "← Back to main menu" or tool is None:
                break

            print()  # Add spacing

            if tool == "Convert PDF to text":
                run_convert_to_text(selected_case)
            elif tool == "Parse transcript":
                run_parse_transcript(selected_case)
            elif tool == "Run gentle aligner":
                run_gentle(selected_case)
            elif tool == "Line up":
                run_lineup(selected_case)

            print()  # Add spacing after tool runs


if __name__ == '__main__':
    main()
