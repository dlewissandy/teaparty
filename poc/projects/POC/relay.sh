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
CFA_PARENT_STATE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --team)             TEAM="$2"; shift 2 ;;
    --task)             TASK="$2"; shift 2 ;;
    --cfa-parent-state) CFA_PARENT_STATE="$2"; shift 2 ;;
    *)                  echo "{\"error\":\"unknown arg: $1\"}" >&2; exit 1 ;;
  esac
done

# Fall back to environment variable for CfA parent state
CFA_PARENT_STATE="${CFA_PARENT_STATE:-${POC_CFA_STATE:-}}"

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

  # Compute project CWD within dispatch worktree (mirrors run.sh PROJECT_WORKDIR logic).
  # Linked-repo: DISPATCH_WORKTREE/poc/projects/POC. Standalone: DISPATCH_WORKTREE.
  REL_PATH="${POC_RELATIVE_PATH:-.}"
  if [[ "$REL_PATH" != "." ]]; then
    WORK_CWD="$DISPATCH_WORKTREE/$REL_PATH"
    mkdir -p "$WORK_CWD"
  else
    WORK_CWD="$DISPATCH_WORKTREE"
  fi
  ADD_DIR_ARGS=(--add-dir "$DISPATCH_WORKTREE" --add-dir "$SESSION_WORKTREE")
  # Also grant read access to the main projects/ directory (if set)
  [[ -n "${PROJECTS_DIR:-}" ]] && ADD_DIR_ARGS+=(--add-dir "$PROJECTS_DIR")
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
WORK_CWD="$WORK_CWD" python3 -c "
import json, os, sys
d = os.environ.get('SCRIPT_DIR', '.')
rules = [
    'Bash(' + d + '/relay.sh:*)',
    'Bash(' + d + '/yt-transcript.sh:*)',
    'Bash(*)',
    'WebFetch',
    'WebSearch',
    'Write',
    'Edit',
    'ExitPlanMode',
]
block_task_cmd = d + '/hooks/block-task.sh'
enforce_write_cmd = d + '/hooks/enforce-write-scope.sh'
json.dump({
    'permissions': {'allow': rules},
    'hooks': {
        'PreToolUse': [
            {
                'matcher': 'Task',
                'hooks': [{'type': 'command', 'command': block_task_cmd}]
            },
            {
                'matcher': 'TaskOutput',
                'hooks': [{'type': 'command', 'command': block_task_cmd}]
            },
            {
                'matcher': 'TaskStop',
                'hooks': [{'type': 'command', 'command': block_task_cmd}]
            },
            {
                'matcher': 'Write',
                'hooks': [{'type': 'command', 'command': enforce_write_cmd}]
            },
            {
                'matcher': 'Edit',
                'hooks': [{'type': 'command', 'command': enforce_write_cmd}]
            },
        ]
    },
    'env': {
        'POC_PROJECT_WORKDIR': os.environ.get('WORK_CWD', ''),
        'POC_RELATIVE_PATH': os.environ.get('POC_RELATIVE_PATH', ''),
        'POC_SESSION_DIR': os.environ.get('POC_SESSION_DIR', ''),
        'POC_PROJECT_DIR': os.environ.get('POC_PROJECT_DIR', ''),
        'POC_PROJECT': os.environ.get('POC_PROJECT', ''),
        'POC_SESSION_WORKTREE': os.environ.get('POC_SESSION_WORKTREE', ''),
        'POC_CFA_STATE': os.environ.get('POC_CFA_STATE', ''),
        'SCRIPT_DIR': d,
    },
}, sys.stdout)
" > "$SETTINGS_FILE"

echo -e "  ${C_DIM}[relay] >>> ${TEAM} team (${LEAD})${C_RESET}" >&2
echo -e "  ${C_DIM}[relay]     ${TASK:0:100}...${C_RESET}" >&2
session_log DISPATCH ">>> $TEAM team ($LEAD) -- ${TASK:0:100}"

# ── CfA child state + per-team proxy model ──
DISPATCH_CFA_STATE="$INFRA_DIR/.cfa-state.json"
TEAM_PROXY_MODEL="${POC_PROJECT_DIR:-.}/.proxy-confidence-${TEAM}.json"

if [[ -n "$CFA_PARENT_STATE" && -f "$CFA_PARENT_STATE" ]]; then
  python3 "$SCRIPT_DIR/scripts/cfa_state.py" --make-child \
    --parent "$CFA_PARENT_STATE" --team "$TEAM" --output "$DISPATCH_CFA_STATE" 2>/dev/null || true
  echo -e "  ${C_DIM}[relay]     CfA child state created${C_RESET}" >&2
  session_log STATE "$TEAM CfA child state created"
fi

# ── Plan → proxy-gated → Execute (with CfA retry loop) ──
MAX_DISPATCH_RETRIES="${MAX_DISPATCH_RETRIES:-5}"
DISPATCH_RETRIES=0
DISPATCH_EXIT=0
RESULT=""

while true; do
  DISPATCH_EXIT=0
  RESULT=$("$SCRIPT_DIR/plan-execute.sh" \
    --agents "$AGENTS_JSON" \
    --agent "$LEAD" \
    --agent-mode \
    --settings "$SETTINGS_FILE" \
    --cwd "$WORK_CWD" \
    --stream-dir "$INFRA_DIR" \
    --proxy-model "$TEAM_PROXY_MODEL" \
    ${DISPATCH_CFA_STATE:+--cfa-state "$DISPATCH_CFA_STATE"} \
    "${ADD_DIR_ARGS[@]}" \
    --filter-prefix "  [$TEAM] " \
    "$TASK") || DISPATCH_EXIT=$?

  if [[ $DISPATCH_EXIT -eq 3 || $DISPATCH_EXIT -eq 4 ]]; then
    # Planning backtrack or infrastructure failure — retry locally
    ((DISPATCH_RETRIES++))
    retry_reason="Planning backtrack"
    [[ $DISPATCH_EXIT -eq 4 ]] && retry_reason="Infrastructure failure"
    if [[ $DISPATCH_RETRIES -ge $MAX_DISPATCH_RETRIES ]]; then
      echo -e "  ${C_YELLOW}[relay] Max retries ($MAX_DISPATCH_RETRIES) reached for $TEAM ($retry_reason)${C_RESET}" >&2
      break
    fi
    echo -e "  ${C_DIM}[relay] $retry_reason — retry $DISPATCH_RETRIES/$MAX_DISPATCH_RETRIES${C_RESET}" >&2
    session_log DISPATCH "$TEAM $retry_reason — retry $DISPATCH_RETRIES/$MAX_DISPATCH_RETRIES"
    continue
  fi
  # exit 0, 1, 2, 10, 11 — stop loop (escalations bubble up to caller)
  if [[ $DISPATCH_EXIT -eq 10 ]]; then
    echo -e "  ${C_DIM}[relay] Plan escalation — proxy not confident, needs outer review${C_RESET}" >&2
    session_log DISPATCH "$TEAM plan escalation — needs outer review"
  elif [[ $DISPATCH_EXIT -eq 11 ]]; then
    echo -e "  ${C_DIM}[relay] Work escalation — proxy not confident, needs outer review${C_RESET}" >&2
    session_log DISPATCH "$TEAM work escalation — needs outer review"
  fi
  break
done

echo -e "  ${C_DIM}[relay] <<< ${TEAM} team finished (exit=$DISPATCH_EXIT, retries=$DISPATCH_RETRIES)${C_RESET}" >&2
session_log DISPATCH "<<< $TEAM team -- $CFA_STATUS (exit=$DISPATCH_EXIT, retries=$DISPATCH_RETRIES)"

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

# Determine CfA status for result JSON
case $DISPATCH_EXIT in
  0)  CFA_STATUS="completed" ;;
  1)  CFA_STATUS="failed" ;;
  2)  CFA_STATUS="backtrack_intent" ;;
  3)  CFA_STATUS="backtrack_planning" ;;
  4)  CFA_STATUS="infrastructure_failure" ;;
  10) CFA_STATUS="needs_plan_review" ;;
  11) CFA_STATUS="needs_work_review" ;;
  *)  CFA_STATUS="error" ;;
esac

# Read backtrack/escalation reason if available
BACKTRACK_REASON=""
[[ -f "$INFRA_DIR/.backtrack-feedback.txt" ]] && BACKTRACK_REASON=$(cat "$INFRA_DIR/.backtrack-feedback.txt" 2>/dev/null || true)

# Escalation context for needs_plan_review/needs_work_review
ESCALATION_CONTEXT=""
if [[ $DISPATCH_EXIT -eq 10 || $DISPATCH_EXIT -eq 11 ]]; then
  ESCALATION_CONTEXT="$BACKTRACK_REASON"
fi

# Read child CfA state for reporting
CFA_STATE_VAL="unknown"
if [[ -f "$DISPATCH_CFA_STATE" ]]; then
  CFA_STATE_VAL=$(python3 -c "
import json, sys
with open(sys.argv[1]) as f: d = json.load(f)
print(d.get('state', 'unknown'))
" "$DISPATCH_CFA_STATE" 2>/dev/null || echo "unknown")
fi

# Determine backtrack direction
CFA_BACKTRACK=""
[[ $DISPATCH_EXIT -eq 2 ]] && CFA_BACKTRACK="intent"
[[ $DISPATCH_EXIT -eq 3 ]] && CFA_BACKTRACK="planning"

# Build JSON summary with CfA fields
RESULT_JSON=$(jq -n \
  --arg team "$TEAM" \
  --arg status "$CFA_STATUS" \
  --arg summary "$RESULT" \
  --arg output_files "$OUTPUT_FILES" \
  --arg cfa_state "$CFA_STATE_VAL" \
  --arg cfa_backtrack "$CFA_BACKTRACK" \
  --arg backtrack_reason "$BACKTRACK_REASON" \
  --arg escalation_context "$ESCALATION_CONTEXT" \
  --argjson dispatch_retries "$DISPATCH_RETRIES" \
  --argjson exit_code "$DISPATCH_EXIT" \
  '{team: $team, status: $status, summary: $summary, output_files: $output_files,
    cfa_state: $cfa_state, cfa_backtrack: $cfa_backtrack,
    backtrack_reason: $backtrack_reason, escalation_context: $escalation_context,
    dispatch_retries: $dispatch_retries, exit_code: $exit_code}')

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
