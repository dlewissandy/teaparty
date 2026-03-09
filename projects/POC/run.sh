#!/usr/bin/env bash
# Hierarchical Agent Teams POC — Entry Point
#
# Usage: ./projects/POC/run.sh "Create a document about the solar system with diagrams"
#        ./projects/POC/run.sh --project tea-handbook "Add chapter 2 on oolong"
#        ./projects/POC/run.sh --project POC "Improve the stream filter"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/ui.sh"

# Parse arguments: optional --project override, --skip-intent, then positional task
PROJECT_OVERRIDE=""
SKIP_INTENT=""
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
export PROJECTS_DIR="$POC_ROOT"
mkdir -p "$PROJECTS_DIR"

if [[ -n "$PROJECT_OVERRIDE" ]]; then
  PROJECT="$PROJECT_OVERRIDE"
  # Still classify for mode — project override only skips slug classification
  CLASSIFY_OUT=$(python3 "$SCRIPT_DIR/scripts/classify_task.py" \
    --task "$TASK" \
    --projects-dir "$PROJECTS_DIR" 2>/dev/null) || CLASSIFY_OUT="default	workflow"
  TASK_MODE=$(printf '%s' "$CLASSIFY_OUT" | cut -f2)
  [[ "$TASK_MODE" =~ ^(workflow|conversational)$ ]] || TASK_MODE=workflow
else
  CLASSIFY_OUT=$(python3 "$SCRIPT_DIR/scripts/classify_task.py" \
    --task "$TASK" \
    --projects-dir "$PROJECTS_DIR" 2>/dev/null) || CLASSIFY_OUT="default	workflow"
  PROJECT=$(printf '%s' "$CLASSIFY_OUT" | cut -f1)
  TASK_MODE=$(printf '%s' "$CLASSIFY_OUT" | cut -f2)
  [[ "$TASK_MODE" =~ ^(workflow|conversational)$ ]] || TASK_MODE=workflow
fi
export POC_PROJECT="$PROJECT"
export POC_TASK_MODE="$TASK_MODE"
export POC_PROJECT_DIR="$PROJECTS_DIR/$PROJECT"

# ── Conversational — no workflow ──
if [[ "$TASK_MODE" == "conversational" ]]; then
  echo -e "  ${C_DIM}Conversational — responding directly, no workflow.${C_RESET}" >&2
  echo "$TASK" | claude -p \
    --model claude-sonnet-4-5 \
    --output-format text
  exit 0
fi

# ── SKIP_INTENT: driven by CLI flags only (proxy decides at runtime) ──
# --skip-intent / --with-intent override; otherwise empty = proxy decides
if [[ -z "$SKIP_INTENT" ]]; then
  SKIP_INTENT=""  # proxy will decide via INTENT_ASSERT gate
fi

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
INTENT.md
.memory.db
.proxy-confidence.json
.cfa-state.json
institutional.md
tasks/
proxy.md
proxy-tasks/
GITIGNORE
  cat > "$POC_PROJECT_DIR/CLAUDE.md" << CLAUDEMD
# Project: $PROJECT
CLAUDEMD
  git -C "$POC_PROJECT_DIR" add -A
  git -C "$POC_PROJECT_DIR" commit -m "init project $PROJECT"
  POC_REPO_DIR="$POC_PROJECT_DIR"
fi
export POC_REPO_DIR

# ── Compute relative path from repo root to project dir ──
# Linked-repo: e.g., "projects/POC". Standalone: "."
if [[ "$POC_REPO_DIR" != "$POC_PROJECT_DIR" ]]; then
  POC_RELATIVE_PATH=$(python3 -c "import os; print(os.path.relpath('$POC_PROJECT_DIR', '$POC_REPO_DIR'))")
else
  POC_RELATIVE_PATH="."
fi
export POC_RELATIVE_PATH

# ── Session setup with worktree ──
SESSION_TS=$(date +%Y%m%d-%H%M%S)
SESSION_BRANCH="session/$SESSION_TS"
SESSION_WORKTREE="$POC_PROJECT_DIR/.worktrees/session-$SESSION_TS"
INFRA_DIR="$POC_PROJECT_DIR/.sessions/$SESSION_TS"

# Create session worktree (branched from repo HEAD)
mkdir -p "$POC_PROJECT_DIR/.worktrees"
git -C "$POC_REPO_DIR" worktree add "$SESSION_WORKTREE" -b "$SESSION_BRANCH"

# Compute project working directory inside the worktree.
# Linked-repo: $SESSION_WORKTREE/projects/POC (agent CWD = project subdir)
# Standalone: $SESSION_WORKTREE (agent CWD = worktree root, same as before)
if [[ "$POC_RELATIVE_PATH" != "." ]]; then
  PROJECT_WORKDIR="$SESSION_WORKTREE/$POC_RELATIVE_PATH"
  mkdir -p "$PROJECT_WORKDIR"
else
  PROJECT_WORKDIR="$SESSION_WORKTREE"
fi
export POC_PROJECT_WORKDIR="$PROJECT_WORKDIR"

# Create infra dirs for each team
mkdir -p "$INFRA_DIR"/{art,writing,editorial,research,coding}

# Export for dispatch.sh and promote_learnings.sh
export POC_SESSION_WORKTREE="$SESSION_WORKTREE"
export POC_SESSION_DIR="$INFRA_DIR"
export POC_PREMORTEM_FILE="$INFRA_DIR/.premortem.md"
export POC_ASSUMPTIONS_FILE="$INFRA_DIR/.assumptions.jsonl"

# Memory store directories — typed stores (institutional.md + tasks/)
mkdir -p "$POC_OUTPUT_DIR/tasks"
mkdir -p "$POC_PROJECT_DIR/tasks"
mkdir -p "$POC_PROJECT_DIR/proxy-tasks"
# Legacy files: kept for backward compat (fallback when tasks/ is empty)
touch "$POC_PROJECT_DIR/OBSERVATIONS.md"
touch "$POC_PROJECT_DIR/ESCALATION.md"

# Shared conversation log — scoped to this session.
# Subteam output is indented via --filter-prefix in dispatch.sh.
export CONVERSATION_LOG="$INFRA_DIR/.conversation"
> "$CONVERSATION_LOG"

# Session chat log — human-readable record of all actor communications + state changes
export SESSION_LOG="$INFRA_DIR/session.log"
session_log SESSION "Started -- Project: $PROJECT | Task: ${TASK:0:200}"
session_log SESSION "Worktree: $SESSION_WORKTREE"
session_log SESSION "Project CWD: $PROJECT_WORKDIR"

# Stream conversation log to terminal (poll-based, no tail -f deadlock risk).
# tail -f blocks forever when the file stops being written — this caused
# repeated session stalls. Poll-based reader exits naturally when killed.
python3 -uc "
import sys, time, os, signal
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
with open(sys.argv[1]) as f:
    while True:
        chunk = f.read(8192)
        if chunk:
            sys.stdout.write(chunk)
            sys.stdout.flush()
        else:
            time.sleep(0.5)
" "$CONVERSATION_LOG" >&2 &
TAIL_PID=$!

# Substitute placeholders with absolute paths in agent definitions
AGENTS_JSON=$(sed -e "s|__POC_DIR__|$SCRIPT_DIR|g" \
                  -e "s|__SESSION_DIR__|$INFRA_DIR|g" \
  "$SCRIPT_DIR/agents/uber-team.json")

# Self-contained settings: pre-approve dispatch.sh
SETTINGS_FILE=$(mktemp)
trap "kill $TAIL_PID 2>/dev/null; rm -f $SETTINGS_FILE" EXIT

SCRIPT_DIR="$SCRIPT_DIR" python3 -c "
import json, os, sys
d = os.environ['SCRIPT_DIR']
rules = [
    'Bash(' + d + '/dispatch.sh:*)',
    'Bash(' + d + '/tools/yt-transcript.sh:*)',
    'WebFetch',
    'WebSearch',
    'Write',
    'Edit',
    'ExitPlanMode',
]
enforce_write_cmd = d + '/hooks/enforce-write-scope.sh'
json.dump({
    'permissions': {'allow': rules},
    'hooks': {
        'PreToolUse': [
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
        'PROJECTS_DIR': os.environ.get('PROJECTS_DIR', ''),
        'SCRIPT_DIR': d,
        'POC_OUTPUT_DIR': os.environ.get('POC_OUTPUT_DIR', ''),
        'POC_PROJECT': os.environ.get('POC_PROJECT', ''),
        'POC_PROJECT_DIR': os.environ.get('POC_PROJECT_DIR', ''),
        'POC_PROJECT_WORKDIR': os.environ.get('POC_PROJECT_WORKDIR', ''),
        'POC_RELATIVE_PATH': os.environ.get('POC_RELATIVE_PATH', ''),
        'POC_REPO_DIR': os.environ.get('POC_REPO_DIR', ''),
        'POC_SESSION_DIR': os.environ.get('POC_SESSION_DIR', ''),
        'POC_SESSION_WORKTREE': os.environ.get('POC_SESSION_WORKTREE', ''),
        'POC_TASK_MODE': os.environ.get('POC_TASK_MODE', 'workflow'),
        'POC_CFA_STATE': os.environ.get('POC_CFA_STATE', ''),
        'POC_PREMORTEM_FILE': os.environ.get('POC_PREMORTEM_FILE', ''),
        'POC_ASSUMPTIONS_FILE': os.environ.get('POC_ASSUMPTIONS_FILE', ''),
    }
}, sys.stdout)
" > "$SETTINGS_FILE"

# ── Startup banner ──
SUBTITLE="Project: $PROJECT  Session: $SESSION_TS"
[[ "$POC_REPO_DIR" != "$POC_PROJECT_DIR" ]] && SUBTITLE="$SUBTITLE  Repo: $POC_REPO_DIR"
chrome_banner "Hierarchical Agent Teams" "$SUBTITLE"
echo -e "  ${C_DIM}Task:${C_RESET} $TASK" >&2
echo -e "  ${C_DIM}Worktree:${C_RESET} $SESSION_WORKTREE" >&2
echo -e "  ${C_DIM}Project CWD:${C_RESET} $PROJECT_WORKDIR" >&2
echo -e "  ${C_DIM}Infra:${C_RESET} $INFRA_DIR/" >&2
echo -e "  ${C_DIM}Mode:${C_RESET} $TASK_MODE" >&2

# ── Memory retrieval (before intent for warm-start — spec Section 8.1) ──
MEMORY_CTX_FILE=$(mktemp /tmp/memory-ctx-XXXXXXXXXXXX)
INST_CTX_FILE=$(mktemp /tmp/inst-ctx-XXXXXXXXXXXX)
PROXY_CTX_FILE=$(mktemp /tmp/proxy-ctx-XXXXXXXXXXXX)
RETRIEVED_IDS_FILE=$(mktemp /tmp/retrieved-ids-XXXXXXXXXXXX)
trap "kill $TAIL_PID 2>/dev/null; rm -f $SETTINGS_FILE $MEMORY_CTX_FILE $INST_CTX_FILE $PROXY_CTX_FILE $RETRIEVED_IDS_FILE" EXIT

# 1. Always-load: institutional.md at global + project level (no retrieval gate)
{
  _GLOBAL_INST="$(dirname "$POC_PROJECT_DIR")/institutional.md"
  if [[ -f "$_GLOBAL_INST" && -s "$_GLOBAL_INST" ]]; then
    echo "--- global institutional ---"; cat "$_GLOBAL_INST"; echo "--- end ---"; echo ""
  fi
  if [[ -f "$POC_PROJECT_DIR/institutional.md" && -s "$POC_PROJECT_DIR/institutional.md" ]]; then
    echo "--- project institutional ---"; cat "$POC_PROJECT_DIR/institutional.md"; echo "--- end ---"; echo ""
  fi
} > "$INST_CTX_FILE"

# 2. Always-load: proxy.md (human preferential); fall back to OBSERVATIONS.md
if [[ -f "$POC_PROJECT_DIR/proxy.md" && -s "$POC_PROJECT_DIR/proxy.md" ]]; then
  cat "$POC_PROJECT_DIR/proxy.md" > "$PROXY_CTX_FILE"
elif [[ -s "$POC_PROJECT_DIR/OBSERVATIONS.md" ]]; then
  cat "$POC_PROJECT_DIR/OBSERVATIONS.md" > "$PROXY_CTX_FILE"
fi

# 3. Fuzzy retrieval: tasks/ + proxy-tasks/ directories
TASK_SOURCES=()
[[ -d "$POC_PROJECT_DIR/tasks" ]] && TASK_SOURCES+=(--source "$POC_PROJECT_DIR/tasks")
[[ -d "$(dirname "$POC_PROJECT_DIR")/tasks" ]] && TASK_SOURCES+=(--source "$(dirname "$POC_PROJECT_DIR")/tasks")
[[ -d "$POC_PROJECT_DIR/proxy-tasks" ]] && TASK_SOURCES+=(--source "$POC_PROJECT_DIR/proxy-tasks")
# Backward compat: fallback to legacy MEMORY.md / OBSERVATIONS.md when tasks/ is empty
if [[ ${#TASK_SOURCES[@]} -eq 0 ]]; then
  [[ -s "$POC_PROJECT_DIR/MEMORY.md" ]] && TASK_SOURCES+=(--source "$POC_PROJECT_DIR/MEMORY.md")
  [[ -s "$(dirname "$POC_PROJECT_DIR")/MEMORY.md" ]] && TASK_SOURCES+=(--source "$(dirname "$POC_PROJECT_DIR")/MEMORY.md")
  [[ -s "$POC_PROJECT_DIR/OBSERVATIONS.md" ]] && TASK_SOURCES+=(--source "$POC_PROJECT_DIR/OBSERVATIONS.md")
  [[ -s "$POC_PROJECT_DIR/ESCALATION.md" ]] && TASK_SOURCES+=(--source "$POC_PROJECT_DIR/ESCALATION.md")
fi
if [[ ${#TASK_SOURCES[@]} -gt 0 ]]; then
  python3 "$SCRIPT_DIR/scripts/memory_indexer.py" \
    --db "$POC_PROJECT_DIR/.memory.db" \
    "${TASK_SOURCES[@]}" \
    --scope-base-dir "$POC_PROJECT_DIR" \
    --task "$TASK" \
    --top-k 10 \
    --output "$MEMORY_CTX_FILE" \
    --retrieved-ids "$RETRIEVED_IDS_FILE" 2>/dev/null || true
fi

# Combined context: institutional (always) + proxy (always) + tasks (fuzzy)
MEMORY_CTX=()
[[ -s "$INST_CTX_FILE" ]] && MEMORY_CTX+=(--context-file "$INST_CTX_FILE")
[[ -s "$PROXY_CTX_FILE" ]] && MEMORY_CTX+=(--context-file "$PROXY_CTX_FILE")
[[ -s "$MEMORY_CTX_FILE" ]] && MEMORY_CTX+=(--context-file "$MEMORY_CTX_FILE")

# ── CfA State Machine: Plan → Execute with backtracking ──
# Implements the Agentic CfA framework: three-phase state machine with
# cross-phase backtracking loops. Exit codes from plan-execute.sh:
#   0 = success (COMPLETED_WORK)
#   1 = failure/rejection (WITHDRAWN)
#   2 = backtrack to intent (INTENT_RESPONSE re-entry)
#   3 = backtrack to planning (PLANNING_RESPONSE re-entry)
#   4 = infrastructure failure (process crash/timeout/error)
CFA_STATE_FILE="$INFRA_DIR/.cfa-state.json"
PROXY_MODEL="$POC_PROJECT_DIR/.proxy-confidence.json"
BACKTRACK_FEEDBACK_FILE="$INFRA_DIR/.backtrack-feedback.txt"
ORIGINAL_TASK="$TASK"
BACKTRACK_COUNT=0

# Initialize root CfA state and export for child processes (dispatch.sh dispatches)
python3 "$SCRIPT_DIR/scripts/cfa_state.py" --init \
  --task-id "session-$(basename "$INFRA_DIR")" \
  --output "$CFA_STATE_FILE" 2>/dev/null || true
export POC_CFA_STATE="$CFA_STATE_FILE"

# CfA state helpers and approval gate helpers are in ui.sh

# ── Intent gathering phase (CfA Phase 1: INTENT_ASSERT proxy gate) ──
# Remove any stale INTENT.md inherited from git or a prior session's worktree.
# A fresh intent phase must start from scratch; the agent writes a new INTENT.md.
rm -f "$PROJECT_WORKDIR/INTENT.md"

INTENT_APPROVED=false
if [[ "$SKIP_INTENT" == "true" ]]; then
  # CLI override: --skip-intent forces skip
  echo -e "  ${C_DIM}Intent skipped (--skip-intent).${C_RESET}" >&2
  session_log STATE "Intent skipped (--skip-intent)"
  cfa_set "INTENT"
else
  # Proxy decides whether to run intent gathering
  INTENT_PROXY=$(proxy_decide "INTENT_ASSERT")
  session_log PROXY "INTENT_ASSERT $INTENT_PROXY"
  if [[ "$INTENT_PROXY" == "auto-approve" ]]; then
    echo -e "  ${C_DIM}Human proxy: auto-approved intent (high confidence)${C_RESET}" >&2
    proxy_record "INTENT_ASSERT" "approve"
    session_log STATE "INTENT_ASSERT -> approve -> INTENT (proxy auto-approved)"
    cfa_set "INTENT"  # Proxy auto-approved — skip intent gathering entirely
  else
    # Run intent.sh — human reviews
    chrome_header "INTENT (CfA Phase 1)"
    INTENT_CTX=()
    # Intent context: proxy (always-load) + escalation fallback + fuzzy-retrieved tasks
    [[ -s "$PROXY_CTX_FILE" ]]                   && INTENT_CTX+=(--context-file "$PROXY_CTX_FILE")
    [[ -s "$POC_PROJECT_DIR/ESCALATION.md" ]]    && INTENT_CTX+=(--context-file "$POC_PROJECT_DIR/ESCALATION.md")
    [[ -s "$MEMORY_CTX_FILE" ]]                  && INTENT_CTX+=(--context-file "$MEMORY_CTX_FILE")

    if "$SCRIPT_DIR/intent.sh" --cwd "$PROJECT_WORKDIR" --stream-dir "$INFRA_DIR" \
        --project-dir "$POC_PROJECT_DIR" --task "$TASK" \
        --proxy-model "$PROXY_MODEL" "${INTENT_CTX[@]}"; then
      INTENT_APPROVED=true
      session_log STATE "INTENT_ASSERT -> approve -> INTENT"
      # intent.sh records proxy outcomes internally — no proxy_record here
      # Phase 2: Archive INTENT.md to infra dir immediately
      if [[ -f "$PROJECT_WORKDIR/INTENT.md" ]]; then
        cp "$PROJECT_WORKDIR/INTENT.md" "$INFRA_DIR/INTENT.md"
        rm "$PROJECT_WORKDIR/INTENT.md"
      fi
      cfa_set "INTENT"

      # Prepend INTENT.md to the task so it governs downstream planning
      TASK="$(cat "$INFRA_DIR/INTENT.md")

---

Original task: $TASK"

      # Extract intent learnings immediately after approval (background)
      INTENT_EXTRACT_PIDS=()
      if [[ -f "$INFRA_DIR/.intent-stream.jsonl" ]]; then
        # observations → proxy.md (always-loaded human preferential context)
        python3 "$SCRIPT_DIR/scripts/summarize_session.py" \
          --stream "$INFRA_DIR/.intent-stream.jsonl" \
          --output "$POC_PROJECT_DIR/proxy.md" \
          --scope observations 2>/dev/null &
        INTENT_EXTRACT_PIDS+=($!)
        # escalation → proxy-tasks/ (fuzzy-retrieved domain-indexed thresholds)
        _ESC_TS=$(date +%Y%m%d-%H%M%S)
        mkdir -p "$POC_PROJECT_DIR/proxy-tasks"
        python3 "$SCRIPT_DIR/scripts/summarize_session.py" \
          --stream "$INFRA_DIR/.intent-stream.jsonl" \
          --output "$POC_PROJECT_DIR/proxy-tasks/${_ESC_TS}-intent.md" \
          --scope escalation 2>/dev/null &
        INTENT_EXTRACT_PIDS+=($!)
      fi
    else
      # intent.sh records proxy outcomes internally — no proxy_record here
      cfa_set "WITHDRAWN"
      session_log STATE "WITHDRAWN (intent failed)"
      chrome_beep
      echo -e "  ${C_RED}Intent failed — session cannot proceed without approved intent.${C_RESET}" >&2
      exit 1
    fi
  fi
fi

# ── Stage detection and retirement ──
if [[ "$INTENT_APPROVED" == "true" && -f "$INFRA_DIR/INTENT.md" ]]; then
  # Read old stage BEFORE detect_stage.py overwrites .current-stage
  OLD_STAGE=""
  [[ -f "$POC_PROJECT_DIR/.current-stage" ]] && OLD_STAGE="$(head -1 "$POC_PROJECT_DIR/.current-stage" | tr -d '[:space:]')" || true

  # Detect new stage; prints "STAGE_CHANGED" to stdout on transition
  STAGE_STATUS="$(python3 "$SCRIPT_DIR/scripts/detect_stage.py" \
    --intent "$INFRA_DIR/INTENT.md" \
    --stage-file "$POC_PROJECT_DIR/.current-stage" 2>/dev/null)" || STAGE_STATUS=""

  # Retire task-domain entries from the old stage if a transition occurred
  if [[ "$STAGE_STATUS" == "STAGE_CHANGED" && -n "$OLD_STAGE" && "$OLD_STAGE" != "unknown" ]]; then
    python3 "$SCRIPT_DIR/scripts/retire_stage.py" \
      --old-stage "$OLD_STAGE" \
      --memory "$POC_PROJECT_DIR/MEMORY.md" 2>/dev/null || true
    NEW_STAGE="$(head -1 "$POC_PROJECT_DIR/.current-stage" 2>/dev/null | tr -d '[:space:]')" || NEW_STAGE=""
    echo -e "  ${C_YELLOW}Stage transition: ${OLD_STAGE} → ${NEW_STAGE}${C_RESET}" >&2
  fi
fi

# ── Confidence posture ──
chrome_header "CONFIDENCE POSTURE"
POSTURE_CTX=""
[[ -s "$INST_CTX_FILE" ]] && POSTURE_CTX=$(cat "$INST_CTX_FILE")
[[ -s "$MEMORY_CTX_FILE" ]] && POSTURE_CTX="$POSTURE_CTX
$(cat "$MEMORY_CTX_FILE")"
[[ -s "$POC_PROJECT_DIR/ESCALATION.md" ]] && POSTURE_CTX="$POSTURE_CTX
$(head -c 2000 "$POC_PROJECT_DIR/ESCALATION.md")"

CONFIDENCE_POSTURE=$(python3 "$SCRIPT_DIR/scripts/generate_confidence_posture.py" \
  --task "$TASK" \
  --context "$POSTURE_CTX" 2>/dev/null) || true

if [[ -n "$CONFIDENCE_POSTURE" ]]; then
  echo "$CONFIDENCE_POSTURE" >&2
  # Skip injection when all dimensions are HIGH (zero information content — spec)
  NON_HIGH_COUNT=$(echo "$CONFIDENCE_POSTURE" | grep -ciE ':\s*(moderate|low)' || true)
  if [[ "$NON_HIGH_COUNT" -gt 0 ]]; then
    TASK="$CONFIDENCE_POSTURE

---

$TASK"
  else
    echo -e "  ${C_DIM}All-HIGH posture — skipping injection (no information content).${C_RESET}" >&2
  fi
fi

# ── Pre-mortem ──
chrome_header "PRE-MORTEM"
python3 "$SCRIPT_DIR/scripts/run_premortem.py" \
  --task "$TASK" \
  --output "$POC_PREMORTEM_FILE" \
  ${MEMORY_CTX[@]:+--context-file "$MEMORY_CTX_FILE"} 2>/dev/null || true

if [[ -s "$POC_PREMORTEM_FILE" ]]; then
  echo -e "  ${C_DIM}Pre-mortem risks identified — injecting as context.${C_RESET}" >&2
  cat "$POC_PREMORTEM_FILE" >&2
  MEMORY_CTX=(--context-file "$POC_PREMORTEM_FILE" ${MEMORY_CTX[@]+"${MEMORY_CTX[@]}"})
fi

# ── Resolve cross-project paths in task text ──
# Tasks may reference files in other projects (e.g., hierarchical-agent-memory/01-spec.md).
# The agent works in a worktree that only contains the current project's git-tracked files.
# Resolve relative project paths to absolute paths so the agent can read them.
# Matches paths like slug/file.md whether quoted, backticked, or bare (after whitespace).
TASK=$(python3 -c "
import re, os, sys
task = sys.stdin.read()
projects_dir = sys.argv[1]

# Build set of known project slugs for targeted matching
slugs = set()
for entry in os.listdir(projects_dir):
    if os.path.isdir(os.path.join(projects_dir, entry)) and not entry.startswith('.'):
        slugs.add(entry)

def resolve(m):
    path = m.group('path')
    # Strip common prefixes: projects/, poc/projects/
    for prefix in ['poc/projects/', 'projects/']:
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    candidate = os.path.join(projects_dir, path)
    if os.path.isfile(candidate):
        return m.group(0).replace(m.group('path'), candidate)
    return m.group(0)

# Match paths starting with a known project slug, with any common file extension
slug_pattern = '|'.join(re.escape(s) for s in slugs)
if slug_pattern:
    pattern = r'(?P<path>(?:(?:poc/)?projects/)?(?:' + slug_pattern + r')/[a-zA-Z0-9_./-]+\.(?:md|py|sh|txt|yaml|json))'
    task = re.sub(pattern, resolve, task)
print(task, end='')
" "$PROJECTS_DIR" <<< "$TASK")

# ── CfA backtracking loop — plan → approve → execute → (backtrack?) ──
export POC_STALL_TIMEOUT=1800

PLAN_SESSION_ID=""
SKIP_PLANNING=false

while true; do
    if [[ "$SKIP_PLANNING" != "true" ]]; then
    # ── Planning phase (CfA Phase 2: DRAFT → PLAN_ASSERT → PLAN) ──
    chrome_header "PLAN (CfA Phase 2)"
    [[ $BACKTRACK_COUNT -gt 0 ]] && echo -e "  ${C_YELLOW}Backtrack #${BACKTRACK_COUNT}${C_RESET}" >&2

    PLAN_EXIT=0
    "$SCRIPT_DIR/plan-execute.sh" \
      --agents "$AGENTS_JSON" \
      --agent project-lead \
      --settings "$SETTINGS_FILE" \
      --cwd "$PROJECT_WORKDIR" \
      --add-dir "$SESSION_WORKTREE" \
      --add-dir "$PROJECTS_DIR" \
      --stream-dir "$INFRA_DIR" \
      --proxy-model "$PROXY_MODEL" \
      --cfa-state "$CFA_STATE_FILE" \
      --plan-only \
      ${MEMORY_CTX[@]+"${MEMORY_CTX[@]}"} \
      "$TASK" || PLAN_EXIT=$?

    if [[ $PLAN_EXIT -eq 2 ]]; then
      # Backtrack to intent — re-enter intent alignment with feedback
      ((BACKTRACK_COUNT++))
      echo -e "  ${C_YELLOW}Backtracking to intent alignment (backtrack #$BACKTRACK_COUNT)...${C_RESET}" >&2
      session_log STATE "Backtrack to intent (#$BACKTRACK_COUNT)"

      BACKTRACK_CTX=""
      [[ -f "$BACKTRACK_FEEDBACK_FILE" ]] && BACKTRACK_CTX=$(cat "$BACKTRACK_FEEDBACK_FILE")

      INTENT_CTX=()
      [[ -s "$PROXY_CTX_FILE" ]]                  && INTENT_CTX+=(--context-file "$PROXY_CTX_FILE")
      [[ -s "$POC_PROJECT_DIR/ESCALATION.md" ]]   && INTENT_CTX+=(--context-file "$POC_PROJECT_DIR/ESCALATION.md")
      [[ -s "$MEMORY_CTX_FILE" ]]                 && INTENT_CTX+=(--context-file "$MEMORY_CTX_FILE")

      if "$SCRIPT_DIR/intent.sh" --cwd "$PROJECT_WORKDIR" --stream-dir "$INFRA_DIR" \
          --project-dir "$POC_PROJECT_DIR" --task "$ORIGINAL_TASK" \
          --proxy-model "$PROXY_MODEL" \
          --backtrack-context "$BACKTRACK_CTX" "${INTENT_CTX[@]}"; then
        if [[ -f "$PROJECT_WORKDIR/INTENT.md" ]]; then
          cp "$PROJECT_WORKDIR/INTENT.md" "$INFRA_DIR/INTENT.md"
          rm "$PROJECT_WORKDIR/INTENT.md"
        fi
        TASK="$(cat "$INFRA_DIR/INTENT.md")

---

Original task: $ORIGINAL_TASK"
      fi
      continue  # Re-enter planning loop
    elif [[ $PLAN_EXIT -eq 4 ]]; then
      # Infrastructure failure during planning — retry the planning phase
      ((BACKTRACK_COUNT++))
      echo -e "  ${C_YELLOW}Planning failed (infrastructure) — retrying (attempt #$BACKTRACK_COUNT)...${C_RESET}" >&2
      session_log STATE "Planning infrastructure failure — retry #$BACKTRACK_COUNT"
      continue
    elif [[ $PLAN_EXIT -eq 1 ]]; then
      echo -e "  ${C_YELLOW}Plan rejected — session ending.${C_RESET}" >&2
      session_log STATE "Plan rejected -- session ending"
      break
    fi

    # Extract plan session ID for execute --resume
    [[ -f "$INFRA_DIR/.plan-session-id" ]] && PLAN_SESSION_ID=$(cat "$INFRA_DIR/.plan-session-id")
    fi  # end SKIP_PLANNING guard
    SKIP_PLANNING=false

    # ── Execution phase (CfA Phase 3: PLAN → TASK → COMPLETED_WORK) ──
    chrome_header "EXECUTE (CfA Phase 3)"
    EXEC_EXIT=0
    "$SCRIPT_DIR/plan-execute.sh" \
      --agents "$AGENTS_JSON" \
      --agent project-lead \
      --settings "$SETTINGS_FILE" \
      --cwd "$PROJECT_WORKDIR" \
      --add-dir "$SESSION_WORKTREE" \
      --add-dir "$PROJECTS_DIR" \
      --stream-dir "$INFRA_DIR" \
      --proxy-model "$PROXY_MODEL" \
      --cfa-state "$CFA_STATE_FILE" \
      --execute-only \
      ${PLAN_SESSION_ID:+--resume-session "$PLAN_SESSION_ID"} \
      ${MEMORY_CTX[@]+"${MEMORY_CTX[@]}"} \
      "$TASK" || EXEC_EXIT=$?

    if [[ $EXEC_EXIT -eq 2 ]]; then
      # Backtrack to intent — re-enter intent alignment with feedback
      ((BACKTRACK_COUNT++))
      echo -e "  ${C_YELLOW}Execution backtracking to intent (backtrack #$BACKTRACK_COUNT)...${C_RESET}" >&2
      session_log STATE "Exec backtrack to intent (#$BACKTRACK_COUNT)"

      BACKTRACK_CTX=""
      [[ -f "$BACKTRACK_FEEDBACK_FILE" ]] && BACKTRACK_CTX=$(cat "$BACKTRACK_FEEDBACK_FILE")

      INTENT_CTX=()
      [[ -s "$PROXY_CTX_FILE" ]]                  && INTENT_CTX+=(--context-file "$PROXY_CTX_FILE")
      [[ -s "$POC_PROJECT_DIR/ESCALATION.md" ]]   && INTENT_CTX+=(--context-file "$POC_PROJECT_DIR/ESCALATION.md")
      [[ -s "$MEMORY_CTX_FILE" ]]                 && INTENT_CTX+=(--context-file "$MEMORY_CTX_FILE")

      if "$SCRIPT_DIR/intent.sh" --cwd "$PROJECT_WORKDIR" --stream-dir "$INFRA_DIR" \
          --project-dir "$POC_PROJECT_DIR" --task "$ORIGINAL_TASK" \
          --proxy-model "$PROXY_MODEL" \
          --backtrack-context "$BACKTRACK_CTX" "${INTENT_CTX[@]}"; then
        if [[ -f "$PROJECT_WORKDIR/INTENT.md" ]]; then
          cp "$PROJECT_WORKDIR/INTENT.md" "$INFRA_DIR/INTENT.md"
          rm "$PROJECT_WORKDIR/INTENT.md"
        fi
        TASK="$(cat "$INFRA_DIR/INTENT.md")

---

Original task: $ORIGINAL_TASK"
      else
        cfa_set "WITHDRAWN"
        session_log STATE "WITHDRAWN (intent failed during backtrack)"
        echo -e "  ${C_RED}Intent failed during backtrack — session ending.${C_RESET}" >&2
        break
      fi
      continue  # Re-enter planning with updated intent
    elif [[ $EXEC_EXIT -eq 3 ]]; then
      # Backtrack to planning
      ((BACKTRACK_COUNT++))
      echo -e "  ${C_YELLOW}Execution backtracking to planning (backtrack #$BACKTRACK_COUNT)...${C_RESET}" >&2
      session_log STATE "Exec backtrack to planning (#$BACKTRACK_COUNT)"
      continue  # Re-enter planning loop (skip intent)
    elif [[ $EXEC_EXIT -eq 4 ]]; then
      # Infrastructure failure during execution — retry execution with same plan
      ((BACKTRACK_COUNT++))
      echo -e "  ${C_YELLOW}Execution failed (infrastructure) — retrying (attempt #$BACKTRACK_COUNT)...${C_RESET}" >&2
      session_log STATE "Execution infrastructure failure — retry #$BACKTRACK_COUNT"
      SKIP_PLANNING=true  # Re-enter the loop but skip planning (go straight to execute)
      continue
    fi

    break  # COMPLETED_WORK — exit CfA loop
  done

# ── Session completion: commit + squash-merge session branch into main ──
chrome_header "MERGE"

# Commit any uncommitted deliverables in the session worktree
# (files written directly by the uber team or merged from dispatch branches)
COMMIT_SUBJECT="${TASK:0:72}"
git -C "$SESSION_WORKTREE" add -A 2>/dev/null || true
if ! git -C "$SESSION_WORKTREE" diff --cached --quiet 2>/dev/null; then
  git -C "$SESSION_WORKTREE" commit -m "$COMMIT_SUBJECT" 2>&1 || true
fi

# Collect session commit log before squashing (for the commit body)
SESSION_COMMITS=$(git -C "$POC_REPO_DIR" log --format='- %s' HEAD.."$SESSION_BRANCH" 2>/dev/null || true)

# Squash-merge session branch into main
if ! git -C "$POC_REPO_DIR" merge --squash "$SESSION_BRANCH" 2>&1; then
  echo -e "  ${C_YELLOW}Merge conflict — retrying with -X theirs...${C_RESET}" >&2
  git -C "$POC_REPO_DIR" reset --hard HEAD 2>/dev/null || true
  git -C "$POC_REPO_DIR" merge --squash -X theirs "$SESSION_BRANCH" 2>&1 || \
    echo -e "  ${C_RED}Session merge failed — deliverables remain on branch $SESSION_BRANCH${C_RESET}" >&2
fi

# Commit squashed changes with a structured message
SESSION_DELIVERABLES=""
if ! git -C "$POC_REPO_DIR" diff --cached --quiet 2>/dev/null; then
  SESSION_DELIVERABLES=$(git -C "$POC_REPO_DIR" diff --cached --name-only 2>/dev/null | sort)
  SQUASH_MSG_FILE=$(mktemp)
  {
    echo "$PROJECT: ${TASK:0:72}"
    echo ""
    if [[ -n "$SESSION_COMMITS" ]]; then
      echo "Squashed commits:"
      echo "$SESSION_COMMITS"
      echo ""
    fi
    echo "Files changed:"
    echo "$SESSION_DELIVERABLES" | sed 's/^/- /'
  } > "$SQUASH_MSG_FILE"
  git -C "$POC_REPO_DIR" commit -F "$SQUASH_MSG_FILE" 2>&1 || true
  rm -f "$SQUASH_MSG_FILE"
else
  echo -e "  ${C_DIM}No changes to merge from session${C_RESET}" >&2
fi

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
# Intent observations/escalation extracted immediately after approval (see above — spec Section 5.3).
# Wait ONLY for those specific background jobs — bare `wait` would deadlock on the tail process.
for pid in "${INTENT_EXTRACT_PIDS[@]+"${INTENT_EXTRACT_PIDS[@]}"}"; do
  wait "$pid" 2>/dev/null || true
done

# 6. Observations/escalation from execution → proxy typed stores
if [[ -f "$INFRA_DIR/.exec-stream.jsonl" ]]; then
  # observations → proxy.md (always-loaded human preferential context)
  python3 "$SCRIPT_DIR/scripts/summarize_session.py" \
    --stream "$INFRA_DIR/.exec-stream.jsonl" \
    --output "$POC_PROJECT_DIR/proxy.md" \
    --scope observations || true

  # escalation → proxy-tasks/ (fuzzy-retrieved domain thresholds)
  _ESC_TS=$(date +%Y%m%d-%H%M%S)
  mkdir -p "$POC_PROJECT_DIR/proxy-tasks"
  python3 "$SCRIPT_DIR/scripts/summarize_session.py" \
    --stream "$INFRA_DIR/.exec-stream.jsonl" \
    --output "$POC_PROJECT_DIR/proxy-tasks/${_ESC_TS}-exec.md" \
    --scope escalation || true
fi

# 7. Intent-vs-outcome alignment → project/tasks/ (procedural alignment patterns)
if [[ -f "$INFRA_DIR/INTENT.md" && -f "$INFRA_DIR/.exec-stream.jsonl" ]]; then
  _IA_TS=$(date +%Y%m%d-%H%M%S)
  mkdir -p "$POC_PROJECT_DIR/tasks"
  python3 "$SCRIPT_DIR/scripts/summarize_session.py" \
    --stream "$INFRA_DIR/.exec-stream.jsonl" \
    --output "$POC_PROJECT_DIR/tasks/${_IA_TS}-alignment.md" \
    --scope intent-alignment \
    --context "$INFRA_DIR/INTENT.md" || true
fi

# 8. Prospective learnings (pre-mortem + execution)
"$SCRIPT_DIR/scripts/promote_learnings.sh" --scope prospective || true

# 9. In-flight learnings (milestone checkpoints)
"$SCRIPT_DIR/scripts/promote_learnings.sh" --scope in-flight || true

# 10. Corrective learnings (error events in exec stream)
"$SCRIPT_DIR/scripts/promote_learnings.sh" --scope corrective || true

# 11. Phase 5: Reinforce memory entries that were retrieved and used this session
if [[ -s "$RETRIEVED_IDS_FILE" ]]; then
  REINFORCE_ARGS=()
  for _rtasks_dir in "$POC_PROJECT_DIR/tasks" "$(dirname "$POC_PROJECT_DIR")/tasks" "$POC_PROJECT_DIR/proxy-tasks"; do
    if [[ -d "$_rtasks_dir" ]]; then
      for _rf in "$_rtasks_dir"/*.md; do
        [[ -s "$_rf" ]] && REINFORCE_ARGS+=(--memory "$_rf")
      done 2>/dev/null
    fi
  done
  # Backward compat: also reinforce legacy MEMORY.md files if present
  [[ -s "$POC_PROJECT_DIR/MEMORY.md" ]] && REINFORCE_ARGS+=(--memory "$POC_PROJECT_DIR/MEMORY.md")
  [[ -s "$(dirname "$POC_PROJECT_DIR")/MEMORY.md" ]] && REINFORCE_ARGS+=(--memory "$(dirname "$POC_PROJECT_DIR")/MEMORY.md")
  if [[ ${#REINFORCE_ARGS[@]} -gt 0 ]]; then
    python3 "$SCRIPT_DIR/scripts/track_reinforcement.py" \
      --ids-file "$RETRIEVED_IDS_FILE" \
      "${REINFORCE_ARGS[@]}" 2>/dev/null || true
  fi
fi

# Stop the tail
kill "$TAIL_PID" 2>/dev/null || true
wait "$TAIL_PID" 2>/dev/null || true

# ── Final report ──
chrome_banner "Session Complete: $SESSION_TS" "Project: $PROJECT"
echo -e "  ${C_BOLD}Deliverables:${C_RESET}" >&2
if [[ -n "${SESSION_DELIVERABLES:-}" ]]; then
  echo "$SESSION_DELIVERABLES" | sed 's/^/    /' >&2
else
  echo "    (no changes this session)" >&2
fi
echo "" >&2
echo -e "  ${C_DIM}Project memory: $POC_PROJECT_DIR/institutional.md (+ tasks/)${C_RESET}" >&2
echo -e "  ${C_DIM}Global memory: $POC_OUTPUT_DIR/institutional.md (+ tasks/)${C_RESET}" >&2
chrome_heavy_line
chrome_beep
session_log SESSION "Ended -- Deliverables: ${SESSION_DELIVERABLES:-none}"
