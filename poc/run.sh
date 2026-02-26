#!/usr/bin/env bash
# Hierarchical Agent Teams POC — Entry Point
#
# Usage: ./poc/run.sh "Create a document about the solar system with diagrams"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASK="${1:?Usage: run.sh '<task description>'}"

export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
export CLAUDE_CODE_MAX_OUTPUT_TOKENS="${CLAUDE_CODE_MAX_OUTPUT_TOKENS:-128000}"

# Session isolation: each run gets a timestamped directory
SESSION_TS=$(date +%Y%m%d-%H%M%S)
export POC_OUTPUT_DIR="$SCRIPT_DIR/output"
export POC_SESSION_DIR="$SCRIPT_DIR/output/$SESSION_TS"

# Create session directories for subteams
mkdir -p "$POC_SESSION_DIR/art"
mkdir -p "$POC_SESSION_DIR/writing"
mkdir -p "$POC_SESSION_DIR/editorial"
mkdir -p "$POC_SESSION_DIR/research"

# Cross-session memory — persists across runs, only appended/curated by uber lead
touch "$POC_OUTPUT_DIR/MEMORY.md"

# Shared conversation log — scoped to this session.
# Subteam output is indented via --filter-prefix in relay.sh.
export CONVERSATION_LOG="$POC_SESSION_DIR/.conversation"
> "$CONVERSATION_LOG"

# Tail the conversation log in the background so it streams to the terminal
tail -f "$CONVERSATION_LOG" &
TAIL_PID=$!

# Substitute placeholders with absolute paths in agent definitions
AGENTS_JSON=$(sed -e "s|__POC_DIR__|$SCRIPT_DIR|g" \
                  -e "s|__SESSION_DIR__|$POC_SESSION_DIR|g" \
  "$SCRIPT_DIR/agents/uber-team.json")

# Self-contained settings: pre-approve relay.sh
SETTINGS_FILE=$(mktemp)
trap "kill $TAIL_PID 2>/dev/null; rm -f $SETTINGS_FILE" EXIT

SCRIPT_DIR="$SCRIPT_DIR" python3 -c "
import json, os, sys
d = os.environ['SCRIPT_DIR']
rules = [
    'Bash(' + d + '/relay.sh:*)',
    'Bash(' + d + '/yt-transcript.sh:*)',
    'WebFetch',
    'WebSearch',
]
json.dump({'permissions': {'allow': rules}, 'env': {
    'SCRIPT_DIR': d,
    'POC_OUTPUT_DIR': os.environ.get('POC_OUTPUT_DIR', ''),
    'POC_SESSION_DIR': os.environ.get('POC_SESSION_DIR', ''),
}}, sys.stdout)
" > "$SETTINGS_FILE"

echo "=== Hierarchical Agent Teams POC ==="
echo "Task: $TASK"
echo "Session: $SESSION_TS"
echo "Output: $POC_SESSION_DIR/"
echo ""

# Plan → Approve → Execute (same script used by relay.sh for subteams)
"$SCRIPT_DIR/plan-execute.sh" \
  --agents "$AGENTS_JSON" \
  --agent project-lead \
  --settings "$SETTINGS_FILE" \
  --cwd "$POC_SESSION_DIR" \
  --plan-turns 15 \
  --exec-turns 30 \
  "$TASK"

# Stop the tail
kill "$TAIL_PID" 2>/dev/null || true
wait "$TAIL_PID" 2>/dev/null || true

echo ""
echo "=== Session: $SESSION_TS ==="
echo "Session dir: $POC_SESSION_DIR/"
echo "Cross-session memory: $POC_OUTPUT_DIR/MEMORY.md"
find "$POC_SESSION_DIR" -type f -not -name '.*' 2>/dev/null | sort
