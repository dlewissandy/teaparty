#!/usr/bin/env bash
# Extract YouTube transcript as plain text.
# Usage: yt-transcript.sh "<youtube-url>"
#
# Auto-installs yt-dlp via Homebrew on first run if not present.
set -euo pipefail

URL="${1:?Usage: yt-transcript.sh '<youtube-url>'}"

# Auto-install yt-dlp if needed
if ! command -v yt-dlp &>/dev/null; then
  echo "[yt-transcript] Installing yt-dlp via Homebrew..." >&2
  brew install yt-dlp >&2
fi

TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

# Try to get auto-generated or manual English subtitles
yt-dlp \
  --skip-download \
  --write-auto-sub \
  --write-sub \
  --sub-lang en \
  --sub-format vtt \
  --convert-subs srt \
  -o "$TMPDIR/%(id)s.%(ext)s" \
  "$URL" >&2 2>&1 || true

# Find the subtitle file
SUB_FILE=$(find "$TMPDIR" -name "*.srt" -o -name "*.vtt" | head -1)

if [[ -z "$SUB_FILE" ]]; then
  echo '{"error": "No transcript available for this video"}'
  exit 1
fi

# Strip SRT formatting (timestamps, sequence numbers) to get plain text
# Remove: sequence numbers (bare digits), timestamps (00:00:00,000 --> ...), blank lines, HTML tags
# Deduplicate consecutive identical lines (common in auto-generated subs)
sed -E '/^[0-9]+$/d; /^[0-9]{2}:[0-9]{2}/d; /^$/d; s/<[^>]*>//g' "$SUB_FILE" \
  | awk '!seen[$0]++' \
  | tr '\n' ' ' \
  | fold -s -w 80

echo ""
