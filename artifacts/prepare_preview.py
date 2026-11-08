#!/usr/bin/env python3
"""Stage only public case/display assets for a narrowly scoped local server."""
import argparse
from pathlib import Path
import re
import shutil
from pipeline import ROOT, OUTPUT, read_json


def prepare(case):
    folder = OUTPUT / case
    manifest = read_json(folder / "manifest.json")
    metadata = read_json(ROOT / manifest["metadata"].lstrip("/"))
    preview = folder / "preview"
    paths = {"artifact-player.html", "artifacts/player.css", "artifacts/player.js", "seal.svg",
             manifest["audio"].lstrip("/"), manifest["metadata"].lstrip("/"), manifest["transcript"].lstrip("/"),
             f"artifacts/output/{case}/manifest.json"}
    for cue in manifest["cues"]:
        paths.update([cue["image"].lstrip("/"), cue["full_page_image"].lstrip("/")])
    for justice in metadata["heard_by"][0]["members"]:
        paths.add("justices/" + justice["thumbnail"]["href"].split("/")[-1])
    for advocate in metadata["advocates"]:
        image = "advocates/" + advocate["advocate"]["identifier"] + ".jpg"
        if (ROOT / image).exists(): paths.add(image)
    # Rebuild the public bundle to avoid stale files; it never includes secrets.
    if preview.exists(): shutil.rmtree(preview)
    preview.mkdir(parents=True)
    for relative in paths:
        source = (ROOT / relative).resolve()
        target = (preview / relative).resolve()
        if not source.is_relative_to(ROOT) or not target.is_relative_to(preview):
            raise ValueError("Asset path is outside the project or preview")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    print(preview)
    return preview


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', default='25A312')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9-]+', args.case): parser.error('Invalid case ID')
    prepare(args.case)
