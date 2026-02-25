#!/usr/bin/env python3
"""
Build a cache of all advocates from the local Oyez data mirror.
This speeds up lookups when matching attorneys in transcripts.
"""

import json
import os
from pathlib import Path

OYEZ_DIR = Path("/Users/dominik/GitHub/scotusstats/data-pipeline/oyez")
CACHE_FILE = Path(__file__).parent / "oyez-advocates-cache.json"


def build_cache():
    """Scan all Oyez case files and extract advocate information."""
    advocates = {}  # keyed by lowercase last_name

    if not OYEZ_DIR.exists():
        print(f"Error: Oyez directory not found: {OYEZ_DIR}")
        return

    file_count = 0
    advocate_count = 0

    for year_dir in sorted(OYEZ_DIR.iterdir()):
        if not year_dir.is_dir():
            continue

        for case_file in year_dir.glob("*.json"):
            # Skip transcript files
            if "_transcript.json" in case_file.name:
                continue

            file_count += 1

            try:
                with open(case_file) as f:
                    case_data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not read {case_file}: {e}")
                continue

            for adv_entry in case_data.get("advocates", []) or []:
                advocate = adv_entry.get("advocate")
                if not advocate:
                    continue

                last_name = advocate.get("last_name")
                if not last_name:
                    continue

                key = last_name.lower()
                entry = {
                    "name": advocate.get("name"),
                    "last_name": last_name,
                    "identifier": advocate.get("identifier"),
                    "description": adv_entry.get("advocate_description"),
                }

                # Store as list since multiple people might share a last name
                if key not in advocates:
                    advocates[key] = []

                # Avoid duplicates (same identifier)
                existing_ids = [a["identifier"] for a in advocates[key]]
                if entry["identifier"] not in existing_ids:
                    advocates[key].append(entry)
                    advocate_count += 1

    # Save cache
    with open(CACHE_FILE, "w") as f:
        json.dump(advocates, f, indent=2)

    print(f"Scanned {file_count} case files")
    print(f"Found {advocate_count} unique advocates")
    print(f"Cache saved to: {CACHE_FILE}")


if __name__ == "__main__":
    build_cache()
