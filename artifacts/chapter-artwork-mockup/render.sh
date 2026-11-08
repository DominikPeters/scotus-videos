#!/bin/sh
# Render each mockup frame to a 1200x1200 PNG (600 CSS px at 2x).
cd "$(dirname "$0")"
chrome="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
mkdir -p png
for f in opening opening-qp duet pan card-case card-split card-timeline card-statute card-compare; do
  "$chrome" --headless=new --hide-scrollbars --allow-file-access-from-files --force-device-scale-factor=2 \
    --window-size=600,600 --virtual-time-budget=2000 --screenshot="png/$f.png" "file://$PWD/mockup.html?f=$f" 2>/dev/null
done
