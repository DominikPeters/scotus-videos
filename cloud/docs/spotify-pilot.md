# Spotify video upload trial

The existing show is externally hosted. The Anchor endpoints documented at
https://github.com/higuchiki/spotify-for-creators-api return 404 for its show and
episode IDs. Spotify's nonhosted upload page uses a separate API:

- `GET https://generic.wg.spotify.com/podcasters/v0/episodes/{spotify_id}/metadata`
- `POST .../episodes/{spotify_id}/generateUploadId`, with `episodeId`, `showId`,
  and `episodeUri` (`spotify:episode:...`).
- `POST https://media-importer.spotify.com/v1/uploadfile/{upload_id}`, multipart
  field `file`, with a Spotify bearer token. A resumed request adds an `offset`
  header and sends the remaining bytes.
- `GET https://media-importer.spotify.com/v1/uploadstatus/{upload_id}`.
- `POST .../episodes/{spotify_id}/publish`, with `uploadId`, `isExplicit`, and
  `isEighteenPlus`. The trial intentionally does not call this endpoint.

These endpoints were read from the current official upload page's JavaScript
on October 13, 2026; they are undocumented and may change. The trial preserves
episode identity, title, description, publication date, and RSS hosting.

`scotus_cloud/spotify_pilot.py` runs inside Google Cloud, reads a private
Secret Manager mount, downloads the saved MP4 there, and stream-copies video
while converting MP3 audio to AAC-LC stereo at 192 kbps. It uses a streaming
multipart request and saves bounded redacted responses as private JSON
artifacts. The job is limited to two CPUs, 2 GiB, 900 seconds, and zero retries.
It does not fetch media through the user's computer or publish automatically.

For an unchanged-file test, set `keep_original: true`, a safe `.mp4` filename,
and the saved assembly `source_sha256`. The worker verifies the downloaded
file against that checksum, requires an MP3 audio track, and uploads the exact
file without invoking ffmpeg or remuxing it. Anderson (25-498) passed the
transfer step with its original 4K H.264 video and mono 64 kbps MP3 audio:
301,291,574 bytes, HTTP 200, no failure reason, 47 seconds to upload.
After owner approval, Spotify completed processing and published this unchanged
MP3-audio file: `hasVideo: true`, episode and upload statuses `PUBLISHED`, and
no failure reason. AAC conversion was not necessary for this recording.

An upload response containing `previewUrl` indicates transfer completion;
it does not establish successful final transcoding or publication. Keep the
upload ID for the separate review/publish step instead of uploading again.

The Beaird trial returned HTTP 200, `UPLOADED`, and no failure reason. The
video stream was unchanged; AAC conversion took 149 seconds and the 548 MB
upload took 82 seconds. After owner approval, publication completed successfully:
both APIs returned `PUBLISHED`, `hasVideo` was true, and no failure reason was
reported. Episode ID `2nNYiQndhVraDLW9szuB1a` remained unchanged.
The initial one-CPU conversion attempt hit a 240-second timeout before creating
any Spotify upload; the revised trial used the fast AAC coder and two CPUs.

## Production manual transfer

The dashboard's “Upload and publish on Spotify” action authorizes both steps.
The cloud worker streams the original saved MP4, attempts to reuse the saved
YouTube JPEG thumbnail, then requests publication of the same RSS episode.
Automatic transfers remain disabled. Saved upload IDs survive retries; a
completed upload is reconciled and published without retransmitting the video.
Legacy uploads without publication authorization still require an owner action.

Thumbnail operations use the official nonhosted application's persisted GraphQL
operations at `https://creators-graph.spotify.com/v2/graph-pq`: reserve a signed
URL, PUT the JPEG without account authorization headers, then complete the
upload. These operations were inspected on October 15, 2026. A thumbnail error
is recorded privately in the dashboard and does not block video publication.
Spotify's subsequent processing may take time even after publication is requested.

The production thumbnail path was tested successfully against Beaird’s existing
episode, using its 134,353-byte saved JPEG. The Cloud Run thumbnail-only trial
completed without transferring or publishing another video.
