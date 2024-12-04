lsof -t -i tcp:8002 | xargs kill
python -m http.server 8002 &
node screenshot.js && python build-video.py && python upload-video.py