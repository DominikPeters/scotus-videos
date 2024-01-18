python -m http.server 8002 &
node screenshot.js && python build-video.py && python upload-video.py