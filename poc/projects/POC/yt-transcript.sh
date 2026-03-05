#!/usr/bin/env bash
# Extract YouTube transcript as plain text.
# Usage: yt-transcript.sh "<youtube-url>"
#
# Auto-installs youtube-transcript-api via pip on first run if not present.
set -euo pipefail

URL="${1:?Usage: yt-transcript.sh '<youtube-url>'}"

# Auto-install youtube-transcript-api if needed
if ! python3 -c "import youtube_transcript_api" 2>/dev/null; then
  echo "[yt-transcript] Installing youtube-transcript-api via pip..." >&2
  pip3 install --quiet youtube-transcript-api >&2
fi

# Extract video ID from URL (handles various YouTube URL formats)
python3 -c "
import sys
import re
import json
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

url = sys.argv[1]

# Extract video ID from various YouTube URL formats
video_id = None
patterns = [
    r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([^&\?\/]+)',
    r'youtube\.com\/.*[?&]v=([^&]+)',
]

for pattern in patterns:
    match = re.search(pattern, url)
    if match:
        video_id = match.group(1)
        break

if not video_id:
    print(json.dumps({'error': 'Could not extract video ID from URL'}))
    sys.exit(1)

try:
    # Get the transcript (tries auto-generated if manual not available)
    transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

    # Try to get English transcript first
    try:
        transcript = transcript_list.find_transcript(['en'])
    except NoTranscriptFound:
        # Fall back to any available transcript
        transcript = transcript_list.find_generated_transcript(['en'])

    # Fetch and format the transcript
    transcript_data = transcript.fetch()

    # Extract just the text, remove duplicates, and format
    seen = set()
    text_parts = []
    for entry in transcript_data:
        text = entry['text'].strip()
        # Remove HTML tags and clean up
        text = re.sub(r'<[^>]+>', '', text)
        # Skip duplicates (common in auto-generated captions)
        if text and text not in seen:
            seen.add(text)
            text_parts.append(text)

    # Join and format to 80 chars width
    full_text = ' '.join(text_parts)

    # Simple word-wrap at 80 chars
    words = full_text.split()
    lines = []
    current_line = []
    current_length = 0

    for word in words:
        word_len = len(word)
        if current_length + word_len + len(current_line) > 80:
            if current_line:
                lines.append(' '.join(current_line))
                current_line = [word]
                current_length = word_len
        else:
            current_line.append(word)
            current_length += word_len

    if current_line:
        lines.append(' '.join(current_line))

    print('\n'.join(lines))

except TranscriptsDisabled:
    print(json.dumps({'error': 'Transcripts are disabled for this video'}))
    sys.exit(1)
except NoTranscriptFound:
    print(json.dumps({'error': 'No transcript available for this video'}))
    sys.exit(1)
except VideoUnavailable:
    print(json.dumps({'error': 'Video is unavailable'}))
    sys.exit(1)
except Exception as e:
    print(json.dumps({'error': f'Failed to fetch transcript: {str(e)}'}))
    sys.exit(1)
" "$URL"
