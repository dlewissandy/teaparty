#!/usr/bin/env bash
# Hierarchical Agent Teams POC — Entry Point
#
# Two-phase execution with hierarchical plan approval:
#   Phase 1: Project-lead gathers plans from all subteams
#   Gate:    User reviews and approves the consolidated plan
#   Phase 2: Project-lead dispatches execution to all subteams
#
# Usage: ./poc/run.sh "Create a document about the solar system with diagrams"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASK="${1:?Usage: run.sh '<task description>'}"

export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1

# Create output directories for subteams
mkdir -p "$SCRIPT_DIR/output/art"
mkdir -p "$SCRIPT_DIR/output/writing"
mkdir -p "$SCRIPT_DIR/output/editorial"

# Substitute __POC_DIR__ with absolute path in agent definitions
AGENTS_JSON=$(sed "s|__POC_DIR__|$SCRIPT_DIR|g" \
  "$SCRIPT_DIR/agents/project-team.json")

echo "=== Hierarchical Agent Teams POC ==="
echo "Task: $TASK"
echo "Output: $SCRIPT_DIR/output/"
echo ""

# Temp files for stream capture
OUTFILE_P1=$(mktemp)
OUTFILE_P2=$(mktemp)

# Self-contained settings: pre-approve relay.sh via a temp settings file
SETTINGS_FILE=$(mktemp)

# Write stream file path so status.sh can find it
STREAM_POINTER="$SCRIPT_DIR/output/.stream-file"
trap "rm -f $OUTFILE_P1 $OUTFILE_P2 $SETTINGS_FILE $STREAM_POINTER" EXIT

# Build the settings JSON with python to avoid all shell quoting issues
SCRIPT_DIR="$SCRIPT_DIR" python3 -c "
import json, os, sys
d = os.environ['SCRIPT_DIR']
# Use colon syntax: Bash(command:*) — matches the documented pattern
rule = 'Bash(' + d + '/relay.sh:*)'
json.dump({'permissions': {'allow': [rule]}}, sys.stdout)
" > "$SETTINGS_FILE"

PLAN_FILE="$SCRIPT_DIR/output/plan.md"

# ═══════════════════════════════════════════
# PHASE 1: PLANNING
# ═══════════════════════════════════════════
echo "╔══════════════════════════════════════╗"
echo "║       PHASE 1: PLANNING             ║"
echo "╚══════════════════════════════════════╝"
echo ""

echo "$OUTFILE_P1" > "$STREAM_POINTER"

PLAN_PROMPT="PLANNING PHASE. Gather plans from each team. Do not execute yet.

$TASK"

echo "$PLAN_PROMPT" | claude -p \
  --output-format stream-json \
  --verbose \
  --max-turns 20 \
  --permission-mode acceptEdits \
  --settings "$SETTINGS_FILE" \
  --agents "$AGENTS_JSON" \
  --agent project-lead \
  | tee "$OUTFILE_P1" \
  | python3 -u "$SCRIPT_DIR/stream_filter.py"

echo ""

# If project-lead didn't write plan.md, extract from stream output
if [[ ! -f "$PLAN_FILE" ]]; then
  echo "[run.sh] project-lead didn't write plan.md, extracting from result..."
  python3 "$SCRIPT_DIR/extract_result.py" < "$OUTFILE_P1" > "$PLAN_FILE"
fi

# ═══════════════════════════════════════════
# APPROVAL GATE
# ═══════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════╗"
echo "║       PROJECT PLAN                   ║"
echo "╚══════════════════════════════════════╝"
echo ""
cat "$PLAN_FILE"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Interactive approval — read from terminal (not stdin pipe)
read -p "Approve plan? [y/n/e(dit)] " approval </dev/tty

case "$approval" in
  n|N)
    echo "Plan rejected. Aborting."
    exit 0
    ;;
  e|E)
    ${EDITOR:-vim} "$PLAN_FILE"
    echo "Plan edited. Proceeding with modified plan."
    ;;
  *)
    echo "Plan approved. Proceeding to execution."
    ;;
esac

echo ""

# ═══════════════════════════════════════════
# PHASE 2: EXECUTION
# ═══════════════════════════════════════════
echo "╔══════════════════════════════════════╗"
echo "║       PHASE 2: EXECUTION            ║"
echo "╚══════════════════════════════════════╝"
echo ""

echo "$OUTFILE_P2" > "$STREAM_POINTER"

# Read the (possibly edited) plan
APPROVED_PLAN=$(cat "$PLAN_FILE")

EXEC_PROMPT="EXECUTION PHASE. Execute this approved plan.

$APPROVED_PLAN"

echo "$EXEC_PROMPT" | claude -p \
  --output-format stream-json \
  --verbose \
  --max-turns 30 \
  --permission-mode acceptEdits \
  --settings "$SETTINGS_FILE" \
  --agents "$AGENTS_JSON" \
  --agent project-lead \
  | tee "$OUTFILE_P2" \
  | python3 -u "$SCRIPT_DIR/stream_filter.py"

echo ""
echo "=== Output files ==="
find "$SCRIPT_DIR/output" -type f -not -name '.*' 2>/dev/null | sort
