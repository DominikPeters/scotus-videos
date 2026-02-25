import sys
import re
import json

justices = {
    "CHIEF JUSTICE ROBERTS": {
        "name": "John G. Roberts, Jr.",
        "last_name": "Roberts",
        "identifier": "john_g_roberts_jr"
    },
    "JUSTICE ROBERTS": {
        "name": "John G. Roberts, Jr.",
        "last_name": "Roberts",
        "identifier": "john_g_roberts_jr"
    },
    "JUSTICE THOMAS": {
        "name": "Clarence Thomas",
        "last_name": "Thomas",
        "identifier": "clarence_thomas"
    },
    "JUSTICE ALITO": {
        "name": "Samuel A. Alito, Jr.",
        "last_name": "Alito",
        "identifier": "samuel_a_alito_jr"
    },
    "JUSTICE SOTOMAYOR": {
        "name": "Sonia Sotomayor",
        "last_name": "Sotomayor",
        "identifier": "sonia_sotomayor"
    },
    "JUSTICE KAGAN": {
        "name": "Elena Kagan",
        "last_name": "Kagan",
        "identifier": "elena_kagan"
    },
    "JUSTICE GORSUCH": {
        "name": "Neil Gorsuch",
        "last_name": "Gorsuch",
        "identifier": "neil_gorsuch"
    },
    "JUSTICE KAVANAUGH": {
        "name": "Brett M. Kavanaugh",
        "last_name": "Kavanaugh",
        "identifier": "brett_m_kavanaugh"
    },
    "JUSTICE BARRETT": {
        "name": "Amy Coney Barrett",
        "last_name": "Barrett",
        "identifier": "amy_coney_barrett"
    },
    "JUSTICE JACKSON": {
        "name": "Ketanji Brown Jackson",
        "last_name": "Jackson",
        "identifier": "ketanji_brown_jackson"
    }
}

def clean_line(line):
    # Remove line numbers at the start of lines
    # line = re.sub(r'^\s*\d+\s*', '', line)
    # removed 2025-05-17, since it seems line numbers are not included in the Acrobat text export
    # and so actual numbers said in the argument were swallowed by the regex
    return line.strip()

def fix_split_speaker_names(text):
    """
    Fix speaker names that got split across lines in PDF export.
    E.g., "Why is that -GENERAL \nSAUER: --severability"
    becomes "Why is that -\nGENERAL SAUER: --severability"
    """
    # Speaker prefixes that can appear at end of line when split
    prefixes = ['GENERAL', 'JUSTICE', 'CHIEF', 'MR.', 'MS.', 'THE']

    lines = text.split('\n')
    fixed_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Check if line ends with a speaker prefix (with optional trailing space)
        moved_prefix = None
        for prefix in prefixes:
            if line.rstrip().endswith(prefix) or line.endswith(prefix + ' '):
                # Check if next line starts with NAME: pattern (completing the speaker)
                if i + 1 < len(lines):
                    next_line = lines[i + 1].lstrip()
                    # Match "LASTNAME:" or "JUSTICE LASTNAME:" (for CHIEF JUSTICE)
                    if re.match(r'^[A-Z\u00C0-\u017F]+:', next_line) or \
                       (prefix == 'CHIEF' and re.match(r'^JUSTICE [A-Z\u00C0-\u017F]+:', next_line)):
                        # Remove prefix from end of current line
                        line = line.rstrip()
                        if line.endswith(prefix + ' '):
                            line = line[:-len(prefix)-1]
                        elif line.endswith(prefix):
                            line = line[:-len(prefix)]
                        moved_prefix = prefix
                        break

        fixed_lines.append(line)

        # If we moved a prefix, prepend it to the next line
        if moved_prefix and i + 1 < len(lines):
            lines[i + 1] = moved_prefix + ' ' + lines[i + 1].lstrip()

        i += 1

    return '\n'.join(fixed_lines)

def parse_scotus_transcript(text):
    # Fix speaker names that got split across lines in PDF export
    text = fix_split_speaker_names(text)

    # Split into lines and remove empty lines
    lines = [clean_line(line) for line in text.split('\n')]
    lines = [line for line in lines if line.strip()]
    
    # Remove header content (everything before "P R O C E E D I N G S")
    for i, line in enumerate(lines):
        if "P R O C E E D I N G S" in line:
            lines = lines[i+1:]
            break
    
    # Initialize variables
    turns = []
    current_section = "BEGINNING"
    current_speaker = None
    current_paragraphs = []
    current_paragraph = []
    
    def save_current_turn():
        nonlocal current_speaker, current_paragraphs, current_paragraph, current_section
        if current_speaker and current_paragraph:
            current_paragraphs.append(' '.join(current_paragraph))
            next_section = None
            for i, para in enumerate(current_paragraphs):
                if para.startswith('ORAL ARGUMENT OF') or para.startswith('REBUTTAL ARGUMENT OF'):
                    next_section = para
                    current_paragraphs.pop(i)
                    if current_section == "BEGINNING":
                        current_section = para
            speaker_name = current_speaker.strip(':')
            if speaker_name in justices:
                speaker = justices[speaker_name]
            else:
                speaker = speaker_name
            turns.append({
                'speaker': speaker,
                'section': current_section,
                'paragraphs': current_paragraphs
            })
            if next_section:
                current_section = next_section
        current_paragraphs = []
        current_paragraph = []
    
    def starts_new_paragraph(line, prev_line):
        # Check if line starts with capital letter
        if not line[0].isupper():
            return False
        # If it's first line of turn, it's a new paragraph
        if not prev_line:
            return True
        # Check if previous line ends with sentence-ending punctuation
        return prev_line.rstrip().endswith(('.', '?', '!'))
    
    # Pattern to detect speakers - includes common speaker prefixes
    speaker_patterns = [
        r'^(CHIEF JUSTICE [A-Z\u00C0-\u017F]+:)',
        r'^(JUSTICE [A-Z\u00C0-\u017F]+:)',
        r'^(MR\. [A-Z\u00C0-\u017F]+:)',
        r'^(MS\. [A-Z\u00C0-\u017F]+:)',
        r'^(THE [A-Z \u00C0-\u017F]+:)',  # For "THE COURT:" etc.
        r'^(GENERAL [A-Z\u00C0-\u017F]+:)',
    ]
    
    prev_line = None
    
    for line in lines:
        # Skip pure numerical lines and common header/footer text
        if re.match(r'^\d+$', line.strip()) or 'Heritage Reporting Corporation' in line:
            continue

        # Check for new speaker using multiple patterns
        new_speaker = None
        for pattern in speaker_patterns:
            speaker_match = re.match(pattern, line)
            if speaker_match:
                new_speaker = speaker_match.group(1)
                break
                
        if new_speaker:
            # Save previous turn if exists
            save_current_turn()
            
            # Start new turn
            current_speaker = new_speaker
            # Remove speaker from line content
            line = line[len(current_speaker):].strip()
            if not line:  # If line only contained speaker, continue to next line
                continue
        
        # Handle paragraph breaks
        if current_paragraph and starts_new_paragraph(line, prev_line):
            current_paragraphs.append(' '.join(current_paragraph))
            current_paragraph = []
        
        # Add line to current paragraph
        if line:
            current_paragraph.append(line)
            
        prev_line = line
    
    # Save final turn
    save_current_turn()
    
    turns[-1]['paragraphs'][-1] = turns[-1]['paragraphs'][-1].split(' (Whereupon')[0]

    return turns

def format_transcript(turns):
    return json.dumps(turns, indent=2)

def validate_turns(turns):
    """
    Check for signs of parsing errors - orphaned speaker prefixes in turn text.
    These indicate a speaker name got split and merged into another turn.
    Returns list of warnings.
    """
    # Orphaned speaker prefixes that suggest a split speaker name
    # e.g., "Why is that -JUSTICE" with "THOMAS:" on next line
    # Look for these prefixes appearing in text (not at very start of turn)
    prefix_pattern = r'(?:^|[ -])(JUSTICE|GENERAL|MR\.|MS\.|CHIEF)(?: |$)'

    warnings = []
    for i, turn in enumerate(turns):
        speaker_name = turn['speaker'] if isinstance(turn['speaker'], str) else turn['speaker'].get('last_name', '')
        for j, para in enumerate(turn['paragraphs']):
            matches = list(re.finditer(prefix_pattern, para))
            for match in matches:
                # Skip if it's at the very beginning (that's normal for first para of a turn)
                if match.start() == 0 and j == 0:
                    continue
                # Get context around the match
                start = max(0, match.start() - 20)
                end = min(len(para), match.end() + 20)
                context = para[start:end]
                if start > 0:
                    context = '...' + context
                if end < len(para):
                    context = context + '...'
                warnings.append(f"Turn {i} ({speaker_name}), paragraph {j}: found orphaned '{match.group(1)}' in text: \"{context}\"")

    return warnings

# Example usage
if __name__ == "__main__":
    case = sys.argv[1]

    # Read input text
    with open(f"{case}/{case}.txt", 'r') as f:
        text = f.read()

    # Parse transcript
    turns = parse_scotus_transcript(text)

    # Validate and warn about potential parsing issues
    warnings = validate_turns(turns)
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)

    flat_transcript = []
    for turn in turns:
        for paragraph in turn['paragraphs']:
            flat_transcript.append(paragraph)
    with open(f"{case}/{case}.flat.txt", 'w') as f:
        f.write('\n'.join(flat_transcript))
    
    # Output formatted JSON
    with open(f"{case}/{case}.json", 'w') as f:
        f.write(format_transcript(turns))