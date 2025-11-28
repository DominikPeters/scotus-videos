import os
import sys
import json

# get case number from case_number.txt
case_number = open("case_number.txt", "r").read().strip()

is_vertical = "--vertical" in sys.argv

if is_vertical:
    print("Vertical mode enabled.")
    frames_dir = "frames-vertical"
    output_dir = "videos-vertical"
    concat_result = 0 # assume audio concatenation was successful
else:
    frames_dir = "frames"
    output_dir = "videos"
    interactions = json.load(open(f"json/{case_number}-interactions.json", "r"))

    # Handle single vs multiple arguments
    if "arguments" in interactions and len(interactions["arguments"]) > 1:
        # Multiple arguments: get all argument mp3s
        argument_mp3s = [a["mp3"] for a in interactions["arguments"]]
    else:
        # Single argument: use existing filename
        argument_mp3s = [f"mp3/{case_number}.mp3"]

    # get list of opinion mp3s
    opinion_mp3s = [a["mp3"] for a in interactions["announcements"]] if "announcements" in interactions else []

    # Build ffmpeg command for concatenation
    input_files = []
    filter_parts = []
    input_index = 0

    # Add argument mp3s with silence between them
    for i, arg_mp3 in enumerate(argument_mp3s):
        input_files.extend(["-i", arg_mp3])
        filter_parts.append(f"[{input_index}:0]")
        input_index += 1
        
        # Add silence between arguments (but not after the last one)
        if i < len(argument_mp3s) - 1:
            input_files.extend(["-i", "mp3/silence.mp3"])
            filter_parts.append(f"[{input_index}:0]")
            input_index += 1

    # Add opinion announcement silence and mp3s if they exist
    if opinion_mp3s:
        input_files.extend(["-i", "mp3/silence.mp3"])
        filter_parts.append(f"[{input_index}:0]")
        input_index += 1
        
        for mp3 in opinion_mp3s:
            input_files.extend(["-i", mp3])
            filter_parts.append(f"[{input_index}:0]")
            input_index += 1

    # Build the filter complex
    total_inputs = len(filter_parts)
    filter_complex = "".join(filter_parts) + f" concat=n={total_inputs}:v=0:a=1[out]"

    # Run ffmpeg concat command
    concat_result = os.system(f"ffmpeg -y {' '.join(input_files)} -filter_complex \"{filter_complex}\" -map \"[out]\" mp3/{case_number}-full.mp3")

# build video using the concatenated mp3
video_result = os.system(f"ffmpeg -y -f concat -safe 0 -i {frames_dir}/{case_number}/frame-durations.txt -i mp3/{case_number}-full.mp3 -c:v libx264 -pix_fmt yuv420p -c:a copy -vf fps=20 {output_dir}/{case_number}.mp4")

# Only delete frames if both ffmpeg commands succeeded (exit code 0)
# if concat_result == 0 and video_result == 0:
#     if os.path.exists(f"{frames_dir}/{case_number}"):
#         os.system(f"rm -rf {frames_dir}/{case_number}")