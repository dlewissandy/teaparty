#!/usr/bin/env bash
# Hierarchical Agent Teams POC — Entry Point
#
# Usage: ./poc/run.sh "Create a document about the solar system with diagrams"
#        ./poc/run.sh --project tea-handbook "Add chapter 2 on oolong"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse arguments: optional --project override, then positional task
PROJECT_OVERRIDE=""
TASK=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT_OVERRIDE="$2"; shift 2 ;;
    *)         TASK="$1"; shift ;;
  esac
done
[[ -z "$TASK" ]] && { echo "Usage: run.sh [--project <slug>] '<task description>'"; exit 1; }

export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
export CLAUDE_CODE_MAX_OUTPUT_TOKENS="${CLAUDE_CODE_MAX_OUTPUT_TOKENS:-128000}"

# ── Project classification ──
export POC_OUTPUT_DIR="$SCRIPT_DIR/output"
PROJECTS_DIR="$POC_OUTPUT_DIR/projects"
mkdir -p "$PROJECTS_DIR"

if [[ -n "$PROJECT_OVERRIDE" ]]; then
  PROJECT="$PROJECT_OVERRIDE"
else
  PROJECT=$(python3 "$SCRIPT_DIR/scripts/classify_task.py" \
    --task "$TASK" \
    --projects-dir "$PROJECTS_DIR" 2>/dev/null) || PROJECT="default"
fi
export POC_PROJECT="$PROJECT"
export POC_PROJECT_DIR="$PROJECTS_DIR/$PROJECT"

# ── Project repo initialization (first run only) ──
if [[ ! -d "$POC_PROJECT_DIR/.git" ]]; then
  mkdir -p "$POC_PROJECT_DIR"
  git init "$POC_PROJECT_DIR"
  cat > "$POC_PROJECT_DIR/.gitignore" << 'GITIGNORE'
.worktrees/
.sessions/
MEMORY.md
GITIGNORE
  cat > "$POC_PROJECT_DIR/CLAUDE.md" << CLAUDEMD
# Project: $PROJECT
CLAUDEMD
  git -C "$POC_PROJECT_DIR" add -A
  git -C "$POC_PROJECT_DIR" commit -m "init project $PROJECT"
fi

# ── Session setup with worktree ──
SESSION_TS=$(date +%Y%m%d-%H%M%S)
SESSION_BRANCH="session/$SESSION_TS"
SESSION_WORKTREE="$POC_PROJECT_DIR/.worktrees/session-$SESSION_TS"
INFRA_DIR="$POC_PROJECT_DIR/.sessions/$SESSION_TS"

# Create session worktree (branched from main)
mkdir -p "$POC_PROJECT_DIR/.worktrees"
git -C "$POC_PROJECT_DIR" worktree add "$SESSION_WORKTREE" -b "$SESSION_BRANCH"

# Create infra dirs for each team
mkdir -p "$INFRA_DIR"/{art,writing,editorial,research}

# Export for relay.sh and promote_learnings.sh
export POC_SESSION_WORKTREE="$SESSION_WORKTREE"
export POC_SESSION_DIR="$INFRA_DIR"

# Memory files — global persists across all projects, project persists across sessions
touch "$POC_OUTPUT_DIR/MEMORY.md"
touch "$POC_PROJECT_DIR/MEMORY.md"

# Shared conversation log — scoped to this session.
# Subteam output is indented via --filter-prefix in relay.sh.
export CONVERSATION_LOG="$INFRA_DIR/.conversation"
> "$CONVERSATION_LOG"

# Tail the conversation log in the background so it streams to the terminal
tail -f "$CONVERSATION_LOG" &
TAIL_PID=$!

# Substitute placeholders with absolute paths in agent definitions
AGENTS_JSON=$(sed -e "s|__POC_DIR__|$SCRIPT_DIR|g" \
                  -e "s|__SESSION_DIR__|$INFRA_DIR|g" \
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
    'POC_PROJECT': os.environ.get('POC_PROJECT', ''),
    'POC_PROJECT_DIR': os.environ.get('POC_PROJECT_DIR', ''),
    'POC_SESSION_DIR': os.environ.get('POC_SESSION_DIR', ''),
    'POC_SESSION_WORKTREE': os.environ.get('POC_SESSION_WORKTREE', ''),
}}, sys.stdout)
" > "$SETTINGS_FILE"

echo "=== Hierarchical Agent Teams POC ==="
echo "Project: $PROJECT"
echo "Task: $TASK"
echo "Session: $SESSION_TS"
echo "Worktree: $SESSION_WORKTREE"
echo "Infra: $INFRA_DIR/"
echo ""

# Plan → Approve → Execute (same script used by relay.sh for subteams)
"$SCRIPT_DIR/plan-execute.sh" \
  --agents "$AGENTS_JSON" \
  --agent project-lead \
  --settings "$SETTINGS_FILE" \
  --cwd "$SESSION_WORKTREE" \
  --stream-dir "$INFRA_DIR" \
  --add-dir "$POC_PROJECT_DIR" \
  --plan-turns 15 \
  --exec-turns 30 \
  "$TASK"

# ── Session completion: merge session branch into main ──
echo ""
echo "=== Merging session into main ==="

git -C "$POC_PROJECT_DIR" merge --no-ff "$SESSION_BRANCH" \
  -m "session $SESSION_TS" 2>&1 || \
  git -C "$POC_PROJECT_DIR" merge -X theirs --no-ff "$SESSION_BRANCH" \
    -m "session $SESSION_TS (auto-resolved)" 2>&1 || \
  echo "WARNING: Session merge failed — deliverables remain on branch $SESSION_BRANCH" >&2

# Clean up worktree and branch
git -C "$POC_PROJECT_DIR" worktree remove "$SESSION_WORKTREE" 2>/dev/null || true
git -C "$POC_PROJECT_DIR" branch -d "$SESSION_BRANCH" 2>/dev/null || true

# ── Extract learnings ──
echo ""
echo "=== Extracting session learnings ==="

# 1. Roll up dispatch MEMORYs → team MEMORY.md (for each team that ran)
"$SCRIPT_DIR/scripts/promote_learnings.sh" --scope team || true

# 2. Roll up team MEMORYs → session MEMORY.md (team-agnostic filter)
"$SCRIPT_DIR/scripts/promote_learnings.sh" --scope session || true

# 3. Roll up session MEMORY → project MEMORY.md
"$SCRIPT_DIR/scripts/promote_learnings.sh" --scope project || true

# 4. Roll up project MEMORY → global MEMORY.md (project-agnostic filter)
"$SCRIPT_DIR/scripts/promote_learnings.sh" --scope global || true

# Stop the tail
kill "$TAIL_PID" 2>/dev/null || true
wait "$TAIL_PID" 2>/dev/null || true

echo ""
echo "=== Session: $SESSION_TS ==="
echo "Project: $PROJECT"
echo "Deliverables (on main):"
git -C "$POC_PROJECT_DIR" ls-files 2>/dev/null | grep -v '^\.' | sort || echo "  (none)"
echo "Infra: $INFRA_DIR/"
echo "Project memory: $POC_PROJECT_DIR/MEMORY.md"
echo "Global memory: $POC_OUTPUT_DIR/MEMORY.md"
