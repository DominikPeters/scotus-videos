# scotus-videos

This repository contains the code used to produce the videos for https://www.youtube.com/@SCOTUSOralArgument, which feature the transcript of oral arguments at the U.S. Supreme Court, displayed using a chat-like interface.
The channel is managed by [Dominik Peters](https://dominik-peters.de) in France as a side project.
I do this because I enjoy listening to oral arguments, which feature both judges and advocates who are extremely well-prepared and are quick analytic thinkers, and I believe that these arguments should find a wider audience. You can contact me by email at mail@dominik-peters.de or you can leave feedback or suggestions as an issue on GitHub.

The videos are made by rendering the data using HTML/CSS, saving the frames to image files using puppeteer by screenshotting, and encoding the video using ffmpeg. The data is taken from the [Oyez](https://www.oyez.org/) project.

Usage:
Run
```bash
python preprocess.py https://www.oyez.org/cases/2023/22-915
```
to download the audio and transcript of a particular case.

Then run
```bash
./produce.sh
```
to build the video. Ensure that puppeteer is available. It will also attempt to upload to YouTube which will probably not work if you're not me.

Starting in the 2024 term, I've also been using the [gentle](https://github.com/lowerquality/gentle) forced aligner to align the audio to the transcript for some cases. This way I don't have to wait for the transcript to be available on Oyez. I do this for a few "hot-button" cases that I want to upload as soon as possible.