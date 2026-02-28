#!/usr/bin/env bash
# Relay a task to a subteam by spawning a plan→execute cycle.
# Called by liaison agents via Bash.
#
# Each dispatch gets its own git worktree (branched from the session branch).
# On completion: commit deliverables, merge into session branch, clean up worktree.
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

# ── Dispatch setup: worktree + infra dir ──
DISPATCH_TS=$(date +%Y%m%d-%H%M%S)
DISPATCH_BRANCH="dispatch/$TEAM/$DISPATCH_TS"

PROJECT_DIR="${POC_PROJECT_DIR:-}"
SESSION_WORKTREE="${POC_SESSION_WORKTREE:-}"

if [[ -n "$PROJECT_DIR" && -n "$SESSION_WORKTREE" ]]; then
  # Worktree mode: create dispatch worktree branched from session
  DISPATCH_WORKTREE="$PROJECT_DIR/.worktrees/$TEAM-$DISPATCH_TS"
  INFRA_DIR="${POC_SESSION_DIR:-$PROJECT_DIR/.sessions}/$TEAM/$DISPATCH_TS"

  mkdir -p "$PROJECT_DIR/.worktrees"
  git -C "$SESSION_WORKTREE" worktree add "$DISPATCH_WORKTREE" -b "$DISPATCH_BRANCH"
  mkdir -p "$INFRA_DIR"
  touch "$INFRA_DIR/.running"

  WORK_CWD="$DISPATCH_WORKTREE"
  ADD_DIR_ARGS=(--add-dir "$SESSION_WORKTREE")
else
  # Fallback: flat directory mode (standalone use without worktrees)
  INFRA_DIR="${POC_SESSION_DIR:-$SCRIPT_DIR/output}/$TEAM/$DISPATCH_TS"
  mkdir -p "$INFRA_DIR"
  touch "$INFRA_DIR/.running"

  DISPATCH_WORKTREE=""
  WORK_CWD="$INFRA_DIR"
  ADD_DIR_ARGS=()
  [[ -n "${POC_SESSION_DIR:-}" ]] && ADD_DIR_ARGS=(--add-dir "$POC_SESSION_DIR")
fi

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
  coding)    LEAD="coding-lead" ;;
  *)         echo "{\"error\":\"unknown team: $TEAM\"}"; exit 1 ;;
esac

# Clean environment for child process (mirrors team_session.py:_clean_env)
unset CLAUDECODE
unset CLAUDE_CODE_ENTRYPOINT

# Settings file: pre-approve tools subteams need
SETTINGS_FILE=$(mktemp)
trap "rm -f $SETTINGS_FILE; rm -f $INFRA_DIR/.running" EXIT
python3 -c "
import json, os, sys
d = os.environ.get('SCRIPT_DIR', '.')
rules = [
    'Bash(' + d + '/relay.sh:*)',
    'Bash(' + d + '/yt-transcript.sh:*)',
    'Bash(*)',
    'WebFetch',
    'WebSearch',
]
json.dump({'permissions': {'allow': rules}}, sys.stdout)
" > "$SETTINGS_FILE"

echo "[RELAY] >>> Dispatching to $TEAM team (lead: $LEAD)" >&2
echo "[RELAY]     Task: ${TASK:0:100}..." >&2

# Plan → auto-approve → Execute
RESULT=$("$SCRIPT_DIR/plan-execute.sh" \
  --agents "$AGENTS_JSON" \
  --agent "$LEAD" \
  --auto-approve \
  --settings "$SETTINGS_FILE" \
  --cwd "$WORK_CWD" \
  --stream-dir "$INFRA_DIR" \
  "${ADD_DIR_ARGS[@]}" \
  --filter-prefix "  [$TEAM] " \
  --plan-turns 10 \
  --exec-turns 30 \
  "$TASK") || true

echo "[RELAY] <<< $TEAM team finished" >&2

# ── Worktree completion: commit, merge, cleanup ──
if [[ -n "$DISPATCH_WORKTREE" && -d "$DISPATCH_WORKTREE" ]]; then
  # Commit any deliverables written by the subteam
  git -C "$DISPATCH_WORKTREE" add -A 2>/dev/null || true
  if ! git -C "$DISPATCH_WORKTREE" diff --cached --quiet 2>/dev/null; then
    COMMIT_MSG=$(echo "$RESULT" | head -c 72)
    git -C "$DISPATCH_WORKTREE" commit -m "$TEAM: ${COMMIT_MSG:-dispatch $DISPATCH_TS}" 2>&1 \
      | sed 's/^/[RELAY]     /' >&2 || true
  else
    echo "[RELAY]     No deliverables to commit" >&2
  fi

  # Merge dispatch branch into session branch
  echo "[RELAY]     Merging $DISPATCH_BRANCH into session..." >&2
  if ! git -C "$SESSION_WORKTREE" merge --no-ff "$DISPATCH_BRANCH" \
      -m "merge $TEAM/$DISPATCH_TS" 2>&1 | sed 's/^/[RELAY]     /' >&2; then
    echo "[RELAY]     Merge conflict — retrying with -X theirs..." >&2
    git -C "$SESSION_WORKTREE" merge --abort 2>/dev/null || true
    git -C "$SESSION_WORKTREE" merge -X theirs --no-ff "$DISPATCH_BRANCH" \
      -m "merge $TEAM/$DISPATCH_TS (auto-resolved)" 2>&1 \
      | sed 's/^/[RELAY]     /' >&2 || \
      echo "[RELAY]     WARNING: Merge failed — deliverables remain on branch $DISPATCH_BRANCH" >&2
  fi

  # Clean up worktree and branch
  git -C "$PROJECT_DIR" worktree remove "$DISPATCH_WORKTREE" 2>/dev/null || true
  git -C "$PROJECT_DIR" branch -d "$DISPATCH_BRANCH" 2>/dev/null || true
fi

# ── Relay result immediately ──

# List deliverable files (from session worktree after merge, or from work dir)
if [[ -n "$SESSION_WORKTREE" && -d "$SESSION_WORKTREE" ]]; then
  OUTPUT_FILES=$(git -C "$SESSION_WORKTREE" diff --name-only HEAD~1 2>/dev/null \
    | paste -sd ',' - || echo "")
else
  OUTPUT_FILES=$(ls "$WORK_CWD" 2>/dev/null | grep -v '^\.' | paste -sd ',' - || echo "")
fi
echo "[RELAY]     Files: ${OUTPUT_FILES:-none}" >&2

# Build JSON summary
RESULT_JSON=$(jq -n \
  --arg team "$TEAM" \
  --arg status "completed" \
  --arg summary "$RESULT" \
  --arg output_files "$OUTPUT_FILES" \
  '{team: $team, status: $status, summary: $summary, output_files: $output_files}')

# Write result and clear sentinel — available to parent immediately
echo "$RESULT_JSON" > "$INFRA_DIR/.result.json"
rm -f "$INFRA_DIR/.running"

# Return result to caller (stdout for foreground Bash, task output for background)
echo "$RESULT_JSON"

# ── Post-processing (async, doesn't block result relay) ──
echo "[RELAY]     Extracting learnings (background)..." >&2
python3 "$SCRIPT_DIR/scripts/summarize_session.py" \
  --stream "$INFRA_DIR/.exec-stream.jsonl" \
  --output "$INFRA_DIR/MEMORY.md" 2>&1 | sed 's/^/[RELAY]     /' >&2 &
