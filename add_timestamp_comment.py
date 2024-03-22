import sys
import json
import os
import googleapiclient.discovery
import google.oauth2.credentials

def seconds_to_timestamp(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = int(seconds % 60)
    if hours >= 10:
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    elif hours >= 1:
        return f"{hours}:{minutes:02}:{seconds:02}"
    else:
        return f"{minutes:02}:{seconds:02}"

def add_timestamp_comment(youtube, video_id, interactions):
    print(f"Adding timestamp comment to video {video_id}...")

    comment_pieces = ["Detailed timestamps:"]
    for section_num in interactions["sections"]:
        section = interactions["sections"][section_num]
        comment_pieces.append(f"{seconds_to_timestamp(section['sectionStartTime'])} {section['advocateName']} ({section['advocateDescription']})")
        for interaction in section["interactions"]:
            comment_pieces.append(f"{seconds_to_timestamp(interaction['startTime'])} {section['advocateLastName']} - {interaction['justiceLastName']}")
    comment = "\n".join(comment_pieces)
    print(comment)

    request = youtube.commentThreads().insert(
        part="snippet",
        body={
          "snippet": {
            "videoId": video_id,
            "topLevelComment": {
              "snippet": {
                "textOriginal": comment
              }
            }
          }
        }
    )
    response = request.execute()

    print(response)

    print(f"Timestamp comment added to video {video_id}.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: add-timestamp-comment.py <case_number> <video_id>")
        sys.exit(1)
    
    case_number = sys.argv[1]
    video_id = sys.argv[2]

    interactions = json.load(open(f"json/{case_number}-interactions.json", "r"))

    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    api_service_name = "youtube"
    api_version = "v3"
    DEVELOPER_KEY = os.environ["YT_DEV_KEY"]
    with open("credentials.json", "r") as file:
        credentials_json = file.read()
    credentials = google.oauth2.credentials.Credentials.from_authorized_user_info(json.loads(credentials_json))

    try:
        youtube = googleapiclient.discovery.build(
            api_service_name, api_version, credentials=credentials, developerKey = DEVELOPER_KEY)
    except Exception as e:
        print("Error building YouTube API service")
        print(e)
        sys.exit(1)

    add_timestamp_comment(youtube, video_id, interactions)