#!/usr/bin/env bash
# Hierarchical Agent Teams POC — Entry Point
#
# Usage: ./poc/run.sh "Create a document about the solar system with diagrams"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASK="${1:?Usage: run.sh '<task description>'}"

export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
export CLAUDE_CODE_MAX_OUTPUT_TOKENS="${CLAUDE_CODE_MAX_OUTPUT_TOKENS:-128000}"

# Create output directories for subteams
mkdir -p "$SCRIPT_DIR/output/art"
mkdir -p "$SCRIPT_DIR/output/writing"
mkdir -p "$SCRIPT_DIR/output/editorial"

# Shared conversation log — all levels (uber + subteams) append here.
# Subteam output is indented via --filter-prefix in relay.sh.
export CONVERSATION_LOG="$SCRIPT_DIR/output/.conversation"
> "$CONVERSATION_LOG"

# Tail the conversation log in the background so it streams to the terminal
tail -f "$CONVERSATION_LOG" &
TAIL_PID=$!

# Substitute __POC_DIR__ with absolute path in agent definitions
AGENTS_JSON=$(sed "s|__POC_DIR__|$SCRIPT_DIR|g" \
  "$SCRIPT_DIR/agents/uber-team.json")

# Self-contained settings: pre-approve relay.sh
SETTINGS_FILE=$(mktemp)
trap "kill $TAIL_PID 2>/dev/null; rm -f $SETTINGS_FILE" EXIT

SCRIPT_DIR="$SCRIPT_DIR" python3 -c "
import json, os, sys
d = os.environ['SCRIPT_DIR']
rule = 'Bash(' + d + '/relay.sh:*)'
json.dump({'permissions': {'allow': [rule]}}, sys.stdout)
" > "$SETTINGS_FILE"

echo "=== Hierarchical Agent Teams POC ==="
echo "Task: $TASK"
echo "Output: $SCRIPT_DIR/output/"
echo ""

# Plan → Approve → Execute (same script used by relay.sh for subteams)
"$SCRIPT_DIR/plan-execute.sh" \
  --agents "$AGENTS_JSON" \
  --agent project-lead \
  --settings "$SETTINGS_FILE" \
  --cwd "$SCRIPT_DIR/output" \
  --plan-turns 15 \
  --exec-turns 30 \
  "$TASK"

# Stop the tail
kill "$TAIL_PID" 2>/dev/null || true
wait "$TAIL_PID" 2>/dev/null || true

echo ""
echo "=== Output files ==="
find "$SCRIPT_DIR/output" -type f -not -name '.*' 2>/dev/null | sort
