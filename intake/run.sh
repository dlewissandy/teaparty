#!/bin/bash
# Research intake pipeline — cron entry point.
#
# Runs the full pipeline:
#   1. Python pre-fetch (all network I/O, no permissions needed)
#   2. Claude Code analysis (read/write only, no Bash/WebFetch/osascript)
#   3. Python notification (osascript, no permissions needed)
#
# Usage:
#   ./intake/run.sh           # full pipeline
#   ./intake/run.sh --fetch   # fetch only (skip analysis)
#
# Cron example (daily at 6am):
#   0 6 * * * cd /Users/darrell/git/teaparty && ./intake/run.sh >> intake/run.log 2>&1

set -euo pipefail
cd "$(dirname "$0")/.."

DATE=$(date +%Y-%m-%d)
echo "=== Research Intake — $DATE ==="
echo ""

# ── Step 1: Pre-fetch all sources ──────────────────────────────────────────
echo "Step 1: Fetching sources..."
uv run python -m intake.fetch

MANIFEST="intake/raw/$DATE/manifest.json"
if [ ! -f "$MANIFEST" ]; then
    echo "ERROR: No manifest file at $MANIFEST"
    exit 1
fi

ITEM_COUNT=$(python3 -c "import json; print(len(json.load(open('$MANIFEST'))['items']))")
echo "Fetched $ITEM_COUNT items"
echo ""

if [ "$ITEM_COUNT" -eq 0 ]; then
    echo "No new content. Sending notification and exiting."
    uv run python -m intake.notify --no-new
    exit 0
fi

if [ "${1:-}" = "--fetch" ]; then
    echo "Fetch-only mode. Stopping here."
    exit 0
fi

# ── Step 2: Claude Code analysis ───────────────────────────────────────────
# Claude reads the manifest and pre-fetched files, writes digest/analysis/ideas.
# No Bash, WebFetch, or osascript needed — only Read, Write, Glob, Grep.
echo "Step 2: Running Claude Code analysis..."
claude --print \
    --allowedTools "Read,Write,Glob,Grep,Agent" \
    --prompt "Run /intake-analyze for today's pre-fetched content. The manifest is at $MANIFEST. Read it, then read each fetched file, produce the digest, triage, and ideation. Write outputs to intake/digests/digest-$DATE.md, intake/analysis/analysis-$DATE.md, and intake/ideas/. After writing, update state by reading the manifest and marking all items as seen."

echo ""

# ── Step 3: Update state ──────────────────────────────────────────────────
echo "Step 3: Updating state..."
uv run python -c "
from intake.state import load_state, mark_seen, save_state
from datetime import date
import json

state = load_state()
manifest = json.load(open('$MANIFEST'))

for item in manifest['items']:
    if item.get('unreachable'):
        continue
    content_id = item.get('video_id', item['url'])
    mark_seen(state, item['source_url'], content_id,
              date=item.get('published', ''),
              content_hash=item.get('content_hash', ''))

state['last_run'] = date.today().isoformat()
save_state(state)
print(f'State updated: {len(manifest[\"items\"])} items marked seen')
"
echo ""

# ── Step 4: Create GitHub issues ──────────────────────────────────────────
ANALYSIS="intake/analysis/analysis-$DATE.md"
if [ -f "$ANALYSIS" ]; then
    echo "Step 4: Creating GitHub issues..."
    uv run python -m intake.create_issues "$ANALYSIS"
else
    echo "Step 4: No analysis file — skipping issue creation."
fi
echo ""

# ── Step 5: Notify ─────────────────────────────────────────────────────────
if [ -f "$ANALYSIS" ]; then
    echo "Step 5: Sending notification..."
    uv run python -m intake.notify "$ANALYSIS"
else
    echo "Step 5: No analysis file found, sending no-new notification..."
    uv run python -m intake.notify --no-new
fi

echo ""
echo "=== Pipeline complete ==="
