import json
import requests
import subprocess
import sox
import os
import datetime
import time
import pickle
import sys
import re

# get url from command line
arg = sys.argv[1]
if "oyez.org" in arg:
    oyez_url = arg
    oyez_url = oyez_url.replace("www.", "api.")
    # get file and save it
    case_metadata = requests.get(oyez_url).json()
    case_number = case_metadata["ID"]
    case_metadata["docket_number"] = case_metadata["docket_number"].strip() # oyez sometimes has a space at the end
    json.dump(case_metadata, open(f"json/{case_number}.json", "w"), indent=4)
else:
    # interpret as case number
    if not os.path.exists(f"json/{arg}.json"):
        print(f"Case {arg} not found")
        exit()
    case_metadata = json.load(open(f"json/{arg}.json"))

def mp3_duration(filename):
    return sox.file_info.duration(filename)

case_metadata["docket_number"] = case_metadata["docket_number"].strip()

case_number = case_metadata["ID"]
docket_number = case_metadata["docket_number"]

# case_metadata = json.load(open(f"{case_number}.json"))
print(f"Handling case {case_number} [Docket {docket_number}] ({case_metadata['name']})")

# Load the oral argument transcript
if len(case_metadata["oral_argument_audio"]) > 1:
    print("Warning: More than one oral argument audio")
oral_argument_url = case_metadata["oral_argument_audio"][0]["href"]
oral_argument_transcript = requests.get(oral_argument_url).json()
json.dump(oral_argument_transcript, open(f"json/{case_number}-audio.json", "w"), indent=4)

# Check that we have justice images
for justice in case_metadata["heard_by"][0]["members"]:
    thumbnail_url = justice["thumbnail"]["href"]
    thumbnail_filename = thumbnail_url.split("/")[-1]
    if os.path.exists(f"justices/{thumbnail_filename}"):
        continue
    print(f"Downloading image of Justice {justice['name']}")
    # download image
    thumbnail = requests.get(thumbnail_url)
    with open(f"justices/{thumbnail_filename}", "wb") as file:
        file.write(thumbnail.content)

# Extract advocate information
advocates = {adv["advocate"]["name"]: (
                adv['advocate']['name'], 
                adv['advocate']['identifier'], 
                adv['advocate_description'].replace('For ', 'for ').strip(),
                adv['advocate']['last_name']
                )
            for adv in case_metadata["advocates"]}
all_advocates = set(advocates.keys())
# check that for each advocate, file "advocates/<advocate_identifier>.jpg" exists, else show warning
missing = False
for advocate_name, advocate in advocates.items():
    if not os.path.exists(f"advocates/{advocate[1]}.jpg"):
        missing = True
        print(f"Warning: Advocate {advocate[1]} has no image")
        # open browser to a google image search for advocate_name
        url = f"https://scotusstats.com/crop.html?filename={advocate[1]}.jpg&searchterm={advocate_name.replace(' ', '+')}&searchurl=https://www.google.com/search?q={advocate_name.replace(' ', '+')}%26tbm=isch"
        print(f"Go to {url}\n")
        os.system(f'open "{url}"')


if missing:
    raise Exception("Missing advocates")

json_object = {"sections" : {}}

# Get MP3
mp3_url = oral_argument_transcript["media_file"][0]["href"]
mp3_filename = f"mp3/{case_number}.mp3"
if not os.path.exists(mp3_filename):
    mp3 = requests.get(mp3_url)
    with open(mp3_filename, "wb") as file:
        file.write(mp3.content)
# get length of mp3 in seconds
mp3_length = mp3_duration(mp3_filename)
json_object["mp3_length"] = mp3_length

# Extract list of presiding justices
justices = {member["name"] : member for member in case_metadata["heard_by"][0]["members"]}

# Extract transcript sections
sections = oral_argument_transcript["transcript"]["sections"]

chapters = []

part_number = 0
for section_counter, section in enumerate(sections):
    turns = section["turns"]

    section_obj = {}
    json_object["sections"][section_counter] = section_obj
    section_obj["sectionStartTime"] = section["start"]
    
    # Determine the headline (name of the first advocate or speaker if no advocate took a turn)
    for turn in turns:
        speaker_name = turn["speaker"]["name"]
        if speaker_name in all_advocates:
            section_obj["advocateName"] = advocates[speaker_name][0]
            section_obj["advocateIdentifier"] = advocates[speaker_name][1]
            section_obj["advocateDescription"] = advocates[speaker_name][2]
            section_obj["advocateLastName"] = advocates[speaker_name][3]
            break
    else:
        raise Exception(f"No advocate found in section {section_counter}")

    if section_counter == len(sections) - 1 and speaker_name == chapters[0]["title"]:
        chapters.append({"title": "Rebuttal: " + speaker_name, "start": turns[0]["start"]})
    elif section_counter:
        chapters.append({"title": speaker_name, "start": turns[0]["start"]})
    else:
        chapters.append({"title": speaker_name, "start": 0}) # youtube requires first chapter to start at 0

    interactions = []
    section_obj["interactions"] = interactions

    # List of justices who took turns
    prev_justice = None
    for i, turn in enumerate(turns):
        current_speaker = turn["speaker"]["name"]

        if current_speaker == "John G. Roberts, Jr." and i == 0:
            continue

        text_blocks = turn["text_blocks"]
        if len(text_blocks) == 1:
            if len(text_blocks[0]["text"].split()) <= 8:
                continue
            if current_speaker == "John G. Roberts, Jr." and len(text_blocks[0]["text"].split()) <= 15 and i == len(turns) - 1:
                continue

        if sum([len(block["text"].split()) for block in text_blocks]) <= 8:
            continue

        if turn["stop"] - turn["start"] < 1.0:
            continue

        if i == len(turns) - 1:
            if current_speaker == "John G. Roberts, Jr.":
                continue
        
        # Check if the current turn is Chief Justice and the next turn is also a justice
        is_moderation = current_speaker == "John G. Roberts, Jr."
        is_moderation = is_moderation and i < len(turns) - 1 and turns[i+1]["speaker"]["name"] in justices
        if is_moderation:
            continue

        # Avoid consecutive repetitions and consider skip_next flag
        if current_speaker in justices and current_speaker != prev_justice:
            if interactions:
                interactions[-1]["endTime"] = turn["start"]
            interactions.append({
                "justice": justices[current_speaker]["identifier"], 
                "justiceLastName": justices[current_speaker]["last_name"],
                "start": i,
                "startTime": turn["start"],
                })
            prev_justice = current_speaker
    
    if interactions:
        interactions[-1]["endTime"] = section["stop"]

# Get opinion announcements
if not "opinion_announcement" in case_metadata:
    case_metadata["opinion_announcement"] = []
if case_metadata["opinion_announcement"] is None:
    case_metadata["opinion_announcement"] = []
announcements = sorted(case_metadata["opinion_announcement"], key=lambda x: (x["title"], x["id"]))
start = json_object["mp3_length"] + 6 # 8 seconds of silence between oral argument and opinion announcement; but begin the first chapter 2 seconds earlier
json_object["announcements"] = []
for i, announcement in enumerate(announcements):
    json_url = announcement["href"]
    json_filename = f"json/{case_number}-opinion-{i}.json"
    mp3_url = None
    if not os.path.exists(json_filename):
        json_content = requests.get(json_url).json()
        assert len(json_content["transcript"]["sections"]) == 1
        json.dump(json_content, open(json_filename, "w"), indent=4)
        mp3_url = json_content["media_file"][0]["href"]
    # COMMENTED OUT FOR ADVOCATE RETRIEVAL
    # mp3_filename = f"mp3/{case_number}-opinion-{i}.mp3"
    # if not os.path.exists(mp3_filename):
    #     mp3 = requests.get(mp3_url)
    #     with open(mp3_filename, "wb") as file:
    #         file.write(mp3.content)
    # get length of mp3 in seconds
    mp3_length = mp3_duration(mp3_filename)
    json_object["announcements"].append({"title": announcement["title"], "json": json_filename, "mp3": mp3_filename, "mp3_length": mp3_length})
    if len(announcements) > 1:
        chapters.append({"title": f"Opinion Announcement {i+1}", "start": start})
    else:
        chapters.append({"title": "Opinion Announcement", "start": start})
    if i == 0:
        start += 2 # 2 seconds of silence included in the first announcement
    start += mp3_length
    
# make podcast rss item
for date in case_metadata["timeline"]:
    if date["event"] == "Argued":
        argued_time = date["dates"][0] 
        break

# argued_date is unix timestamp
# Format: Jan 1, 2023
argued_date = datetime.datetime.fromtimestamp(argued_time).strftime("%b %-d, %Y")

is_decided = False
for date in case_metadata["timeline"]:
    if date["event"] == "Decided":
        decided_time = date["dates"][0] 
        decided_date = datetime.datetime.fromtimestamp(decided_time).strftime("%b %-d, %Y")
        is_decided = True
        break

json_object["dates"] = f"Argued on {argued_date}." + (f"\nDecided on {decided_date}." if is_decided else "")

wikipedia_url = f"https://en.wikipedia.org/wiki/{case_metadata['name'].replace(' ', '_')}"
if requests.get(wikipedia_url).status_code == 200:
    wikipedia_text = "Wikipedia: " + wikipedia_url + "\n"
else:
    wikipedia_text = ""

docket_text = ""
try:
    if int(case_metadata["term"]) >= 2001:
        docket_text = f"Docket: https://www.supremecourt.gov/docket/docketfiles/html/public/{docket_number}.html\n"
except ValueError:
    pass

parties_text = f"*{case_metadata['first_party_label']}:* {case_metadata['first_party']}\n"
if case_metadata["second_party"]:
    parties_text += f"*{case_metadata['second_party_label']}:* {case_metadata['second_party']}"

def de_html(text):
    if text is None:
        return ""
    text = text.replace("</p>", "\n")
    text = text.replace("<br>", "\n")
    text = re.sub("</.*?>", " ", text)
    text = re.sub("<.*?>", "", text)
    return text.strip()

def seconds_to_time(seconds):
    # e.g. 1:12:34 with no milliseconds
    return str(datetime.timedelta(seconds=seconds)).split(".")[0]

advocates_list = '\n'.join([f"- {advocates[advocate][0]} ({advocates[advocate][2]})" for advocate in advocates])
conclusion_text = ""
if is_decided:
    conclusion_text = f"""
*Conclusion*
{de_html(case_metadata['conclusion'])}"""
facts = ""
if case_metadata['facts_of_the_case']:
    facts = f"""
*Facts of the case (from oyez.org)*
{de_html(case_metadata['facts_of_the_case'])}
"""

chapters_text = '\n'.join(
    [f"{seconds_to_time(chapter['start'])} {chapter['title']}" for chapter in chapters]
)

announcement_text = ""
youtube_title = f"Oral Argument: {case_metadata['name']}"
if len(announcements) == 1:
    announcement_text = f" Also includes audio of the opinion announcement on {decided_date}."
    youtube_title = f"Oral Argument + Opinion: {case_metadata['name']}"
elif len(announcements) > 1:
    announcement_text = f" Also includes audio of the opinion announcements on {decided_date}."
    youtube_title = f"Oral Argument + Opinion: {case_metadata['name']}"

youtube_description = f"""Oral argument audio (including transcript) of case 
[{docket_number}] *{case_metadata['name']}*
argued at the Supreme Court of the United States on {argued_date}.{announcement_text}

*More information about the case:*
{wikipedia_text}Justia: {case_metadata['justia_url']}
{docket_text}Oyez.org: {case_metadata['href'].replace('api.','www.')}

Video produced based on information and transcripts on oyez.org, licensed under a CC-BY-NC License (https://creativecommons.org/licenses/by-nc/4.0/).
Not affiliated with oyez.org or the Supreme Court.

{json_object['dates']}
{parties_text}
*Advocates:* 
{advocates_list}

*Chapters*
{chapters_text}
{facts}
*Question*
{de_html(case_metadata['question']) if 'question' in case_metadata else ''}
{conclusion_text}"""

if len(youtube_description) > 5000:
    youtube_description = youtube_description[:4996] + "..."

json_object["youtube_title"] = youtube_title
json_object["youtube_description"] = youtube_description
json_object["term"] = case_metadata["term"]

# print(youtube_description)

with open(f"json/{case_number}-interactions.json", "w") as file:
    json.dump(json_object, file, indent=4)

print("Case number:")
print(case_number)

# write case_number to case_number.txt
with open("case_number.txt", "w") as file:
    file.write(str(case_number))