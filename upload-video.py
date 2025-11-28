import json

import os
import time

# from b2sdk.v2 import *

from PIL import Image

import googleapiclient.discovery
import google.oauth2.credentials
from googleapiclient.http import MediaFileUpload

from add_timestamp_comment import add_timestamp_comment

def main():
    # get case number from case_number.txt
    case_number = open("case_number.txt", "r").read().strip()

    # Disable OAuthlib's HTTPS verification when running locally.
    # *DO NOT* leave this option enabled in production.
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    api_service_name = "youtube"
    api_version = "v3"
    DEVELOPER_KEY = os.environ["YT_DEV_KEY"]

    with open(f"json/{case_number}-interactions.json", "r") as file:
        interactions = json.load(file)

    img = Image.open(f"thumbnails/{case_number}.png")
    resized = img.resize((1280, 720)) 
    resized = resized.convert('RGB')
    resized.save(f'thumbnails/{case_number}.jpg', optimize=True, quality=90)
    # check if size exceeds 2097152 bytes, if so, compress more
    if os.path.getsize(f"thumbnails/{case_number}.jpg") > 2097152:
        resized.save(f'thumbnails/{case_number}.jpg', optimize=True, quality=80)
    if os.path.getsize(f"thumbnails/{case_number}.jpg") > 2097152:
        resized.save(f'thumbnails/{case_number}.jpg', optimize=True, quality=60)
    if os.path.getsize(f"thumbnails/{case_number}.jpg") > 2097152:
        raise Exception("Thumbnail too large")

    with open("credentials.json", "r") as file:
        credentials_json = file.read()
    credentials = google.oauth2.credentials.Credentials.from_authorized_user_info(json.loads(credentials_json))

    try:
        youtube = googleapiclient.discovery.build(
            api_service_name, api_version, credentials=credentials, developerKey = DEVELOPER_KEY)

        print("Uploading video...")
        request = youtube.videos().insert(
            part="snippet,status",
            body={
            "snippet": {
                "categoryId": "25", # News & Politics
                "description": interactions["youtube_description"],
                "title": interactions["youtube_title"]
            },
            "status": {
                "privacyStatus": "unlisted", # unlisted allows adding comments
                "selfDeclaredMadeForKids": False
            }
            },
            media_body=MediaFileUpload(f"videos/{case_number}.mp4", chunksize=-1, resumable=True)
        )
        response = request.execute()
        video_id = response["id"]
        print(json.dumps(response, indent=4))


        if response and "id" in response:
            print("")
            print(f"Video id {response['id']} was successfully uploaded.")
            time.sleep(1)
            print("")
            print("Uploading thumbnail...")
            request = youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(f"thumbnails/{case_number}.jpg")
            )
            response = request.execute()
            print(json.dumps(response, indent=4))
            playlists = json.load(open("playlist_ids.json", "r"))
            if interactions["term"] not in playlists:
                print(f"WARNING: No playlist found for term {interactions['term']}, skipping adding to playlist")
            else:
                playlist_id = playlists[interactions["term"]]
                request = youtube.playlistItems().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "playlistId": playlist_id,
                            "resourceId": {
                                "kind": "youtube#video",
                                "videoId": video_id
                            }
                        }
                    }
                )
                response = request.execute()
                print(f"Added video to playlist OT {playlist_id} ({interactions['term']})")
            add_timestamp_comment(youtube, video_id, interactions)
            print("")
            with open("comment.txt", "w") as file:
                file.write("Uploaded to YouTube\n\n")
                file.write(f"https://www.youtube.com/watch?v={video_id}")
    except Exception as e:
        print(e)
        print("Possible authentication error, uploading to B2")
        info = InMemoryAccountInfo()
        b2_api = B2Api(info)
        application_key = os.environ["B2_APP_KEY"]
        application_key_id = os.environ["B2_APP_KEY_ID"]
        b2_api.authorize_account("production", application_key_id, application_key)
        bucket = b2_api.get_bucket_by_name("scotus-videos")
        bucket.upload_local_file(local_file=f"videos/{case_number}.mp4", file_name=f"{case_number}.mp4")
        bucket.upload_local_file(local_file=f"thumbnails/{case_number}.jpg", file_name=f"{case_number}.jpg")
        bucket.upload_local_file(local_file=f"json/{case_number}-interactions.json", file_name=f"{case_number}-interactions.json")
        with open("comment.txt", "w") as file:
            file.write("Uploaded to B2 because upload to YouTube failed\n\n")
            file.write(f"https://scotus-videos.s3.us-west-002.backblazeb2.com/{case_number}.mp4")
            file.write(f"https://scotus-videos.s3.us-west-002.backblazeb2.com/{case_number}.jpg")
            file.write(f"https://scotus-videos.s3.us-west-002.backblazeb2.com/{case_number}-interactions.json")



if __name__ == "__main__":
    main()