#!/usr/bin/env bash
# Relay a task to a subteam by spawning a new claude process.
# Called by liaison agents via Bash.
#
# Usage: relay.sh --team art --task "Create diagrams for..."
#        relay.sh --team art --plan-only --task "Create diagrams for..."
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1

TEAM=""
TASK=""
PLAN_ONLY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --team)      TEAM="$2"; shift 2 ;;
    --task)      TASK="$2"; shift 2 ;;
    --plan-only) PLAN_ONLY=true; shift ;;
    *)           echo "{\"error\":\"unknown arg: $1\"}" >&2; exit 1 ;;
  esac
done

[[ -z "$TEAM" ]] && { echo '{"error":"--team required"}'; exit 1; }
[[ -z "$TASK" ]] && { echo '{"error":"--task required"}'; exit 1; }

OUTPUT_DIR="$SCRIPT_DIR/output/$TEAM"
mkdir -p "$OUTPUT_DIR"

# Read agent definitions and substitute the POC directory path
AGENTS_JSON=$(sed "s|__POC_DIR__|$SCRIPT_DIR|g" \
  "$SCRIPT_DIR/agents/${TEAM}-team.json")

# Determine lead agent slug
case "$TEAM" in
  art)       LEAD="art-lead" ;;
  writing)   LEAD="writing-lead" ;;
  editorial) LEAD="editorial-lead" ;;
  *)         echo "{\"error\":\"unknown team: $TEAM\"}"; exit 1 ;;
esac

# Clean environment for child process (mirrors team_session.py:_clean_env)
# CLAUDECODE and CLAUDE_CODE_ENTRYPOINT from the parent process cause
# child claude processes to run in restricted mode — must remove them.
unset CLAUDECODE
unset CLAUDE_CODE_ENTRYPOINT

STDERR_LOG="$OUTPUT_DIR/.relay-stderr.log"

# In plan-only mode, prepend planning instructions and reduce turns
if [[ "$PLAN_ONLY" == true ]]; then
  TASK="[PLAN ONLY] Create a detailed plan for the following task. Describe what you will create, the approach, format decisions, and file names. Do NOT delegate to specialists or create any output files yet.

Task: $TASK"
  MAX_TURNS=8
  PHASE="plan"
else
  MAX_TURNS=30
  PHASE="execute"
fi

# Log dispatch to stderr (visible in parent process)
echo "[RELAY] >>> Dispatching to $TEAM team (lead: $LEAD, phase: $PHASE)" >&2
echo "[RELAY]     Task: ${TASK:0:100}..." >&2
echo "[RELAY]     Output dir: $OUTPUT_DIR" >&2

# Spawn the subteam in the output directory so Write creates files there
RAW=$(cd "$OUTPUT_DIR" && echo "$TASK" | claude -p \
  --output-format stream-json \
  --verbose \
  --max-turns "$MAX_TURNS" \
  --permission-mode acceptEdits \
  --agents "$AGENTS_JSON" \
  --agent "$LEAD" 2>"$STDERR_LOG") || true

echo "[RELAY] <<< $TEAM team finished (phase: $PHASE)" >&2
echo "[RELAY]     stderr log: $STDERR_LOG" >&2

# Show any errors from the subteam
if [[ -s "$STDERR_LOG" ]]; then
  echo "[RELAY]     stderr tail:" >&2
  tail -5 "$STDERR_LOG" >&2
fi

# Extract the final result text
SUMMARY=$(echo "$RAW" | python3 "$SCRIPT_DIR/extract_result.py")

# List output files produced by the subteam (exclude hidden files)
OUTPUT_FILES=$(ls "$OUTPUT_DIR" 2>/dev/null | grep -v '^\.' | paste -sd ',' - || echo "")

echo "[RELAY]     Files: ${OUTPUT_FILES:-none}" >&2

# Build JSON summary using jq for safe quoting
jq -n \
  --arg team "$TEAM" \
  --arg status "completed" \
  --arg phase "$PHASE" \
  --arg summary "$SUMMARY" \
  --arg output_files "$OUTPUT_FILES" \
  --arg output_dir "$OUTPUT_DIR" \
  '{team: $team, status: $status, phase: $phase, summary: $summary, output_files: $output_files, output_dir: $output_dir}'
