#!/bin/bash
# Run gentle forced aligner on a case
# Usage: ./run-gentle.sh <case-number>
# Example: ./run-gentle.sh 25-332

set -e

CASE="$1"
if [ -z "$CASE" ]; then
    echo "Usage: $0 <case-number>"
    exit 1
fi

AUDIO="$CASE/$CASE.mp3"
TRANSCRIPT="$CASE/$CASE.flat.txt"
OUTPUT="$CASE/$CASE.timed.json"

# Check input files exist
if [ ! -f "$AUDIO" ]; then
    echo "Error: Audio file not found: $AUDIO"
    exit 1
fi

if [ ! -f "$TRANSCRIPT" ]; then
    echo "Error: Transcript file not found: $TRANSCRIPT"
    exit 1
fi

# Check if gentle server is running
if ! curl -s -o /dev/null http://localhost:8765/ 2>/dev/null; then
    echo "Gentle server not running. Starting gentle.app..."
    open -a "gentle"

    # Wait for server to be ready
    echo "Waiting for gentle server to start..."
    for i in {1..30}; do
        if curl -s -o /dev/null http://localhost:8765/ 2>/dev/null; then
            echo "Gentle server is ready."
            break
        fi
        sleep 1
    done

    if ! curl -s -o /dev/null http://localhost:8765/ 2>/dev/null; then
        echo "Error: Gentle server failed to start after 30 seconds"
        exit 1
    fi
fi

echo "Running alignment on $CASE..."
echo "  Audio: $AUDIO"
echo "  Transcript: $TRANSCRIPT"
echo "  Output: $OUTPUT"

curl -F "audio=@$AUDIO" \
     -F "transcript=@$TRANSCRIPT" \
     "http://localhost:8765/transcriptions?async=false" \
     -o "$OUTPUT" \
     --progress-bar

echo ""
echo "Alignment complete. Output saved to: $OUTPUT"

# Show summary
WORD_COUNT=$(python3 -c "import json; print(len(json.load(open('$OUTPUT')).get('words', [])))")
echo "Words aligned: $WORD_COUNT"
