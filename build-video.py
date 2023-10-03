import os
import sys
import json

# get case number from case_number.txt
case_number = open("case_number.txt", "r").read().strip()

interactions = json.load(open(f"json/{case_number}-interactions.json", "r"))

argument_mp3 = f"mp3/{case_number}.mp3"

# get list of opinion mp3s
opinion_mp3s = [a["mp3"] for a in interactions["announcements"]]

# concat mp3s
os.system(f"ffmpeg -t 60 -i {argument_mp3} -i mp3/silence.mp3 " + " ".join([f"-i {mp3}" for mp3 in opinion_mp3s]) + f" -filter_complex \"[0:0][1:0]" + "".join([f"[{i+2}:0]" for i in range(len(opinion_mp3s))]) + f" concat=n={len(opinion_mp3s)+2}:v=0:a=1[out]\" -map \"[out]\" mp3/{case_number}-full.mp3")

# build video
# ffmpeg -f concat -i frame-durations.txt -i rucho.mp3 -c:v libx264 -pix_fmt yuv420p -c:a copy -vf fps=20 rucho.mp4
os.system(f"ffmpeg -t 60 -f concat -i frames/{case_number}/frame-durations.txt -i mp3/{case_number}-full.mp3 -c:v libx264 -pix_fmt yuv420p -c:a copy -vf fps=20 videos/{case_number}.mp4")

if os.path.exists(f"frames/{case_number}"):
    if os.path.exists(f"videos/{case_number}.mp4"):
        os.system(f"rm -rf frames/{case_number}")