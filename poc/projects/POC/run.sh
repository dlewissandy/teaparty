#!/usr/bin/env bash
# Hierarchical Agent Teams POC — Entry Point
#
# Usage: ./poc/run.sh "Create a document about the solar system with diagrams"
#        ./poc/run.sh --project tea-handbook "Add chapter 2 on oolong"
#        ./poc/run.sh --project POC "Improve the stream filter"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/chrome.sh"

# Parse arguments: optional --project override, --skip-intent, then positional task
PROJECT_OVERRIDE=""
SKIP_INTENT="true"
TASK=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)      PROJECT_OVERRIDE="$2"; shift 2 ;;
    --skip-intent)  SKIP_INTENT="true"; shift ;;
    --with-intent)  SKIP_INTENT="false"; shift ;;
    *)              TASK="$1"; shift ;;
  esac
done
[[ -z "$TASK" ]] && { echo "Usage: run.sh [--project <slug>] '<task description>'"; exit 1; }

export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
export CLAUDE_CODE_MAX_OUTPUT_TOKENS="${CLAUDE_CODE_MAX_OUTPUT_TOKENS:-128000}"

# ── Project classification ──
export POC_OUTPUT_DIR="$POC_ROOT"
PROJECTS_DIR="$POC_ROOT/projects"
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

# ── Project repo detection ──
# Three cases:
#   1. Project has its own .git — isolated repo (standard for runtime projects)
#   2. Project has .linked-repo — part of a parent git repo (the POC/dogfooding case)
#   3. New project — init isolated repo
if [[ -d "$POC_PROJECT_DIR/.git" ]]; then
  POC_REPO_DIR="$POC_PROJECT_DIR"
elif [[ -f "$POC_PROJECT_DIR/.linked-repo" ]]; then
  POC_REPO_DIR=$(git -C "$POC_PROJECT_DIR" rev-parse --show-toplevel)
else
  mkdir -p "$POC_PROJECT_DIR"
  git init "$POC_PROJECT_DIR"
  cat > "$POC_PROJECT_DIR/.gitignore" << 'GITIGNORE'
.worktrees/
.sessions/
MEMORY.md
OBSERVATIONS.md
ESCALATION.md
.memory.db
GITIGNORE
  cat > "$POC_PROJECT_DIR/CLAUDE.md" << CLAUDEMD
# Project: $PROJECT
CLAUDEMD
  git -C "$POC_PROJECT_DIR" add -A
  git -C "$POC_PROJECT_DIR" commit -m "init project $PROJECT"
  POC_REPO_DIR="$POC_PROJECT_DIR"
fi
export POC_REPO_DIR

# ── Session setup with worktree ──
SESSION_TS=$(date +%Y%m%d-%H%M%S)
SESSION_BRANCH="session/$SESSION_TS"
SESSION_WORKTREE="$POC_PROJECT_DIR/.worktrees/session-$SESSION_TS"
INFRA_DIR="$POC_PROJECT_DIR/.sessions/$SESSION_TS"

# Create session worktree (branched from repo HEAD)
mkdir -p "$POC_PROJECT_DIR/.worktrees"
git -C "$POC_REPO_DIR" worktree add "$SESSION_WORKTREE" -b "$SESSION_BRANCH"

# Create infra dirs for each team
mkdir -p "$INFRA_DIR"/{art,writing,editorial,research,coding}

# Export for relay.sh and promote_learnings.sh
export POC_SESSION_WORKTREE="$SESSION_WORKTREE"
export POC_SESSION_DIR="$INFRA_DIR"

# Memory files — global persists across all projects, project persists across sessions
touch "$POC_OUTPUT_DIR/MEMORY.md"
touch "$POC_PROJECT_DIR/MEMORY.md"
touch "$POC_PROJECT_DIR/OBSERVATIONS.md"
touch "$POC_PROJECT_DIR/ESCALATION.md"

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
    'POC_REPO_DIR': os.environ.get('POC_REPO_DIR', ''),
    'POC_SESSION_DIR': os.environ.get('POC_SESSION_DIR', ''),
    'POC_SESSION_WORKTREE': os.environ.get('POC_SESSION_WORKTREE', ''),
}}, sys.stdout)
" > "$SETTINGS_FILE"

# ── Startup banner ──
SUBTITLE="Project: $PROJECT  Session: $SESSION_TS"
[[ "$POC_REPO_DIR" != "$POC_PROJECT_DIR" ]] && SUBTITLE="$SUBTITLE  Repo: $POC_REPO_DIR"
chrome_banner "Hierarchical Agent Teams" "$SUBTITLE"
echo -e "  ${C_DIM}Task:${C_RESET} $TASK" >&2
echo -e "  ${C_DIM}Worktree:${C_RESET} $SESSION_WORKTREE" >&2
echo -e "  ${C_DIM}Infra:${C_RESET} $INFRA_DIR/" >&2

# ── Intent gathering phase ──
if [[ "$SKIP_INTENT" != "true" ]]; then
  INTENT_CTX=()
  [[ -f "$POC_REPO_DIR/INTENT.md" ]]          && INTENT_CTX+=(--context-file "$POC_REPO_DIR/INTENT.md")
  [[ -s "$POC_PROJECT_DIR/OBSERVATIONS.md" ]]  && INTENT_CTX+=(--context-file "$POC_PROJECT_DIR/OBSERVATIONS.md")
  [[ -s "$POC_PROJECT_DIR/ESCALATION.md" ]]    && INTENT_CTX+=(--context-file "$POC_PROJECT_DIR/ESCALATION.md")
  [[ -s "$POC_PROJECT_DIR/MEMORY.md" ]]        && INTENT_CTX+=(--context-file "$POC_PROJECT_DIR/MEMORY.md")
  [[ -s "$POC_OUTPUT_DIR/MEMORY.md" ]]         && INTENT_CTX+=(--context-file "$POC_OUTPUT_DIR/MEMORY.md")

  if "$SCRIPT_DIR/intent.sh" --cwd "$SESSION_WORKTREE" --stream-dir "$INFRA_DIR" \
      --task "$TASK" "${INTENT_CTX[@]}"; then
    # Prepend INTENT.md to the task so it governs downstream planning
    TASK="$(cat "$SESSION_WORKTREE/INTENT.md")

---

Original task: $TASK"
  else
    chrome_beep
    echo -e "  ${C_YELLOW}Intent skipped.${C_RESET} Continue without? (y/n)" >&2
    read -p "$(echo -e "${C_GREEN}[you]${C_RESET} > ")" cont </dev/tty
    [[ "$cont" == [nN] ]] && exit 0
  fi
fi

# ── Memory retrieval ──
MEMORY_CTX_FILE=$(mktemp /tmp/memory-ctx-XXXXXXXXXXXX)
trap "kill $TAIL_PID 2>/dev/null; rm -f $SETTINGS_FILE $MEMORY_CTX_FILE" EXIT
MEMORY_CTX=()
if python3 "$SCRIPT_DIR/scripts/memory_indexer.py" \
    --db "$POC_PROJECT_DIR/.memory.db" \
    --source "$POC_PROJECT_DIR/OBSERVATIONS.md" \
    --source "$POC_PROJECT_DIR/ESCALATION.md" \
    --source "$POC_PROJECT_DIR/MEMORY.md" \
    --source "$(dirname "$POC_PROJECT_DIR")/MEMORY.md" \
    --task "$TASK" \
    --output "$MEMORY_CTX_FILE" 2>/dev/null; then
  [[ -s "$MEMORY_CTX_FILE" ]] && MEMORY_CTX=(--context-file "$MEMORY_CTX_FILE")
fi

# Plan → Approve → Execute (same script used by relay.sh for subteams)
"$SCRIPT_DIR/plan-execute.sh" \
  --agents "$AGENTS_JSON" \
  --agent project-lead \
  --settings "$SETTINGS_FILE" \
  --cwd "$SESSION_WORKTREE" \
  --stream-dir "$INFRA_DIR" \
  --plan-turns 15 \
  --exec-turns 30 \
  ${MEMORY_CTX[@]+"${MEMORY_CTX[@]}"} \
  "$TASK"

# ── Session completion: commit + merge session branch into main ──
chrome_header "MERGE"

# Commit any uncommitted deliverables in the session worktree
# (files written directly by the uber team or merged from dispatch branches)
git -C "$SESSION_WORKTREE" add -A 2>/dev/null || true
if ! git -C "$SESSION_WORKTREE" diff --cached --quiet 2>/dev/null; then
  git -C "$SESSION_WORKTREE" commit -m "session deliverables: $PROJECT" 2>&1 || true
fi

git -C "$POC_REPO_DIR" merge --no-ff "$SESSION_BRANCH" \
  -m "session $SESSION_TS" 2>&1 || \
  git -C "$POC_REPO_DIR" merge -X theirs --no-ff "$SESSION_BRANCH" \
    -m "session $SESSION_TS (auto-resolved)" 2>&1 || \
  echo -e "  ${C_RED}Session merge failed — deliverables remain on branch $SESSION_BRANCH${C_RESET}" >&2

# Clean up worktree and branch
git -C "$POC_REPO_DIR" worktree remove "$SESSION_WORKTREE" 2>/dev/null || true
git -C "$POC_REPO_DIR" branch -d "$SESSION_BRANCH" 2>/dev/null || true

# ── Extract learnings ──
chrome_header "LEARNINGS"

# 1. Roll up dispatch MEMORYs → team MEMORY.md (for each team that ran)
"$SCRIPT_DIR/scripts/promote_learnings.sh" --scope team || true

# 2. Roll up team MEMORYs → session MEMORY.md (team-agnostic filter)
"$SCRIPT_DIR/scripts/promote_learnings.sh" --scope session || true

# 3. Roll up session MEMORY → project MEMORY.md
"$SCRIPT_DIR/scripts/promote_learnings.sh" --scope project || true

# 4. Roll up project MEMORY → global MEMORY.md (project-agnostic filter)
"$SCRIPT_DIR/scripts/promote_learnings.sh" --scope global || true

# ── Intent learning extraction ──

# 5. Observations from intent conversation
if [[ -f "$INFRA_DIR/.intent-stream.jsonl" ]]; then
  python3 "$SCRIPT_DIR/scripts/summarize_session.py" \
    --stream "$INFRA_DIR/.intent-stream.jsonl" \
    --output "$POC_PROJECT_DIR/OBSERVATIONS.md" \
    --scope observations || true

  python3 "$SCRIPT_DIR/scripts/summarize_session.py" \
    --stream "$INFRA_DIR/.intent-stream.jsonl" \
    --output "$POC_PROJECT_DIR/ESCALATION.md" \
    --scope escalation || true
fi

# 6. Observations from execution (corrections, autonomous decisions)
if [[ -f "$INFRA_DIR/.exec-stream.jsonl" ]]; then
  python3 "$SCRIPT_DIR/scripts/summarize_session.py" \
    --stream "$INFRA_DIR/.exec-stream.jsonl" \
    --output "$POC_PROJECT_DIR/OBSERVATIONS.md" \
    --scope observations || true

  python3 "$SCRIPT_DIR/scripts/summarize_session.py" \
    --stream "$INFRA_DIR/.exec-stream.jsonl" \
    --output "$POC_PROJECT_DIR/ESCALATION.md" \
    --scope escalation || true
fi

# 7. Intent-vs-outcome alignment (worktree is gone — use merged INTENT.md)
if [[ -f "$POC_REPO_DIR/INTENT.md" && -f "$INFRA_DIR/.exec-stream.jsonl" ]]; then
  python3 "$SCRIPT_DIR/scripts/summarize_session.py" \
    --stream "$INFRA_DIR/.exec-stream.jsonl" \
    --output "$POC_PROJECT_DIR/OBSERVATIONS.md" \
    --scope intent-alignment \
    --context "$POC_REPO_DIR/INTENT.md" || true
fi

# Stop the tail
kill "$TAIL_PID" 2>/dev/null || true
wait "$TAIL_PID" 2>/dev/null || true

# ── Final report ──
chrome_banner "Session Complete: $SESSION_TS" "Project: $PROJECT"
echo -e "  ${C_BOLD}Deliverables:${C_RESET}" >&2
git -C "$POC_REPO_DIR" ls-files 2>/dev/null | grep -v '^\.' | sort | sed 's/^/    /' >&2 || echo "    (none)" >&2
echo "" >&2
echo -e "  ${C_DIM}Project memory: $POC_PROJECT_DIR/MEMORY.md${C_RESET}" >&2
echo -e "  ${C_DIM}Global memory: $POC_OUTPUT_DIR/MEMORY.md${C_RESET}" >&2
chrome_heavy_line
chrome_beep
