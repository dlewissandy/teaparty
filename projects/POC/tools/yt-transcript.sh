#!/usr/bin/env bash
# Extract YouTube transcript as plain text using yt-dlp.
# Usage: yt-transcript.sh "<youtube-url>"
#
# Uses --cookies-from-browser chrome to bypass YouTube bot detection.
# Falls back to unauthenticated attempt if Chrome cookies unavailable.
set -euo pipefail

URL="${1:?Usage: yt-transcript.sh '<youtube-url>'}"

# Auto-install yt-dlp if needed
if ! python3 -c "import yt_dlp" 2>/dev/null; then
  echo "[yt-transcript] Installing yt-dlp via pip..." >&2
  pip3 install --quiet yt-dlp >&2
fi

python3 -c "
import sys, re, os, tempfile, json, shutil
import yt_dlp

url = sys.argv[1]
tmpdir = tempfile.mkdtemp()

def extract_vtt_text(vtt_path):
    with open(vtt_path) as f:
        content = f.read()
    # Remove WEBVTT header line
    content = re.sub(r'^WEBVTT[^\n]*\n', '', content, flags=re.MULTILINE)
    # Remove NOTE blocks
    content = re.sub(r'NOTE\n.*?\n\n', '', content, flags=re.DOTALL)
    # Remove timestamp lines (e.g. 00:00:01.000 --> 00:00:04.000 align:start)
    content = re.sub(r'\d{1,2}:\d{2}[^\n]*-->[^\n]*\n', '', content)
    # Remove HTML/XML tags (auto-generated captions use <c> timing tags etc.)
    content = re.sub(r'<[^>]+>', '', content)
    # Collect non-empty lines
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    # Deduplicate adjacent identical lines (very common in auto-generated VTT)
    deduped = []
    for line in lines:
        if not deduped or line != deduped[-1]:
            deduped.append(line)
    # Join to one text block and word-wrap at 80 chars
    full_text = ' '.join(deduped)
    words = full_text.split()
    result_lines = []
    current = []
    length = 0
    for word in words:
        if length + len(word) + len(current) > 80 and current:
            result_lines.append(' '.join(current))
            current = [word]
            length = len(word)
        else:
            current.append(word)
            length += len(word)
    if current:
        result_lines.append(' '.join(current))
    return '\n'.join(result_lines)

def try_extract(opts_override):
    opts = {
        'writeautomaticsub': True,
        'writesubtitles': True,
        'subtitleslangs': ['en', 'en-US', 'en-orig'],
        'subtitlesformat': 'vtt',
        'skip_download': True,
        'outtmpl': os.path.join(tmpdir, '%(id)s'),
        'quiet': True,
        'no_warnings': True,
    }
    opts.update(opts_override)
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    for fname in os.listdir(tmpdir):
        if fname.endswith('.vtt'):
            return os.path.join(tmpdir, fname)
    return None

try:
    vtt_path = None

    # Primary: try with Chrome cookies to bypass bot detection.
    # Reads cookie store from disk — no running browser required.
    try:
        vtt_path = try_extract({'cookiesfrombrowser': ('chrome',)})
    except Exception:
        pass

    # Fallback: try without cookies (works for non-restricted videos)
    if not vtt_path:
        vtt_path = try_extract({})

    if not vtt_path:
        print(json.dumps({'error': 'No transcript available for this video'}))
        sys.exit(1)

    print(extract_vtt_text(vtt_path))

except yt_dlp.utils.DownloadError as e:
    msg = str(e)
    if 'Private video' in msg or 'not available' in msg.lower():
        print(json.dumps({'error': 'Video is unavailable'}))
    elif 'subtitles' in msg.lower() or 'caption' in msg.lower():
        print(json.dumps({'error': 'No transcript available for this video'}))
    else:
        print(json.dumps({'error': 'Failed to fetch transcript: ' + msg}))
    sys.exit(1)
except Exception as e:
    print(json.dumps({'error': 'Failed to fetch transcript: ' + str(e)}))
    sys.exit(1)
finally:
    shutil.rmtree(tmpdir, ignore_errors=True)
" "$URL"
