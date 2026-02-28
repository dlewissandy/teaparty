#!/usr/bin/env bash
# Standalone research team entry point.
#
# Usage: ./poc/research.sh "Research quantum error correction techniques"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASK="${1:?Usage: research.sh '<research question>'}"

export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
export CLAUDE_CODE_MAX_OUTPUT_TOKENS="${CLAUDE_CODE_MAX_OUTPUT_TOKENS:-128000}"

OUTPUT_DIR="$SCRIPT_DIR/output/research"
mkdir -p "$OUTPUT_DIR"

# Shared conversation log
export CONVERSATION_LOG="$OUTPUT_DIR/.conversation"
> "$CONVERSATION_LOG"

# Tail the conversation log in the background
tail -f "$CONVERSATION_LOG" &
TAIL_PID=$!

# Substitute __POC_DIR__ with absolute path in agent definitions
AGENTS_JSON=$(sed "s|__POC_DIR__|$SCRIPT_DIR|g" \
  "$SCRIPT_DIR/agents/research-team.json")

# Pre-approve research tools: yt-transcript.sh and curl
SETTINGS_FILE=$(mktemp)
trap "kill $TAIL_PID 2>/dev/null; rm -f $SETTINGS_FILE" EXIT

SCRIPT_DIR="$SCRIPT_DIR" python3 -c "
import json, os, sys
d = os.environ['SCRIPT_DIR']
rules = [
    'Bash(' + d + '/yt-transcript.sh:*)',
    'Bash(curl:*)'
]
json.dump({'permissions': {'allow': rules}}, sys.stdout)
" > "$SETTINGS_FILE"

echo "=== Research Team ==="
echo "Task: $TASK"
echo "Output: $OUTPUT_DIR/"
echo ""

# Plan -> Approve -> Execute
"$SCRIPT_DIR/plan-execute.sh" \
  --agents "$AGENTS_JSON" \
  --agent research-lead \
  --settings "$SETTINGS_FILE" \
  --cwd "$OUTPUT_DIR" \
  --plan-turns 10 \
  --exec-turns 30 \
  "$TASK"

# Stop the tail
kill "$TAIL_PID" 2>/dev/null || true
wait "$TAIL_PID" 2>/dev/null || true

echo ""
echo "=== Research output ==="
find "$OUTPUT_DIR" -type f -not -name '.*' 2>/dev/null | sort
