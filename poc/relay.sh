#!/usr/bin/env bash
# Relay a task to a subteam by spawning a plan→execute cycle.
# Called by liaison agents via Bash.
#
# Usage: relay.sh --team art --task "Create diagrams for..."
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1

TEAM=""
TASK=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --team) TEAM="$2"; shift 2 ;;
    --task) TASK="$2"; shift 2 ;;
    *)      echo "{\"error\":\"unknown arg: $1\"}" >&2; exit 1 ;;
  esac
done

[[ -z "$TEAM" ]] && { echo '{"error":"--team required"}'; exit 1; }
[[ -z "$TASK" ]] && { echo '{"error":"--task required"}'; exit 1; }

# Each dispatch gets its own timestamped directory to prevent clobbering
DISPATCH_TS=$(date +%Y%m%d-%H%M%S)

# Use session directory if set (from run.sh), fall back to flat output/ for standalone use
if [[ -n "${POC_SESSION_DIR:-}" ]]; then
  OUTPUT_DIR="$POC_SESSION_DIR/$TEAM/$DISPATCH_TS"
else
  OUTPUT_DIR="$SCRIPT_DIR/output/$TEAM/$DISPATCH_TS"
fi
mkdir -p "$OUTPUT_DIR"

# Sentinel: exists while this relay is running, removed on completion.
# Agents can poll for completion: when .running is gone and .result.json exists, done.
touch "$OUTPUT_DIR/.running"

# Read agent definitions and substitute placeholders with absolute paths
AGENTS_JSON=$(sed -e "s|__POC_DIR__|$SCRIPT_DIR|g" \
                  -e "s|__SESSION_DIR__|${POC_SESSION_DIR:-$SCRIPT_DIR/output}|g" \
  "$SCRIPT_DIR/agents/${TEAM}-team.json")

# Determine lead agent slug
case "$TEAM" in
  art)       LEAD="art-lead" ;;
  writing)   LEAD="writing-lead" ;;
  editorial) LEAD="editorial-lead" ;;
  research)  LEAD="research-lead" ;;
  *)         echo "{\"error\":\"unknown team: $TEAM\"}"; exit 1 ;;
esac

# Clean environment for child process (mirrors team_session.py:_clean_env)
unset CLAUDECODE
unset CLAUDE_CODE_ENTRYPOINT

# Settings file: pre-approve tools subteams need
SETTINGS_FILE=$(mktemp)
trap "rm -f $SETTINGS_FILE; rm -f $OUTPUT_DIR/.running" EXIT
python3 -c "
import json, os, sys
d = os.environ.get('SCRIPT_DIR', '.')
rules = [
    'Bash(' + d + '/relay.sh:*)',
    'Bash(' + d + '/yt-transcript.sh:*)',
    'WebFetch',
    'WebSearch',
]
json.dump({'permissions': {'allow': rules}}, sys.stdout)
" > "$SETTINGS_FILE"

echo "[RELAY] >>> Dispatching to $TEAM team (lead: $LEAD)" >&2
echo "[RELAY]     Task: ${TASK:0:100}..." >&2

# Grant read access to session tree so subteams can see sibling dispatches + other teams
ADD_DIR_ARGS=()
[[ -n "${POC_SESSION_DIR:-}" ]] && ADD_DIR_ARGS=(--add-dir "$POC_SESSION_DIR")

# Plan → auto-approve → Execute (same script used by run.sh for uber level)
RESULT=$("$SCRIPT_DIR/plan-execute.sh" \
  --agents "$AGENTS_JSON" \
  --agent "$LEAD" \
  --auto-approve \
  --settings "$SETTINGS_FILE" \
  --cwd "$OUTPUT_DIR" \
  "${ADD_DIR_ARGS[@]}" \
  --filter-prefix "  [$TEAM] " \
  --plan-turns 10 \
  --exec-turns 30 \
  "$TASK") || true

echo "[RELAY] <<< $TEAM team finished" >&2

# ── Relay result immediately ──
# The stream's result event (type:result, subtype:success) signals completion.
# The accompanying text IS the result — relay it up NOW, before post-processing.

# List output files produced by the subteam (exclude hidden files)
OUTPUT_FILES=$(ls "$OUTPUT_DIR" 2>/dev/null | grep -v '^\.' | paste -sd ',' - || echo "")
echo "[RELAY]     Files: ${OUTPUT_FILES:-none}" >&2

# Build JSON summary
RESULT_JSON=$(jq -n \
  --arg team "$TEAM" \
  --arg status "completed" \
  --arg summary "$RESULT" \
  --arg output_files "$OUTPUT_FILES" \
  --arg output_dir "$OUTPUT_DIR" \
  '{team: $team, status: $status, summary: $summary, output_files: $output_files, output_dir: $output_dir}')

# Write result and clear sentinel — available to parent immediately
echo "$RESULT_JSON" > "$OUTPUT_DIR/.result.json"
rm -f "$OUTPUT_DIR/.running"

# Return result to caller (stdout for foreground Bash, task output for background)
echo "$RESULT_JSON"

# ── Post-processing (async, doesn't block result relay) ──
echo "[RELAY]     Extracting learnings (background)..." >&2
python3 "$SCRIPT_DIR/scripts/summarize_session.py" \
  --stream "$OUTPUT_DIR/.exec-stream.jsonl" \
  --output "$OUTPUT_DIR/MEMORY.md" 2>&1 | sed 's/^/[RELAY]     /' >&2 &
