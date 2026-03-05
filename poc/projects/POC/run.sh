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
export PROJECTS_DIR="$POC_ROOT/projects"
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
    --max-turns 1 \
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
export POC_PREMORTEM_FILE="$INFRA_DIR/.premortem.md"
export POC_ASSUMPTIONS_FILE="$INFRA_DIR/.assumptions.jsonl"

# Memory files — global persists across all projects, project persists across sessions
touch "$POC_OUTPUT_DIR/MEMORY.md"
touch "$POC_PROJECT_DIR/MEMORY.md"
touch "$POC_PROJECT_DIR/OBSERVATIONS.md"
touch "$POC_PROJECT_DIR/ESCALATION.md"

# Shared conversation log — scoped to this session.
# Subteam output is indented via --filter-prefix in relay.sh.
export CONVERSATION_LOG="$INFRA_DIR/.conversation"
> "$CONVERSATION_LOG"

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
    'env': {
        'PROJECTS_DIR': os.environ.get('PROJECTS_DIR', ''),
        'SCRIPT_DIR': d,
        'POC_OUTPUT_DIR': os.environ.get('POC_OUTPUT_DIR', ''),
        'POC_PROJECT': os.environ.get('POC_PROJECT', ''),
        'POC_PROJECT_DIR': os.environ.get('POC_PROJECT_DIR', ''),
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
echo -e "  ${C_DIM}Infra:${C_RESET} $INFRA_DIR/" >&2
echo -e "  ${C_DIM}Mode:${C_RESET} $TASK_MODE" >&2

# ── Memory retrieval (before intent for warm-start — spec Section 8.1) ──
MEMORY_CTX_FILE=$(mktemp /tmp/memory-ctx-XXXXXXXXXXXX)
RETRIEVED_IDS_FILE=$(mktemp /tmp/retrieved-ids-XXXXXXXXXXXX)  # Phase 5
trap "kill $TAIL_PID 2>/dev/null; rm -f $SETTINGS_FILE $MEMORY_CTX_FILE $RETRIEVED_IDS_FILE" EXIT
MEMORY_CTX=()
if python3 "$SCRIPT_DIR/scripts/memory_indexer.py" \
    --db "$POC_PROJECT_DIR/.memory.db" \
    --source "$POC_PROJECT_DIR/OBSERVATIONS.md" \
    --source "$POC_PROJECT_DIR/ESCALATION.md" \
    --source "$POC_PROJECT_DIR/MEMORY.md" \
    --source "$(dirname "$POC_PROJECT_DIR")/MEMORY.md" \
    --task "$TASK" \
    --top-k 10 \
    --output "$MEMORY_CTX_FILE" \
    --retrieved-ids "$RETRIEVED_IDS_FILE" 2>/dev/null; then
  [[ -s "$MEMORY_CTX_FILE" ]] && MEMORY_CTX=(--context-file "$MEMORY_CTX_FILE")
fi

# ── CfA State Machine: Plan → Execute with backtracking ──
# Implements the Agentic CfA framework: three-phase state machine with
# cross-phase backtracking loops. Exit codes from plan-execute.sh:
#   0 = success (COMPLETED_WORK)
#   1 = failure/rejection (WITHDRAWN)
#   2 = backtrack to intent (INTENT_RESPONSE re-entry)
#   3 = backtrack to planning (PLANNING_RESPONSE re-entry)
CFA_STATE_FILE="$INFRA_DIR/.cfa-state.json"
PROXY_MODEL="$POC_PROJECT_DIR/.proxy-confidence.json"
BACKTRACK_FEEDBACK_FILE="$INFRA_DIR/.backtrack-feedback.txt"
ORIGINAL_TASK="$TASK"
BACKTRACK_COUNT=0

# Initialize root CfA state and export for child processes (relay.sh dispatches)
python3 "$SCRIPT_DIR/scripts/cfa_state.py" --init \
  --task-id "session-$(basename "$INFRA_DIR")" \
  --output "$CFA_STATE_FILE" 2>/dev/null || true
export POC_CFA_STATE="$CFA_STATE_FILE"

# CfA state helpers (mirrors plan-execute.sh)
cfa_transition() {
  local action="$1"
  if [[ -n "$CFA_STATE_FILE" && -f "$CFA_STATE_FILE" ]]; then
    if ! python3 "$SCRIPT_DIR/scripts/cfa_state.py" --transition \
        --state-file "$CFA_STATE_FILE" --action "$action" 2>/dev/null; then
      return 1
    fi
  fi
}

cfa_set() {
  if [[ -n "$CFA_STATE_FILE" && -f "$CFA_STATE_FILE" ]]; then
    python3 "$SCRIPT_DIR/scripts/cfa_state.py" --set-state \
      --state-file "$CFA_STATE_FILE" --target "$1" 2>/dev/null || true
  fi
}

# Human proxy helpers (mirrors plan-execute.sh proxy_decide/proxy_record)
proxy_decide() {
  local state="$1"
  local task_type="${2:-default}"
  if [[ -n "$PROXY_MODEL" ]]; then
    python3 "$SCRIPT_DIR/scripts/human_proxy.py" \
      --decide --state "$state" --task-type "$task_type" \
      --model "$PROXY_MODEL" 2>/dev/null || echo "escalate"
  else
    echo "escalate"
  fi
}
proxy_record() {
  local state="$1" outcome="$2"
  local task_type="${3:-default}"
  local diff_summary="${4:-}"
  if [[ -n "$PROXY_MODEL" ]]; then
    local diff_args=()
    [[ -n "$diff_summary" ]] && diff_args=(--diff "$diff_summary")
    python3 "$SCRIPT_DIR/scripts/human_proxy.py" \
      --record --state "$state" --outcome "$outcome" --task-type "$task_type" \
      ${diff_args[@]+"${diff_args[@]}"} \
      --model "$PROXY_MODEL" 2>/dev/null || true
  fi
}

# ── Intent gathering phase (CfA Phase 1: INTENT_ASSERT proxy gate) ──
# Remove any stale INTENT.md inherited from git or a prior session's worktree.
# A fresh intent phase must start from scratch; the agent writes a new INTENT.md.
rm -f "$SESSION_WORKTREE/INTENT.md"

INTENT_APPROVED=false
if [[ "$SKIP_INTENT" == "true" ]]; then
  # CLI override: --skip-intent forces skip
  echo -e "  ${C_DIM}Intent skipped (--skip-intent).${C_RESET}" >&2
  cfa_set "INTENT"
else
  # Proxy decides whether to run intent gathering
  INTENT_PROXY=$(proxy_decide "INTENT_ASSERT")
  if [[ "$INTENT_PROXY" == "auto-approve" ]]; then
    echo -e "  ${C_DIM}Human proxy: auto-approved intent (high confidence)${C_RESET}" >&2
    proxy_record "INTENT_ASSERT" "approve"
    cfa_set "INTENT"  # Proxy auto-approved — skip intent gathering entirely
  else
    # Run intent.sh — human reviews
    chrome_header "INTENT (CfA Phase 1)"
    INTENT_CTX=()
    # Intent context: only task-scoped files, not team-level MEMORY.md.
    [[ -s "$POC_PROJECT_DIR/OBSERVATIONS.md" ]]  && INTENT_CTX+=(--context-file "$POC_PROJECT_DIR/OBSERVATIONS.md")
    [[ -s "$POC_PROJECT_DIR/ESCALATION.md" ]]    && INTENT_CTX+=(--context-file "$POC_PROJECT_DIR/ESCALATION.md")
    [[ -s "$MEMORY_CTX_FILE" ]]                  && INTENT_CTX+=(--context-file "$MEMORY_CTX_FILE")

    if "$SCRIPT_DIR/intent.sh" --cwd "$SESSION_WORKTREE" --stream-dir "$INFRA_DIR" \
        --project-dir "$POC_PROJECT_DIR" --task "$TASK" \
        --proxy-model "$PROXY_MODEL" "${INTENT_CTX[@]}"; then
      INTENT_APPROVED=true
      # intent.sh records proxy outcomes internally — no proxy_record here
      # Phase 2: Archive INTENT.md to infra dir immediately
      if [[ -f "$SESSION_WORKTREE/INTENT.md" ]]; then
        cp "$SESSION_WORKTREE/INTENT.md" "$INFRA_DIR/INTENT.md"
        rm "$SESSION_WORKTREE/INTENT.md"
      fi
      cfa_set "INTENT"

      # Prepend INTENT.md to the task so it governs downstream planning
      TASK="$(cat "$INFRA_DIR/INTENT.md")

---

Original task: $TASK"

      # Extract intent learnings immediately after approval (background)
      INTENT_EXTRACT_PIDS=()
      if [[ -f "$INFRA_DIR/.intent-stream.jsonl" ]]; then
        python3 "$SCRIPT_DIR/scripts/summarize_session.py" \
          --stream "$INFRA_DIR/.intent-stream.jsonl" \
          --output "$POC_PROJECT_DIR/OBSERVATIONS.md" \
          --scope observations 2>/dev/null &
        INTENT_EXTRACT_PIDS+=($!)
        python3 "$SCRIPT_DIR/scripts/summarize_session.py" \
          --stream "$INFRA_DIR/.intent-stream.jsonl" \
          --output "$POC_PROJECT_DIR/ESCALATION.md" \
          --scope escalation 2>/dev/null &
        INTENT_EXTRACT_PIDS+=($!)
      fi
    else
      # intent.sh records proxy outcomes internally — no proxy_record here
      cfa_set "WITHDRAWN"
      chrome_beep
      echo -e "  ${C_RED}Intent failed — session cannot proceed without approved intent.${C_RESET}" >&2
      exit 1
    fi
  fi
fi

# ── Phase detection and retirement (Phase 4) ──
if [[ "$INTENT_APPROVED" == "true" && -f "$INFRA_DIR/INTENT.md" ]]; then
  # Read old phase BEFORE detect_phase.py overwrites .current-phase
  OLD_PHASE=""
  [[ -f "$POC_PROJECT_DIR/.current-phase" ]] && OLD_PHASE="$(head -1 "$POC_PROJECT_DIR/.current-phase" | tr -d '[:space:]')" || true

  # Detect new phase; prints "PHASE_CHANGED" to stdout on transition
  PHASE_STATUS="$(python3 "$SCRIPT_DIR/scripts/detect_phase.py" \
    --intent "$INFRA_DIR/INTENT.md" \
    --phase-file "$POC_PROJECT_DIR/.current-phase" 2>/dev/null)" || PHASE_STATUS=""

  # Retire task-domain entries from the old phase if a transition occurred
  if [[ "$PHASE_STATUS" == "PHASE_CHANGED" && -n "$OLD_PHASE" && "$OLD_PHASE" != "unknown" ]]; then
    python3 "$SCRIPT_DIR/scripts/retire_phase.py" \
      --old-phase "$OLD_PHASE" \
      --memory "$POC_PROJECT_DIR/MEMORY.md" 2>/dev/null || true
    NEW_PHASE="$(head -1 "$POC_PROJECT_DIR/.current-phase" 2>/dev/null | tr -d '[:space:]')" || NEW_PHASE=""
    echo -e "  ${C_YELLOW}Phase transition: ${OLD_PHASE} → ${NEW_PHASE}${C_RESET}" >&2
  fi
fi

# ── Confidence posture ──
chrome_header "CONFIDENCE POSTURE"
POSTURE_CTX=""
[[ -s "$MEMORY_CTX_FILE" ]] && POSTURE_CTX=$(cat "$MEMORY_CTX_FILE")
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
PLAN_T=15; EXEC_T=30
export POC_STALL_TIMEOUT=1800

PLAN_SESSION_ID=""

while true; do
    # ── Planning phase (CfA Phase 2: DRAFT → PLAN_ASSERT → PLAN) ──
    chrome_header "PLAN (CfA Phase 2)"
    [[ $BACKTRACK_COUNT -gt 0 ]] && echo -e "  ${C_YELLOW}Backtrack #${BACKTRACK_COUNT}${C_RESET}" >&2

    PLAN_EXIT=0
    "$SCRIPT_DIR/plan-execute.sh" \
      --agents "$AGENTS_JSON" \
      --agent project-lead \
      --settings "$SETTINGS_FILE" \
      --cwd "$SESSION_WORKTREE" \
      --stream-dir "$INFRA_DIR" \
      --plan-turns "$PLAN_T" \
      --exec-turns "$EXEC_T" \
      --proxy-model "$PROXY_MODEL" \
      --cfa-state "$CFA_STATE_FILE" \
      --plan-only \
      ${MEMORY_CTX[@]+"${MEMORY_CTX[@]}"} \
      "$TASK" || PLAN_EXIT=$?

    if [[ $PLAN_EXIT -eq 2 ]]; then
      # Backtrack to intent — re-enter intent alignment with feedback
      ((BACKTRACK_COUNT++))
      echo -e "  ${C_YELLOW}Backtracking to intent alignment (backtrack #$BACKTRACK_COUNT)...${C_RESET}" >&2

      BACKTRACK_CTX=""
      [[ -f "$BACKTRACK_FEEDBACK_FILE" ]] && BACKTRACK_CTX=$(cat "$BACKTRACK_FEEDBACK_FILE")

      INTENT_CTX=()
      [[ -s "$POC_PROJECT_DIR/OBSERVATIONS.md" ]] && INTENT_CTX+=(--context-file "$POC_PROJECT_DIR/OBSERVATIONS.md")
      [[ -s "$POC_PROJECT_DIR/ESCALATION.md" ]]   && INTENT_CTX+=(--context-file "$POC_PROJECT_DIR/ESCALATION.md")
      [[ -s "$MEMORY_CTX_FILE" ]]                 && INTENT_CTX+=(--context-file "$MEMORY_CTX_FILE")

      if "$SCRIPT_DIR/intent.sh" --cwd "$SESSION_WORKTREE" --stream-dir "$INFRA_DIR" \
          --project-dir "$POC_PROJECT_DIR" --task "$ORIGINAL_TASK" \
          --proxy-model "$PROXY_MODEL" \
          --backtrack-context "$BACKTRACK_CTX" "${INTENT_CTX[@]}"; then
        if [[ -f "$SESSION_WORKTREE/INTENT.md" ]]; then
          cp "$SESSION_WORKTREE/INTENT.md" "$INFRA_DIR/INTENT.md"
          rm "$SESSION_WORKTREE/INTENT.md"
        fi
        TASK="$(cat "$INFRA_DIR/INTENT.md")

---

Original task: $ORIGINAL_TASK"
      fi
      continue  # Re-enter planning loop
    elif [[ $PLAN_EXIT -eq 1 ]]; then
      echo -e "  ${C_YELLOW}Plan rejected — session ending.${C_RESET}" >&2
      break
    fi

    # Extract plan session ID for execute --resume
    [[ -f "$INFRA_DIR/.plan-session-id" ]] && PLAN_SESSION_ID=$(cat "$INFRA_DIR/.plan-session-id")

    # ── Execution phase (CfA Phase 3: PLAN → TASK → COMPLETED_WORK) ──
    chrome_header "EXECUTE (CfA Phase 3)"
    EXEC_EXIT=0
    "$SCRIPT_DIR/plan-execute.sh" \
      --agents "$AGENTS_JSON" \
      --agent project-lead \
      --settings "$SETTINGS_FILE" \
      --cwd "$SESSION_WORKTREE" \
      --stream-dir "$INFRA_DIR" \
      --plan-turns "$PLAN_T" \
      --exec-turns "$EXEC_T" \
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

      BACKTRACK_CTX=""
      [[ -f "$BACKTRACK_FEEDBACK_FILE" ]] && BACKTRACK_CTX=$(cat "$BACKTRACK_FEEDBACK_FILE")

      INTENT_CTX=()
      [[ -s "$POC_PROJECT_DIR/OBSERVATIONS.md" ]] && INTENT_CTX+=(--context-file "$POC_PROJECT_DIR/OBSERVATIONS.md")
      [[ -s "$POC_PROJECT_DIR/ESCALATION.md" ]]   && INTENT_CTX+=(--context-file "$POC_PROJECT_DIR/ESCALATION.md")
      [[ -s "$MEMORY_CTX_FILE" ]]                 && INTENT_CTX+=(--context-file "$MEMORY_CTX_FILE")

      if "$SCRIPT_DIR/intent.sh" --cwd "$SESSION_WORKTREE" --stream-dir "$INFRA_DIR" \
          --project-dir "$POC_PROJECT_DIR" --task "$ORIGINAL_TASK" \
          --proxy-model "$PROXY_MODEL" \
          --backtrack-context "$BACKTRACK_CTX" "${INTENT_CTX[@]}"; then
        if [[ -f "$SESSION_WORKTREE/INTENT.md" ]]; then
          cp "$SESSION_WORKTREE/INTENT.md" "$INFRA_DIR/INTENT.md"
          rm "$SESSION_WORKTREE/INTENT.md"
        fi
        TASK="$(cat "$INFRA_DIR/INTENT.md")

---

Original task: $ORIGINAL_TASK"
      else
        cfa_set "WITHDRAWN"
        echo -e "  ${C_RED}Intent failed during backtrack — session ending.${C_RESET}" >&2
        break
      fi
      continue  # Re-enter planning with updated intent
    elif [[ $EXEC_EXIT -eq 3 ]]; then
      # Backtrack to planning
      ((BACKTRACK_COUNT++))
      echo -e "  ${C_YELLOW}Execution backtracking to planning (backtrack #$BACKTRACK_COUNT)...${C_RESET}" >&2
      continue  # Re-enter planning loop (skip intent)
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
SESSION_LOG=$(git -C "$POC_REPO_DIR" log --format='- %s' HEAD.."$SESSION_BRANCH" 2>/dev/null || true)

# Squash-merge session branch into main
if ! git -C "$POC_REPO_DIR" merge --squash "$SESSION_BRANCH" 2>&1; then
  echo -e "  ${C_YELLOW}Merge conflict — retrying with -X theirs...${C_RESET}" >&2
  git -C "$POC_REPO_DIR" reset --hard HEAD 2>/dev/null || true
  git -C "$POC_REPO_DIR" merge --squash -X theirs "$SESSION_BRANCH" 2>&1 || \
    echo -e "  ${C_RED}Session merge failed — deliverables remain on branch $SESSION_BRANCH${C_RESET}" >&2
fi

# Commit squashed changes with a structured message
if ! git -C "$POC_REPO_DIR" diff --cached --quiet 2>/dev/null; then
  SQUASH_MSG_FILE=$(mktemp)
  {
    echo "$PROJECT: ${TASK:0:72}"
    echo ""
    if [[ -n "$SESSION_LOG" ]]; then
      echo "Squashed commits:"
      echo "$SESSION_LOG"
      echo ""
    fi
    echo "Files changed:"
    git -C "$POC_REPO_DIR" diff --cached --name-only 2>/dev/null | sed 's/^/- /'
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

# 7. Intent-vs-outcome alignment (Phase 2: INTENT.md archived to infra dir)
if [[ -f "$INFRA_DIR/INTENT.md" && -f "$INFRA_DIR/.exec-stream.jsonl" ]]; then
  python3 "$SCRIPT_DIR/scripts/summarize_session.py" \
    --stream "$INFRA_DIR/.exec-stream.jsonl" \
    --output "$POC_PROJECT_DIR/OBSERVATIONS.md" \
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
  python3 "$SCRIPT_DIR/scripts/track_reinforcement.py" \
    --ids-file "$RETRIEVED_IDS_FILE" \
    --memory "$POC_PROJECT_DIR/MEMORY.md" \
    --memory "$(dirname "$POC_PROJECT_DIR")/MEMORY.md" 2>/dev/null || true
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
