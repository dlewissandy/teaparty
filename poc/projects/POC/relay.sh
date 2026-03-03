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
source "$SCRIPT_DIR/chrome.sh"
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
REPO_DIR="${POC_REPO_DIR:-$PROJECT_DIR}"
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
hook_cmd = d + '/hooks/block-task.sh'
json.dump({
    'permissions': {'allow': rules},
    'hooks': {
        'PreToolUse': [
            {
                'matcher': 'Task',
                'hooks': [{'type': 'command', 'command': hook_cmd}]
            },
            {
                'matcher': 'TaskOutput',
                'hooks': [{'type': 'command', 'command': hook_cmd}]
            },
            {
                'matcher': 'TaskStop',
                'hooks': [{'type': 'command', 'command': hook_cmd}]
            },
        ]
    },
}, sys.stdout)
" > "$SETTINGS_FILE"

echo -e "  ${C_DIM}[relay] >>> ${TEAM} team (${LEAD})${C_RESET}" >&2
echo -e "  ${C_DIM}[relay]     ${TASK:0:100}...${C_RESET}" >&2

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

echo -e "  ${C_DIM}[relay] <<< ${TEAM} team finished${C_RESET}" >&2

# ── Worktree completion: commit, merge, cleanup ──
if [[ -n "$DISPATCH_WORKTREE" && -d "$DISPATCH_WORKTREE" ]]; then
  # Commit any deliverables written by the subteam
  DISPATCH_SUBJECT="${TASK:0:60}"
  git -C "$DISPATCH_WORKTREE" add -A 2>/dev/null || true
  if ! git -C "$DISPATCH_WORKTREE" diff --cached --quiet 2>/dev/null; then
    git -C "$DISPATCH_WORKTREE" commit -m "$TEAM: ${DISPATCH_SUBJECT:-dispatch}" 2>&1 \
      | sed "s/^/  $(printf '\033[2m')[relay]     /" | sed "s/$/$(printf '\033[0m')/" >&2 || true
  else
    echo -e "  ${C_DIM}[relay]     No deliverables to commit${C_RESET}" >&2
  fi

  # Squash-merge dispatch branch into session branch
  echo -e "  ${C_DIM}[relay]     Squash-merging $DISPATCH_BRANCH into session...${C_RESET}" >&2

  # Collect dispatch commit history before squashing (for the commit body)
  DISPATCH_LOG=$(git -C "$SESSION_WORKTREE" log --format='- %s' HEAD.."$DISPATCH_BRANCH" 2>/dev/null || true)

  if ! git -C "$SESSION_WORKTREE" merge --squash "$DISPATCH_BRANCH" 2>&1 \
      | sed "s/^/  $(printf '\033[2m')[relay]     /" | sed "s/$/$(printf '\033[0m')/" >&2; then
    echo -e "  ${C_DIM}[relay]     Merge conflict — retrying with -X theirs...${C_RESET}" >&2
    git -C "$SESSION_WORKTREE" reset --hard HEAD 2>/dev/null || true
    git -C "$SESSION_WORKTREE" merge --squash -X theirs "$DISPATCH_BRANCH" 2>&1 \
      | sed "s/^/  $(printf '\033[2m')[relay]     /" | sed "s/$/$(printf '\033[0m')/" >&2 || \
      echo -e "  ${C_RED}[relay] Merge failed — deliverables remain on branch $DISPATCH_BRANCH${C_RESET}" >&2
  fi

  # Commit squashed changes with a structured message
  if ! git -C "$SESSION_WORKTREE" diff --cached --quiet 2>/dev/null; then
    SQUASH_MSG_FILE=$(mktemp)
    {
      echo "$TEAM: ${DISPATCH_SUBJECT:-dispatch}"
      echo ""
      if [[ -n "$DISPATCH_LOG" ]]; then
        echo "Squashed commits:"
        echo "$DISPATCH_LOG"
        echo ""
      fi
      echo "Files changed:"
      git -C "$SESSION_WORKTREE" diff --cached --name-only 2>/dev/null | sed 's/^/- /'
    } > "$SQUASH_MSG_FILE"
    git -C "$SESSION_WORKTREE" commit -F "$SQUASH_MSG_FILE" 2>&1 \
      | sed "s/^/  $(printf '\033[2m')[relay]     /" | sed "s/$/$(printf '\033[0m')/" >&2 || true
    rm -f "$SQUASH_MSG_FILE"
  else
    echo -e "  ${C_DIM}[relay]     Nothing to commit after squash merge${C_RESET}" >&2
  fi

  # Clean up worktree and branch
  git -C "$REPO_DIR" worktree remove "$DISPATCH_WORKTREE" 2>/dev/null || true
  git -C "$REPO_DIR" branch -d "$DISPATCH_BRANCH" 2>/dev/null || true
fi

# ── Relay result immediately ──

# List deliverable files (from session worktree after merge, or from work dir)
if [[ -n "$SESSION_WORKTREE" && -d "$SESSION_WORKTREE" ]]; then
  OUTPUT_FILES=$(git -C "$SESSION_WORKTREE" diff --name-only HEAD~1 2>/dev/null \
    | paste -sd ',' - || echo "")
else
  OUTPUT_FILES=$(ls "$WORK_CWD" 2>/dev/null | grep -v '^\.' | paste -sd ',' - || echo "")
fi
echo -e "  ${C_DIM}[relay]     Files: ${OUTPUT_FILES:-none}${C_RESET}" >&2

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
echo -e "  ${C_DIM}[relay]     Extracting learnings...${C_RESET}" >&2
python3 "$SCRIPT_DIR/scripts/summarize_session.py" \
  --stream "$INFRA_DIR/.exec-stream.jsonl" \
  --output "$INFRA_DIR/MEMORY.md" 2>&1 | sed "s/^/  $(printf '\033[2m')[relay]     /" | sed "s/$/$(printf '\033[0m')/" >&2 &
