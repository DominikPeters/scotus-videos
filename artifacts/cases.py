#!/usr/bin/env python3
"""Find the first mention of each cited case in an argument and build case cards.

Citations come from the docket PDFs indexed by `pipeline.py fetch`, so names, years
and reporters are exact even when the transcript garbles a name. A model picks the
first mention of each cited case (disambiguating e.g. "Sawyer" or "Reagan"). Supreme
Court cases are looked up on Oyez by citation, and Oyez's conclusion is condensed into
a one-sentence holding. Output: artifacts/output/CASE/cases.json (for review), and
optionally case cues merged into a mockup cue file.
"""
import argparse
from collections import Counter, OrderedDict
import difflib
import html
import json
from pathlib import Path
import re

import requests

from pipeline import OUTPUT, ROOT, NUM, STR, ask_model, index_document, read_json, schema, transcript, write_json

REPORTERS = (r"U\.\s?S\.|S\.\s?Ct\.|L\.\s?Ed\.(?:\s?2d)?|F\.\s?Supp\.(?:\s?(?:2d|3d))?|F\.\s?App(?:'|’)x|F\.(?:\s?(?:2d|3d|4th))?"
             r"|A\.(?:\s?(?:2d|3d))?|P\.(?:\s?(?:2d|3d))?|N\.E\.(?:\s?(?:2d|3d))?|N\.W\.(?:\s?2d)?|S\.E\.(?:\s?2d)?"
             r"|S\.W\.(?:\s?(?:2d|3d))?|So\.(?:\s?(?:2d|3d))?|Ct\.\s?Cl\.|N\.J\.L\.|Wall\.|Pet\.|How\.|Cranch|Wheat\.|Dall\.")
PARTY = r"(?:[A-Z][\w.'’&\-]*|of|the|and|for|ex|rel\.|de|la|du|von|van|&)"
NAME = rf"(?:(?:In re|Ex parte) {PARTY}(?: {PARTY}){{0,6}}|{PARTY}(?: {PARTY}){{0,8}} v\. {PARTY}(?: {PARTY}){{0,8}})"
CITATION = re.compile(rf"(?P<name>{NAME}),\s+(?P<vol>\d{{1,4}})\s+(?P<rep>{REPORTERS})\s+(?P<page>\d{{1,5}}|_+)"
                      rf"[^()]{{0,60}}?\((?P<court>[^()]*?)\s*(?P<year>1[6-9]\d\d|20\d\d)\)")
# Words that precede a case name in running text (citation signals, sentence fragments).
LEADING = re.compile(r"^(?:(?:See|see|Cf\.|cf\.|E\.g\.,|e\.g\.,|also|accord|Accord|But|but|Compare|compare|with|and|quoting|citing"
                     r"|The|the|As|as|Under|under|Following|of|Page|CASES|Cases|TABLE|OF|AUTHORITIES|In(?! re))\s+)+")
GENERIC = set("united states america v in re ex parte rel of the and for board co corp inc ltd llc company commission dept department "
              "state people city county commissioners comm’rs commrs bd educ ass’n assn national am school".split())
OYEZ_RANGES = [(1789, 1850), (1850, 1900), (1900, 1940), (1940, 1955)]


def authorities(case):
    """Every case cited in the indexed docket PDFs, keyed by citation."""
    folder = OUTPUT / case
    documents = [d for d in read_json(folder / "catalog.json") if d.get("pdf") and not d.get("excluded")]
    found = OrderedDict()
    for doc in documents:
        for page in index_document(doc, folder):
            text = re.sub(r"(\w)-\s+(?=[a-z])", r"\1", page["text"])
            for m in CITATION.finditer(text):
                name = LEADING.sub("", m["name"]).strip()
                name = drop_preceding_sentence(name)
                reporter = re.sub(r"\s", "", m["rep"]).replace("S.Ct.", "S. Ct.").replace("U.S.", "U.S.")
                key = f'{m["vol"]} {reporter} {m["page"]}'
                entry = found.setdefault(key, {"id": key, "names": Counter(), "year": int(m["year"]),
                                               "court": m["court"].strip(" ,"), "documents": Counter()})
                entry["names"][name] += 1
                entry["documents"][doc["id"]] += 1
    result = []
    for entry in found.values():
        names = [n for n, _ in entry["names"].most_common()]
        # Prefer the most frequent full-looking variant (abbreviated names can lose their first party).
        best = max(names[:3], key=lambda n: (entry["names"][n] >= entry["names"][names[0]] / 2, len(n)))
        result.append({"id": entry["id"], "name": best, "variants": names[:4], "year": entry["year"],
                       "court": entry["court"], "supreme_court": " U.S. " in f' {entry["id"]} ' or "S. Ct." in entry["id"],
                       "citations": sum(entry["names"].values())})
    return result


def drop_preceding_sentence(name):
    # "Supreme Court. Collins v. Yellen" -> "Collins v. Yellen", but keep "Consumer Fin. Prot. Bureau".
    parts = re.split(r"(?<=[a-z]{3})\. (?=[A-Z])", name)
    for i in range(len(parts) - 1, -1, -1):
        suffix = ". ".join(parts[i:])
        if " v. " in suffix or suffix.startswith(("In re ", "Ex parte ")):
            return suffix
    return name


def distinctive_words(names):
    words = set()
    for name in names:
        for word in re.findall(r"[A-Za-z’']+", name):
            if len(word) > 2 and word.lower() not in GENERIC:
                words.add(word.lower().strip("’'"))
    return words


def spoken_names(evidence, authority):
    """The words in the evidence that name the case (for highlighting in the transcript)."""
    words = distinctive_words([authority["name"]])  # the cleaned name, not every variant found in the briefs
    found = {w for w in re.findall(r"[A-Za-z’']+", evidence)
             if any(difflib.SequenceMatcher(None, d, w.lower().strip("’'")).ratio() >= 0.75 for d in words)}
    # prefer the full spoken name ("Trump against United States") over a bare party name
    party = r"[A-Z][\w’'.]*(?: (?:of|the|and|[A-Z][\w’'.]*))*"
    for match in re.finditer(rf"{party} (?:against|versus|v\.) {party}", evidence):
        if any(w in match.group() for w in found):
            return [match.group()]
    return sorted(found)


def mentions_name(evidence, authority):
    spoken = [w.lower() for w in re.findall(r"[A-Za-z’']+", evidence)]
    for word in distinctive_words(authority["variants"]):
        if any(difflib.SequenceMatcher(None, word, s).ratio() >= 0.75 for s in spoken):
            return True
    return False


def first_exact_mention(rows, start, authority):
    words = distinctive_words(authority["variants"])
    for row in rows[start:]:
        for match in re.finditer(r"[A-Za-z’']+", row["text"]):
            if match.group().lower().strip("’'") in words:
                return row, row["text"][max(0, match.start() - 30):match.end() + 30].strip()
    return None


REFERENCE = schema({"authority_id": STR, "block_id": STR, "evidence": STR,
                    "salience": {"type": "string", "enum": ["discussed", "passing"]}, "reason": STR})


def detect(case, model, engine):
    folder = OUTPUT / case
    rows = transcript(case)
    cited = authorities(case)
    write_json(folder / "authorities.json", cited)
    prompt = f"""Below are (1) the complete transcript of a Supreme Court oral argument, as numbered text blocks, and (2) the cases cited in the parties' and amici's filings.
Find every listed case that a speaker refers to BY NAME. Speakers say "against" or "versus" for "v." and often use a short name ("Sawyer", "Humphrey's", "Wilcox"); the transcript may misspell names ("Hagertown" for Hagerstown). Disambiguate with context: several cases can share a party name (e.g. "In re Sawyer" vs "Youngstown Sheet & Tube Co. v. Sawyer"), and a name can refer to a person rather than a case (e.g. President Reagan vs "Reagan v. United States"). Ignore cases referred to only indirectly ("our cases", "that decision").
For each referenced case return ONE item: the FIRST block where it is named, evidence = a verbatim substring of that block containing the name, and salience = "discussed" if any speaker relies on, explains or argues about the case anywhere in the argument, "passing" if it is only named in a list. Return each authority_id at most once; use only ids from the list.
CITED CASES: {json.dumps([{k: a[k] for k in ("id", "name", "year", "court")} for a in cited], ensure_ascii=False)}
TRANSCRIPT: {json.dumps([{"id": r["id"], "speaker": r["speaker"]["name"], "text": r["text"]} for r in rows], ensure_ascii=False)}"""
    result = ask_model(folder, model, "cases-detect", prompt, schema({"references": {"type": "array", "items": REFERENCE}}), engine)
    by_id = {a["id"]: a for a in cited}
    blocks = {r["id"]: r for r in rows}
    references, rejected, seen = [], [], set()
    for item in result["references"]:
        authority, block = by_id.get(item["authority_id"]), blocks.get(item["block_id"])
        if authority and block and item["evidence"] in block["text"] and not mentions_name(item["evidence"], authority):
            # The speaker misnamed the case (e.g. "Drago" for Delgado): use the first exact mention instead.
            exact = first_exact_mention(rows, rows.index(block), authority)
            if exact:
                block, item = exact[0], item | {"block_id": exact[0]["id"], "evidence": exact[1]}
        problem = ("unknown authority" if authority is None else "unknown block" if block is None
                   else "duplicate" if item["authority_id"] in seen
                   else "evidence not verbatim" if not item["evidence"] or " ".join(item["evidence"].split()) not in " ".join(block["text"].split())
                   else "evidence does not contain the case name" if not mentions_name(item["evidence"], authority) else None)
        if problem:
            rejected.append(item | {"rejected": problem})
            continue
        seen.add(item["authority_id"])
        references.append(item | {"start": block["start"], "stop": block["stop"], "speaker": block["speaker"]["name"]})
    references.sort(key=lambda r: r["start"])
    return cited, references, rejected


def oyez_case(folder, authority):
    """Oyez case record for a U.S. Reports citation, or None."""
    match = re.fullmatch(r"(\d+) U\.S\. (\d+)", authority["id"])
    if not match:
        return None
    volume, page = match.groups()
    year = authority["year"]
    terms = [str(t) for t in (year - 1, year) if t >= 1955]
    terms += [f"{a}-{b}" for a, b in OYEZ_RANGES if a <= year <= b + 1]
    for term in terms:
        path = OUTPUT / "oyez" / f"term-{term}.json"
        if not path.exists():
            response = requests.get("https://api.oyez.org/cases", params={"filter": f"term:{term}", "per_page": 0}, timeout=60)
            response.raise_for_status()
            write_json(path, response.json())
        listing = read_json(path)
        exact = [e for e in listing if (e.get("citation") or {}).get("volume") == volume and (e.get("citation") or {}).get("page") == page]
        # Recent cases often have no page number on Oyez yet: match the volume and a party name instead.
        words = distinctive_words(authority["variants"])
        by_name = [e for e in listing if (e.get("citation") or {}).get("volume") == volume and not (e.get("citation") or {}).get("page")
                   and words & distinctive_words([e["name"]])]
        for entry in (exact or by_name[:1]):
                detail_path = OUTPUT / "oyez" / (entry["href"].split("/cases/")[-1].replace("/", "_") + ".json")
                if not detail_path.exists():
                    response = requests.get(entry["href"], timeout=60)
                    response.raise_for_status()
                    write_json(detail_path, response.json())
                return read_json(detail_path)
    return None


def cap_case(authority):
    """Caselaw Access Project record (with the reporter's syllabus as head matter) for a U.S. Reports citation."""
    match = re.fullmatch(r"(\d+) U\.S\. (\d+)", authority["id"])
    if not match:
        return None
    volume = match.group(1)
    meta_path = OUTPUT / "cap" / f"us-{volume}-metadata.json"
    if not meta_path.exists():
        response = requests.get(f"https://static.case.law/us/{volume}/CasesMetadata.json", timeout=60)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        write_json(meta_path, response.json())
    entry = next((e for e in read_json(meta_path) if any(c.get("cite") == authority["id"] for c in e.get("citations", []))), None)
    if entry is None:
        return None
    path = OUTPUT / "cap" / f'us-{volume}-{entry["file_name"]}.json'
    if not path.exists():
        response = requests.get(f'https://static.case.law/us/{volume}/cases/{entry["file_name"]}.json', timeout=60)
        response.raise_for_status()
        write_json(path, response.json())
    return read_json(path)


def summary_source(folder, authority):
    """Name, year, vote and the text a holding may be based on: Oyez first, else the official syllabus."""
    record = oyez_case(folder, authority)
    if record and plain(record.get("conclusion")):
        return {"name": record["name"], "year": (record.get("citation") or {}).get("year") or authority["year"],
                "vote": vote(record), "basis": "Oyez question and conclusion",
                "text": f'Question: {plain(record.get("question"))}\nConclusion: {plain(record.get("conclusion"))}',
                "credit": "Summary based on Oyez (oyez.org)", "url": record.get("href")}
    record = cap_case(authority)
    head = plain((record or {}).get("casebody", {}).get("head_matter"))
    if head:
        return {"name": record.get("name_abbreviation") or authority["name"], "year": record.get("decision_date", "")[:4] or authority["year"],
                "vote": None, "basis": "syllabus (reporter's head matter) from the U.S. Reports",
                "text": head[:2500], "credit": "Summary based on the official syllabus (U.S. Reports)",
                "url": f'https://static.case.law/us/{authority["id"].split()[0]}/cases/{record.get("file_name")}.json'}
    return None


def plain(text):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def vote(record):
    decisions = [d for d in record.get("decisions") or [] if d]
    if len(decisions) != 1:
        return None  # no decision recorded, or several (split) decisions
    decision = decisions[0]
    majority, minority = decision.get("majority_vote"), decision.get("minority_vote")
    if majority is None or minority is None:
        return None
    return "unanimous" if minority == 0 else f"decided {majority}–{minority}"


def italic_name(name):
    name = html.escape(name, quote=False)
    if " v. " in name:
        a, b = name.split(" v. ", 1)
        return f"<i>{a}</i> v. <i>{b}</i>"
    return f"<i>{name}</i>"


HOLDING = schema({"authority_id": STR, "holding": STR, "confidence": NUM})


def summarize(folder, model, engine, entries):
    if not entries:
        return {}
    prompt = """For each case, write ONE sentence (at most 35 words) for a viewer of an oral argument video saying what the Supreme Court held. Start with "The Court held that", use the past tense, stay neutral, and use ONLY facts stated in the supplied basis text (Oyez's question and conclusion, or the official syllabus from the U.S. Reports, which may continue into a statement of facts); do not add later history or evaluate the decision. If the case decided several questions, state only the holding most relevant to the excerpt in which a speaker mentions it (the excerpt is context, not a source). If the basis does not state a holding clearly, return an empty holding and low confidence.
CASES: """ + json.dumps(entries, ensure_ascii=False)
    result = ask_model(folder, model, "cases-holdings", prompt, schema({"holdings": {"type": "array", "items": HOLDING}}), engine)
    return {h["authority_id"]: h for h in result["holdings"]}


def build(case, model, engine, card_seconds, include_passing, merge_into):
    folder = OUTPUT / case
    cited, references, rejected = detect(case, model, engine)
    by_id = {a["id"]: a for a in cited}
    sources, unresolved = {}, []
    for ref in references:
        authority = by_id[ref["authority_id"]]
        if not include_passing and ref["salience"] == "passing":
            unresolved.append(ref | {"reason": "Only named in passing"})
            continue
        source = summary_source(folder, authority) if authority["supreme_court"] else None
        if source is None:
            unresolved.append(ref | {"reason": "No summary source (not a U.S. Reports case, or neither Oyez nor the syllabus is available)"})
            continue
        sources[ref["authority_id"]] = source
    holdings = summarize(folder, model, engine, [
        {"authority_id": key, "name": source["name"], "basis": source["basis"], "text": source["text"],
         "mentioned_in": next(r["evidence"] for r in references if r["authority_id"] == key)}
        for key, source in sources.items()])
    cards = []
    for ref in references:
        source, holding = sources.get(ref["authority_id"]), holdings.get(ref["authority_id"])
        if source is None:
            continue
        sentence = (holding or {}).get("holding", "").strip()
        if not sentence or len(sentence.split()) > 45 or not sentence.startswith("The Court held"):
            unresolved.append(ref | {"reason": "No usable holding sentence"})
            continue
        details = " · ".join(x for x in (str(source["year"]), source["vote"]) if x)
        cards.append({"id": "case-" + re.sub(r"\W+", "-", ref["authority_id"]).strip("-").lower(),
                      "start": ref["start"], "end": ref["start"] + card_seconds, "kind": "Case", "label": "", "heading": "",
                      "case": {"name": italic_name(source["name"]), "details": details},
                      "text": html.escape(sentence, quote=False), "source": source["credit"], "date": "",
                      "highlight": spoken_names(ref["evidence"], by_id[ref["authority_id"]]),
                      "block": ref["block_id"], "evidence": ref["evidence"], "speaker": ref["speaker"],
                      "citation": ref["authority_id"], "source_url": source["url"], "basis": source["text"],
                      "confidence": holding.get("confidence"), "reviewed": False})
    write_json(folder / "cases.json", {"case": case, "engine": engine, "model": model, "cards": cards,
                                        "unresolved": unresolved, "rejected": rejected,
                                        "limitations": ["Holdings are condensed by a model from Oyez or the official syllabus: review each card against its basis.",
                                                        "Later history (overruling, narrowing) is not checked.",
                                                        "Only Supreme Court cases get cards; lower-court and state cases are listed as unresolved."]})
    print(f"{len(cited)} cited cases; {len(references)} named in the argument; {len(cards)} cards; {len(unresolved)} unresolved; {len(rejected)} rejected")
    if merge_into:
        merge(merge_into, cards)


def merge(path, cards):
    """Replace the case cues in a mockup cue file, skipping cards that would collide with other cues."""
    path = Path(path)
    data = read_json(path) if path.exists() else {"cues": []}
    others = [c for c in data["cues"] if c.get("kind") != "Case"]
    accepted = []
    for card in cards:
        busy = others + accepted
        # cards may abut (the renderer stacks the next card onto the previous one), but not start inside another
        if any(c["start"] <= card["start"] < c["end"] for c in busy):
            print(f'  skipped {card["id"]}: starts while another card is shown')
            continue
        following = [c["start"] for c in busy if c["start"] > card["start"]]
        if following:
            card = card | {"end": min(card["end"], min(following))}
        accepted.append(card)
    data["cues"] = sorted(others + accepted, key=lambda c: c["start"])
    write_json(path, data)
    print(f"Merged {len(accepted)} case cards into {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    parser.add_argument("--engine", choices=["openai", "codex"], default="codex")
    parser.add_argument("--model", default=None, help="Model name (default: gpt-6-luna for openai, Codex's default for codex)")
    parser.add_argument("--card-seconds", type=float, default=12)
    parser.add_argument("--include-passing", action="store_true", help="Also make cards for cases only named in passing")
    parser.add_argument("--merge-into", type=Path, help="Mockup cue file to update, e.g. mockup-quotes/25A312.json")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9-]+", args.case):
        parser.error("Case ID must contain only letters, numbers and hyphens")
    model = args.model or ("gpt-6-luna" if args.engine == "openai" else None)
    try:
        build(args.case, model, args.engine, args.card_seconds, args.include_passing, args.merge_into)
    except (ValueError, requests.RequestException) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
