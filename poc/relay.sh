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
unset CLAUDECODE
unset CLAUDE_CODE_ENTRYPOINT

echo "[RELAY] >>> Dispatching to $TEAM team (lead: $LEAD)" >&2
echo "[RELAY]     Task: ${TASK:0:100}..." >&2

# Plan → auto-approve → Execute (same script used by run.sh for uber level)
RESULT=$("$SCRIPT_DIR/plan-execute.sh" \
  --agents "$AGENTS_JSON" \
  --agent "$LEAD" \
  --auto-approve \
  --cwd "$OUTPUT_DIR" \
  --filter-prefix "  [$TEAM] " \
  --plan-turns 10 \
  --exec-turns 30 \
  "$TASK") || true

echo "[RELAY] <<< $TEAM team finished" >&2

# List output files produced by the subteam (exclude hidden files)
OUTPUT_FILES=$(ls "$OUTPUT_DIR" 2>/dev/null | grep -v '^\.' | paste -sd ',' - || echo "")
echo "[RELAY]     Files: ${OUTPUT_FILES:-none}" >&2

# Build JSON summary
jq -n \
  --arg team "$TEAM" \
  --arg status "completed" \
  --arg summary "$RESULT" \
  --arg output_files "$OUTPUT_FILES" \
  --arg output_dir "$OUTPUT_DIR" \
  '{team: $team, status: $status, summary: $summary, output_files: $output_files, output_dir: $output_dir}'
