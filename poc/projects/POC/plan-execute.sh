#!/usr/bin/env bash
# plan-execute.sh — CfA-aware plan-then-execute lifecycle for agent teams.
#
# Works at both levels:
#   Uber:    plan-execute.sh --agents "$JSON" --agent project-lead "Design a book"
#   Subteam: plan-execute.sh --agents "$JSON" --agent art-lead --agent-mode "Create diagrams"
#
# CfA modes (used by run.sh backtracking loop):
#   --plan-only      Run plan phase only, stop after approval
#   --execute-only   Run execute phase only (requires --resume-session)
#
# CfA exit codes:
#   0 = success (COMPLETED_WORK or PLAN approved)
#   1 = rejected/failed (WITHDRAWN)
#   2 = backtrack to intent (re-enter intent alignment)
#   3 = backtrack to planning (re-enter planning)
#   4 = infrastructure failure (process crash/timeout/error, agent-mode)
#  10 = plan escalation (proxy not confident, agent-mode)
#  11 = work escalation (proxy not confident, agent-mode)
#
# Legacy flow (no --plan-only/--execute-only):
#   1. Plan  — claude -p --permission-mode plan (agent plans, calls ExitPlanMode)
#   2. Approve — human gate (or proxy auto-approve when confident)
#   3. Execute — claude -p --resume $SESSION_ID (agent executes the plan)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/chrome.sh"

# Defaults
AGENTS_JSON=""
LEAD=""
AGENT_MODE=false
SETTINGS_FILE=""
CWD=""
ADD_DIRS=()
FILTER_PREFIX=""
STREAM_DIR=""
CONTEXT_FILES=()
TASK=""
NO_PLAN=false
PLAN_ONLY=false
EXECUTE_ONLY=false
RESUME_SESSION=""
PROXY_MODEL=""
CFA_STATE_FILE=""

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --agents)          AGENTS_JSON="$2"; shift 2 ;;
    --agent)           LEAD="$2"; shift 2 ;;
    --agent-mode)      AGENT_MODE=true; shift ;;
    --settings)        SETTINGS_FILE="$2"; shift 2 ;;
    --cwd)             CWD="$2"; shift 2 ;;
    --add-dir)         ADD_DIRS+=("$2"); shift 2 ;;
    --stream-dir)      STREAM_DIR="$2"; shift 2 ;;
    --filter-prefix)   FILTER_PREFIX="$2"; shift 2 ;;
    --context-file)    CONTEXT_FILES+=("$2"); shift 2 ;;
    --no-plan)         NO_PLAN=true; shift ;;
    --plan-only)       PLAN_ONLY=true; shift ;;
    --execute-only)    EXECUTE_ONLY=true; shift ;;
    --resume-session)  RESUME_SESSION="$2"; shift 2 ;;
    --proxy-model)     PROXY_MODEL="$2"; shift 2 ;;
    --cfa-state)       CFA_STATE_FILE="$2"; shift 2 ;;
    -*)                echo "Unknown option: $1" >&2; exit 1 ;;
    *)                 TASK="$1"; shift ;;
  esac
done

[[ -z "$TASK" ]] && { echo "Usage: plan-execute.sh [options] <task>" >&2; exit 1; }

# Build common claude args
CLAUDE_ARGS=(-p --output-format stream-json --verbose --setting-sources user)
[[ -n "$AGENTS_JSON" ]]   && CLAUDE_ARGS+=(--agents "$AGENTS_JSON")
[[ -n "$LEAD" ]]           && CLAUDE_ARGS+=(--agent "$LEAD")
[[ -n "$SETTINGS_FILE" ]]  && CLAUDE_ARGS+=(--settings "$SETTINGS_FILE")
for _ad in "${ADD_DIRS[@]+"${ADD_DIRS[@]}"}"; do
  CLAUDE_ARGS+=(--add-dir "$_ad")
done

# Inline context files into the task (claude CLI has no --context-file flag).
# Same approach as intent.sh: read contents and prepend to the prompt.
for ctx in ${CONTEXT_FILES[@]+"${CONTEXT_FILES[@]}"}; do
  if [[ -f "$ctx" && -s "$ctx" ]]; then
    LABEL=$(basename "$ctx")
    TASK="--- $LABEL ---
$(cat "$ctx")
--- end $LABEL ---

$TASK"
  fi
done

# Working directory for agent CWD
WORK_DIR="${CWD:-.}"
mkdir -p "$WORK_DIR"

# Stream files — go to STREAM_DIR if provided, otherwise WORK_DIR
STREAM_TARGET="${STREAM_DIR:-$WORK_DIR}"
mkdir -p "$STREAM_TARGET"
PLAN_STREAM="$STREAM_TARGET/.plan-stream.jsonl"
EXEC_STREAM="$STREAM_TARGET/.exec-stream.jsonl"

# Write pointer for status.sh
echo "$EXEC_STREAM" > "$STREAM_TARGET/.stream-file" 2>/dev/null || true

# Backtrack feedback file — written when human chooses to backtrack
BACKTRACK_FEEDBACK="$STREAM_TARGET/.backtrack-feedback.txt"

# ── Stall watchdog ──
STALL_TIMEOUT="${STALL_TIMEOUT:-1800}"  # 30 minutes default

kill_tree() {
  local pid=$1
  local children
  children=$(pgrep -P "$pid" 2>/dev/null || true)
  for child in $children; do
    kill_tree "$child"
  done
  kill -TERM "$pid" 2>/dev/null || true
}

stall_watchdog() {
  local pid=$1 stream=$2
  sleep 120
  while kill -0 "$pid" 2>/dev/null; do
    sleep 60
    local mtime now age
    mtime=$(stat -f%m "$stream" 2>/dev/null || stat -c%Y "$stream" 2>/dev/null || echo 0)
    now=$(date +%s)
    age=$(( now - mtime ))
    if [[ $age -ge $STALL_TIMEOUT ]]; then
      local running_count=0
      if [[ -n "${POC_SESSION_DIR:-}" ]]; then
        running_count=$(find "$POC_SESSION_DIR" -name ".running" 2>/dev/null | wc -l | tr -d ' ')
      fi
      if [[ $running_count -gt 0 ]]; then
        echo -e "  ${C_DIM}[watchdog] Stream stale ${age}s but $running_count dispatch(es) active${C_RESET}" >&2
        continue
      fi
      echo -e "  ${C_RED}[watchdog] Stream stale ${age}s — killing PID $pid${C_RESET}" >&2
      echo "Process killed after ${age}s of inactivity (stall timeout: ${STALL_TIMEOUT}s)" \
        > "$STREAM_TARGET/.failure-reason"
      kill_tree "$pid"
      break
    fi
  done
}

filter_stream() {
  local dest="${CONVERSATION_LOG:-/dev/stderr}"
  if [[ -n "$FILTER_PREFIX" ]]; then
    python3 -u "$SCRIPT_DIR/stream_filter.py" | sed -u "s/^/$FILTER_PREFIX/" >> "$dest"
  else
    python3 -u "$SCRIPT_DIR/stream_filter.py" >> "$dest"
  fi
}

extract_session_id() {
  python3 -c "
import json, sys
for line in sys.stdin:
    try:
        ev = json.loads(line.strip())
        if ev.get('type') == 'system' and ev.get('subtype') == 'init':
            print(ev['session_id'])
            break
    except:
        pass
"
}

# Check if the planning stream contains permission blocks (denied reads/globs).
# A plan built without reading essential inputs is not trustworthy.
# Sets PLAN_PERM_BLOCKS (non-empty if blocks found).
check_plan_perm_blocks() {
  local stream_file="$1"
  PLAN_PERM_BLOCKS=$(python3 -c "
import json, sys
blocks = []
for line in open('$stream_file'):
    try:
        ev = json.loads(line.strip())
    except: continue
    if ev.get('type') != 'user': continue
    for b in ev.get('message',{}).get('content',[]):
        if not isinstance(b, dict) or not b.get('is_error'): continue
        t = b.get('text','') or b.get('content','')
        if 'denied' in t.lower() or 'requires approval' in t or 'require approval' in t or 'not allowed' in t.lower():
            blocks.append(t.strip())
for b in blocks[:5]: print(b)
" 2>/dev/null || true)
}

# If planning had permission blocks, abort before PLAN_ASSERT.
# Returns 0 if it handled the failure (caller should not proceed to PLAN_ASSERT).
# Returns 1 if no blocks found (caller proceeds normally).
gate_plan_perm_blocks() {
  local stream_file="$1"
  check_plan_perm_blocks "$stream_file"
  [[ -z "$PLAN_PERM_BLOCKS" ]] && return 1  # no blocks — proceed normally

  local failure_summary="Planning blocked by permission restrictions.
The agent could not read files needed for planning:

$(echo "$PLAN_PERM_BLOCKS" | while IFS= read -r b; do echo "- $b"; done)

A plan produced without reading the essential inputs is not trustworthy."

  echo -e "  ${C_RED}Planning blocked — agent could not read essential files${C_RESET}" >&2
  session_log STATE "Planning blocked by permission restrictions"

  if [[ "$AGENT_MODE" == "true" ]]; then
    echo "$failure_summary" > "$BACKTRACK_FEEDBACK"
    exit 4  # infrastructure failure
  fi

  cfa_failure_decision "$failure_summary" "planning"
  case "$FAILURE_ACTION" in
    retry)    return 0 ;;  # caller should re-run planning
    backtrack)
      echo "$failure_summary" > "$BACKTRACK_FEEDBACK"
      exit 2 ;;
    withdraw)
      cfa_set "WITHDRAWN"
      exit 1 ;;
    *)
      echo "$failure_summary" > "$BACKTRACK_FEEDBACK"
      exit 2 ;;
  esac
}

run_claude() {
  local stream_file="$1"; shift
  local task_input="$1"; shift

  local fifo
  fifo=$(mktemp -u).fifo
  mkfifo "$fifo"

  (cd "$WORK_DIR" && echo "$task_input" | claude "${CLAUDE_ARGS[@]}" "$@" > "$fifo") &
  local bg_pid=$!

  stall_watchdog "$bg_pid" "$stream_file" &
  local watchdog_pid=$!

  cat < "$fifo" \
    | tee "$stream_file" \
    | tee >(filter_stream) \
    | tee >(session_stream_log "$FILTER_PREFIX") > /dev/null

  CLAUDE_EXIT=0
  wait "$bg_pid" 2>/dev/null || CLAUDE_EXIT=$?

  kill "$watchdog_pid" 2>/dev/null || true
  wait "$watchdog_pid" 2>/dev/null || true

  rm -f "$fifo"
}

# Orchestrated multi-agent execution: message broker with priority mailboxes.
# Used for exec phase when --agents is present (spoke-and-wheel pattern).
run_orchestrated() {
  local stream_file="$1"; shift
  local task_input="$1"; shift
  local resume_session="${1:-}"
  [[ -n "$resume_session" ]] && shift

  local orch_args=(
    --agents "$AGENTS_JSON"
    --agent "$LEAD"
    --stream "$stream_file"
    --cwd "$WORK_DIR"
    --max-turns 20
  )
  [[ -n "$SETTINGS_FILE" ]] && orch_args+=(--settings "$SETTINGS_FILE")
  [[ -n "${SESSION_LOG:-}" ]] && orch_args+=(--session-log "$SESSION_LOG")
  [[ -n "$resume_session" ]] && orch_args+=(--resume "$resume_session")

  # Forward --add-dir flags so orchestrated agents can read project files
  for _ad in ${ADD_DIRS[@]+"${ADD_DIRS[@]}"}; do
    orch_args+=(--add-dir "$_ad")
  done

  CLAUDE_EXIT=0
  python3 "$SCRIPT_DIR/orchestrator.py" "${orch_args[@]}" "$task_input" >&2 || CLAUDE_EXIT=$?

  # Post-process: run filter and session stream logger on the merged stream
  if [[ -f "$stream_file" ]]; then
    cat "$stream_file" | filter_stream &
    cat "$stream_file" | session_stream_log "$FILTER_PREFIX" &
    wait
  fi
}

# ── CfA state helpers ──

# Validated transition: checks the action is legal from the current state.
# Returns 0 on success, 1 on failure. Prints new state to stdout on success.
cfa_transition() {
  local action="$1"
  if [[ -n "$CFA_STATE_FILE" && -f "$CFA_STATE_FILE" ]]; then
    if ! python3 "$SCRIPT_DIR/scripts/cfa_state.py" --transition \
        --state-file "$CFA_STATE_FILE" --action "$action" 2>/dev/null; then
      echo -e "  ${C_DIM}CfA: transition '$action' invalid from current state${C_RESET}" >&2
      return 1
    fi
  fi
}

# Direct state set: bypasses transition validation.
# Used after autonomous agent runs where intermediate states aren't tracked.
cfa_set() {
  local target="$1"
  if [[ -n "$CFA_STATE_FILE" && -f "$CFA_STATE_FILE" ]]; then
    python3 "$SCRIPT_DIR/scripts/cfa_state.py" --set-state \
      --state-file "$CFA_STATE_FILE" --target "$target" 2>/dev/null || true
  fi
}

# ── Human proxy helper ──
# Queries the proxy model to decide whether to auto-approve or escalate.
# Returns "auto-approve" or "escalate" on stdout.
proxy_decide() {
  local state="$1"
  local task_type="${POC_PROJECT:-default}"
  if [[ -n "$PROXY_MODEL" && -f "$PROXY_MODEL" ]]; then
    python3 "$SCRIPT_DIR/scripts/human_proxy.py" \
      --decide --state "$state" --task-type "$task_type" \
      --model "$PROXY_MODEL" 2>/dev/null || echo "escalate"
  else
    echo "escalate"
  fi
}

# Records outcome to the proxy model.
# Usage: proxy_record STATE OUTCOME [DIFF_SUMMARY]
proxy_record() {
  local state="$1" outcome="$2"
  local diff_summary="${3:-}"
  local task_type="${POC_PROJECT:-default}"
  if [[ -n "$PROXY_MODEL" ]]; then
    local diff_args=()
    [[ -n "$diff_summary" ]] && diff_args=(--diff "$diff_summary")
    python3 "$SCRIPT_DIR/scripts/human_proxy.py" \
      --record --state "$state" --task-type "$task_type" \
      --outcome "$outcome" ${diff_args[@]+"${diff_args[@]}"} \
      --model "$PROXY_MODEL" 2>/dev/null || true
  fi
}

# ── Execute-only mode: skip straight to execution ──
if [[ "$EXECUTE_ONLY" == "true" ]]; then
  chrome_header "TASK → TASK_IN_PROGRESS (CfA Phase 3: Execution)"
  session_log STATE "TASK → TASK_IN_PROGRESS (execute-only mode)"
  cfa_set "TASK"  # Agent runs autonomously through TASK → TASK_IN_PROGRESS → ...

  EXEC_SESSION_ID="$RESUME_SESSION"
  CORRECTION_MSG=""
  PLAN_FILE="${PLAN_FILE:-$STREAM_TARGET/plan.md}"

  # ── Execution loop: run → review → (correct → re-run) or (exit) ──
  # Per spec: WORK_ASSERT correct → TASK_RESPONSE → agent fixes → WORK_ASSERT
  while true; do
    if [[ -n "$CORRECTION_MSG" && -n "$EXEC_SESSION_ID" ]]; then
      # Correction round: resume agent with feedback (TASK_RESPONSE → TASK_IN_PROGRESS)
      cfa_set "TASK_IN_PROGRESS"
      if [[ -n "$AGENTS_JSON" ]]; then
        run_orchestrated "$EXEC_STREAM" "$CORRECTION_MSG" "$EXEC_SESSION_ID"
      else
        run_claude "$EXEC_STREAM" "$CORRECTION_MSG" \
          --resume "$EXEC_SESSION_ID" --permission-mode acceptEdits
      fi
    elif [[ -n "$EXEC_SESSION_ID" ]]; then
      if [[ -n "$AGENTS_JSON" ]]; then
        run_orchestrated "$EXEC_STREAM" "Execute the plan." "$EXEC_SESSION_ID"
      else
        run_claude "$EXEC_STREAM" "Execute the plan." \
          --resume "$EXEC_SESSION_ID" --permission-mode acceptEdits
      fi
    else
      if [[ -n "$AGENTS_JSON" ]]; then
        run_orchestrated "$EXEC_STREAM" "$TASK"
      else
        run_claude "$EXEC_STREAM" "$TASK" \
          --permission-mode acceptEdits
      fi
    fi

    # Extract session ID for correction rounds
    if [[ -z "$EXEC_SESSION_ID" ]]; then
      EXEC_SESSION_ID=$(extract_session_id < "$EXEC_STREAM")
    fi

    # ── Infrastructure failure gate ──
    if [[ $CLAUDE_EXIT -ne 0 ]]; then
      FAILURE_SUMMARY=$(extract_failure "$EXEC_STREAM" "$CLAUDE_EXIT" "$STREAM_TARGET")
      session_log STATE "Infrastructure failure (exit $CLAUDE_EXIT) during execution"

      if [[ "$AGENT_MODE" == "true" ]]; then
        echo "$FAILURE_SUMMARY" > "$BACKTRACK_FEEDBACK"
        cfa_set "FAILED_TASK"
        exit 4
      fi

      cfa_failure_decision "$FAILURE_SUMMARY" "execution"
      case "$FAILURE_ACTION" in
        retry)    CORRECTION_MSG=""; continue ;;
        escalate)
          cfa_set "TASK_ESCALATE"
          echo "$FAILURE_SUMMARY" > "$STREAM_TARGET/.task-escalation.md"
          ;;  # fall through to escalation handling below
        backtrack)
          echo "$FAILURE_SUMMARY" > "$BACKTRACK_FEEDBACK"
          exit 3 ;;
        withdraw)
          cfa_set "WITHDRAWN"
          exit 1 ;;
      esac
    fi

    # ── Auto-detect permission blocks → generate escalation ──
    TASK_ESCALATION="$STREAM_TARGET/.task-escalation.md"
    if [[ ! -f "$TASK_ESCALATION" ]]; then
      PERM_BLOCKS=$(python3 -c "
import json, sys
blocks = []
for line in open('$EXEC_STREAM'):
    try:
        ev = json.loads(line.strip())
    except: continue
    if ev.get('type') != 'user': continue
    for b in ev.get('message',{}).get('content',[]):
        if not isinstance(b, dict) or not b.get('is_error'): continue
        t = b.get('text','') or b.get('content','')
        if 'requires approval' in t or 'require approval' in t:
            blocks.append(t.strip())
for b in blocks[:5]: print(b)
" 2>/dev/null || true)
      if [[ -n "$PERM_BLOCKS" ]]; then
        {
          echo "## Execution blocked by permission restrictions"
          echo ""
          echo "The agent was unable to complete execution because the following"
          echo "commands were denied by the permission system:"
          echo ""
          echo "$PERM_BLOCKS" | while IFS= read -r b; do echo "- $b"; done
          echo ""
          echo "The human approved the intent and plan, but the execution"
          echo "environment blocked the commands needed to carry them out."
          echo ""
          echo "Options: grant permission and re-run, or run the commands manually."
        } > "$TASK_ESCALATION"
        echo -e "  ${C_DIM}Auto-detected permission blocks → TASK_ESCALATE${C_RESET}" >&2
        session_log STATE "Auto-detected permission blocks → TASK_ESCALATE"
      fi
    fi

    # ── Check for execution escalation (TASK_ESCALATE) ──
    if [[ -f "$TASK_ESCALATION" ]]; then
      cfa_set "TASK_ESCALATE"
      session_log STATE "TASK_ESCALATE — agent needs clarification"
      chrome_header "TASK_ESCALATE — agent needs clarification"
      chrome_bridge "$TASK_ESCALATION" "TASK_ESCALATE" "$TASK"
      chrome_heavy_line

      if [[ "$AGENT_MODE" == "true" ]]; then
        cp "$TASK_ESCALATION" "$BACKTRACK_FEEDBACK"
        rm -f "$TASK_ESCALATION"
        exit 11
      fi

      cfa_review_loop "TASK_ESCALATE" "" "" "$TASK_ESCALATION" "" "$TASK"
      if [[ "$REVIEW_ACTION" == "withdraw" ]]; then
        proxy_record "TASK_ESCALATE" "withdraw"
        cfa_transition "withdraw" || cfa_set "WITHDRAWN"
        session_log STATE "TASK_ESCALATE → withdraw → WITHDRAWN"
        rm -f "$TASK_ESCALATION"
        exit 1
      fi

      proxy_record "TASK_ESCALATE" "clarify" "$CFA_RESPONSE"
      cfa_transition "clarify" || cfa_set "TASK_RESPONSE"
      echo -e "  ${C_DIM}CfA: TASK_ESCALATE → clarify → TASK_RESPONSE → TASK_IN_PROGRESS${C_RESET}" >&2
      session_log STATE "TASK_ESCALATE → clarify → TASK_RESPONSE → TASK_IN_PROGRESS"
      rm -f "$TASK_ESCALATION"
      cfa_set "TASK_IN_PROGRESS"
      CORRECTION_MSG="Human clarification: $CFA_RESPONSE"
      continue
    fi

    # ── WORK_ASSERT: human/proxy reviews the work ──
    cfa_set "WORK_ASSERT"  # Agent completed: WORK_IN_PROGRESS → assert → WORK_ASSERT
    chrome_header "WORK_ASSERT (CfA Phase 3 — human reviews deliverable)"
    PROXY_ACTION=$(proxy_decide "WORK_ASSERT")
    session_log PROXY "WORK_ASSERT proxy=$PROXY_ACTION"

    if [[ "$PROXY_ACTION" == "auto-approve" ]]; then
      echo -e "  ${C_DIM}CfA: WORK_ASSERT → approve → COMPLETED_WORK (proxy auto-approved)${C_RESET}" >&2
      session_log STATE "WORK_ASSERT → approve → COMPLETED_WORK (proxy auto-approved)"
      proxy_record "WORK_ASSERT" "approve"
      cfa_transition "approve" || cfa_set "COMPLETED_WORK"
      break
    elif [[ "$AGENT_MODE" == "true" ]]; then
      # Agent mode: escalate to outer scope — Execution Lead is our "human"
      echo "Work requires review — proxy not confident enough to auto-approve" > "$BACKTRACK_FEEDBACK"
      exit 11  # work escalation
    fi

    # Completion assertion bridge — frame what was accomplished
    WORK_SUMMARY_FILE="$STREAM_TARGET/.work-summary.md"
    python3 "$SCRIPT_DIR/extract_result.py" < "$EXEC_STREAM" > "$WORK_SUMMARY_FILE"
    chrome_bridge "$WORK_SUMMARY_FILE" "WORK_ASSERT" "$TASK"
    chrome_heavy_line

    # Free-text review with dialog loop
    PLAN_SUMMARY=$(head -c 500 "$PLAN_FILE" 2>/dev/null || true)
    INTENT_SUMMARY=$(head -c 500 "$WORK_DIR/INTENT.md" 2>/dev/null || true)

    if cfa_review_loop "WORK_ASSERT" "$INTENT_SUMMARY" "$PLAN_SUMMARY" "$PLAN_FILE" "$EXEC_STREAM" "$TASK"; then
      case "$REVIEW_ACTION" in
        approve)
          proxy_record "WORK_ASSERT" "approve"
          cfa_transition "approve" || cfa_set "COMPLETED_WORK"
          echo -e "  ${C_DIM}CfA: WORK_ASSERT → approve → COMPLETED_WORK${C_RESET}" >&2
          session_log STATE "WORK_ASSERT → approve → COMPLETED_WORK"
          break
          ;;
        correct)
          cfa_transition "correct" || cfa_set "TASK_RESPONSE"
          echo -e "  ${C_DIM}CfA: WORK_ASSERT → correct → TASK_RESPONSE${C_RESET}" >&2
          session_log STATE "WORK_ASSERT → correct → TASK_RESPONSE"
          proxy_record "WORK_ASSERT" "correct" "$REVIEW_FEEDBACK"
          CORRECTION_MSG="Apply this correction to the work: $REVIEW_FEEDBACK"
          ;;
        revise-plan)
          cfa_transition "revise-plan" || cfa_set "PLANNING_RESPONSE"
          echo -e "  ${C_DIM}CfA: WORK_ASSERT → revise-plan → PLANNING_RESPONSE (cross-phase backtrack)${C_RESET}" >&2
          session_log STATE "WORK_ASSERT → revise-plan → PLANNING_RESPONSE (cross-phase backtrack)"
          proxy_record "WORK_ASSERT" "correct" "$REVIEW_FEEDBACK"
          echo "$REVIEW_FEEDBACK" > "$BACKTRACK_FEEDBACK"
          exit 3
          ;;
        refine-intent)
          cfa_transition "refine-intent" || cfa_set "INTENT_RESPONSE"
          echo -e "  ${C_DIM}CfA: WORK_ASSERT → refine-intent → INTENT_RESPONSE (cross-phase backtrack)${C_RESET}" >&2
          session_log STATE "WORK_ASSERT → refine-intent → INTENT_RESPONSE (cross-phase backtrack)"
          proxy_record "WORK_ASSERT" "correct" "$REVIEW_FEEDBACK"
          echo "$REVIEW_FEEDBACK" > "$BACKTRACK_FEEDBACK"
          exit 2
          ;;
        withdraw)
          proxy_record "WORK_ASSERT" "withdraw"
          cfa_transition "withdraw" || cfa_set "WITHDRAWN"
          echo -e "  ${C_DIM}CfA: WORK_ASSERT → withdraw → WITHDRAWN${C_RESET}" >&2
          session_log STATE "WORK_ASSERT → withdraw → WITHDRAWN"
          exit 1
          ;;
      esac
    else
      # Fallback: treat raw input as work correction
      cfa_transition "correct" || cfa_set "TASK_RESPONSE"
      session_log STATE "WORK_ASSERT → correct → TASK_RESPONSE (fallback)"
      proxy_record "WORK_ASSERT" "correct" "$CFA_RESPONSE"
      CORRECTION_MSG="Apply this correction to the work: $CFA_RESPONSE"
    fi
  done

  python3 "$SCRIPT_DIR/extract_result.py" < "$EXEC_STREAM"
  chrome_header "done"
  chrome_beep
  exit 0
fi

# ── Plan phase (also used by --plan-only mode) ──
if [[ "$NO_PLAN" == "true" ]]; then
  chrome_header "EXECUTE (no plan mode)"
  # NO_PLAN: skip planning phase but still track CfA state
  # The human decided no plan is needed — equivalent to auto-approving an empty plan
  cfa_set "PLAN"  # Jump to PLAN (planning phase complete)
  SESSION_ID=""
else
  chrome_header "DRAFT (CfA Phase 2: Planning)"
  session_log STATE "DRAFT (planning phase)"
  cfa_set "DRAFT"  # Agent runs autonomously through DRAFT (planning)

  PLANS_BEFORE=$(mktemp)
  ls ~/.claude/plans/ 2>/dev/null | sort > "$PLANS_BEFORE" || true

  run_claude "$PLAN_STREAM" "$TASK" \
    --permission-mode plan

  # ── Planning infrastructure failure gate ──
  if [[ $CLAUDE_EXIT -ne 0 ]]; then
    FAILURE_SUMMARY=$(extract_failure "$PLAN_STREAM" "$CLAUDE_EXIT" "$STREAM_TARGET")
    session_log STATE "Infrastructure failure (exit $CLAUDE_EXIT) during planning"

    if [[ "$AGENT_MODE" == "true" ]]; then
      echo "$FAILURE_SUMMARY" > "$BACKTRACK_FEEDBACK"
      exit 4
    fi

    cfa_failure_decision "$FAILURE_SUMMARY" "planning"
    case "$FAILURE_ACTION" in
      retry)
        # Re-run planning from scratch
        run_claude "$PLAN_STREAM" "$TASK" --permission-mode plan
        ;;
      backtrack)
        echo "$FAILURE_SUMMARY" > "$BACKTRACK_FEEDBACK"
        exit 2 ;;  # backtrack to intent
      withdraw)
        cfa_set "WITHDRAWN"
        exit 1 ;;
      *)
        # escalate → treat as backtrack for planning phase
        echo "$FAILURE_SUMMARY" > "$BACKTRACK_FEEDBACK"
        exit 2 ;;
    esac
  fi

  SESSION_ID=$(extract_session_id < "$PLAN_STREAM")

  if [[ -z "$SESSION_ID" ]]; then
    echo -e "  ${C_RED}Could not extract session ID from plan output${C_RESET}" >&2
    exit 1
  fi

  # ── Planning escalation loop (PLANNING_ESCALATE) ──
  # Agent may escalate multiple times — loop until it stops writing escalation files.
  while [[ -f "$STREAM_TARGET/.plan-escalation.md" ]]; do
    PLAN_ESCALATION="$STREAM_TARGET/.plan-escalation.md"
    cfa_set "PLANNING_ESCALATE"
    chrome_header "PLANNING_ESCALATE — agent needs clarification"
    chrome_bridge "$PLAN_ESCALATION" "PLANNING_ESCALATE" "$TASK"
    chrome_heavy_line

    if [[ "$AGENT_MODE" == "true" ]]; then
      # Subteam: escalate to outer scope
      cp "$PLAN_ESCALATION" "$BACKTRACK_FEEDBACK"
      rm -f "$PLAN_ESCALATION"
      exit 10
    fi

    cfa_review_loop "PLANNING_ESCALATE" "" "" "$PLAN_ESCALATION" "" "$TASK"
    if [[ "$REVIEW_ACTION" == "withdraw" ]]; then
      proxy_record "PLANNING_ESCALATE" "withdraw"
      cfa_transition "withdraw" || cfa_set "WITHDRAWN"
      rm -f "$PLAN_ESCALATION"
      exit 1
    fi

    proxy_record "PLANNING_ESCALATE" "clarify" "$CFA_RESPONSE"
    cfa_transition "clarify" || cfa_set "PLANNING_RESPONSE"
    echo -e "  ${C_DIM}CfA: PLANNING_ESCALATE → clarify → PLANNING_RESPONSE → synthesize → DRAFT${C_RESET}" >&2
    session_log STATE "PLANNING_ESCALATE → clarify → PLANNING_RESPONSE → DRAFT"
    rm -f "$PLAN_ESCALATION"
    cfa_set "DRAFT"
    run_claude "$PLAN_STREAM" "Human clarification: $CFA_RESPONSE" \
      --resume "$SESSION_ID" --permission-mode plan
  done

  # ── Planning permission block gate ──
  # If the agent couldn't read essential files, the plan is worthless.
  if gate_plan_perm_blocks "$PLAN_STREAM"; then
    # Permission blocks detected and handled (retry chosen) — re-run planning
    run_claude "$PLAN_STREAM" "$TASK" --permission-mode plan
  fi

  cfa_set "PLAN_ASSERT"  # Agent completed planning: DRAFT → assert → PLAN_ASSERT
  echo -e "  ${C_DIM}plan complete (session: ${SESSION_ID:0:8}...)${C_RESET}" >&2
  session_log AGENT "Plan phase complete (session: ${SESSION_ID:0:8})"

  # Save session ID for --execute-only mode
  echo "$SESSION_ID" > "$STREAM_TARGET/.plan-session-id"

  PLANS_AFTER=$(mktemp)
  ls ~/.claude/plans/ 2>/dev/null | sort > "$PLANS_AFTER" || true
  NEW_PLANS=$(comm -13 "$PLANS_BEFORE" "$PLANS_AFTER" || true)
  for plan in $NEW_PLANS; do
    mv ~/.claude/plans/"$plan" "$STREAM_TARGET/plan.md"
    echo -e "  ${C_DIM}Relocated plan: $plan${C_RESET}" >&2
    break
  done
  rm -f "$PLANS_BEFORE" "$PLANS_AFTER"

  # Log plan content to session log (first 800 chars)
  if [[ -f "$STREAM_TARGET/plan.md" ]]; then
    PLAN_PREVIEW=$(head -c 800 "$STREAM_TARGET/plan.md" 2>/dev/null || true)
    PLAN_SIZE=$(wc -c < "$STREAM_TARGET/plan.md" 2>/dev/null | tr -d ' ')
    session_log PLAN "--- plan.md (${PLAN_SIZE} bytes) ---"
    while IFS= read -r pline; do
      session_log PLAN "$pline"
    done <<< "${PLAN_PREVIEW}"
    [[ ${#PLAN_PREVIEW} -ge 800 ]] && session_log PLAN "... (truncated, see plan.md for full content)"
    session_log PLAN "--- end plan.md ---"
  fi
fi

# ── Approve phase (CfA: PLAN_ASSERT) ──
PLAN_FILE="$STREAM_TARGET/plan.md"

if [[ "$NO_PLAN" != "true" ]]; then
  # CfA plan approval loop — always consult proxy, supports revision and backtracking
  while true; do
    chrome_header "PLAN_ASSERT (CfA Phase 2 — human reviews plan)"

    # Always check human proxy confidence — no more bypassing
    PROXY_ACTION=$(proxy_decide "PLAN_ASSERT")
    session_log PROXY "PLAN_ASSERT proxy=$PROXY_ACTION"

    if [[ "$PROXY_ACTION" == "auto-approve" ]]; then
      echo -e "  ${C_DIM}CfA: PLAN_ASSERT → approve → PLAN (proxy auto-approved)${C_RESET}" >&2
      session_log STATE "PLAN_ASSERT → approve → PLAN (proxy auto-approved)"
      proxy_record "PLAN_ASSERT" "approve"
      cfa_transition "approve" || cfa_set "PLAN"
      break
    fi

    if [[ "$AGENT_MODE" == "true" ]]; then
      # Agent mode: escalate to outer scope — Execution Lead is our "human"
      echo "Plan requires review — proxy not confident enough to auto-approve" > "$BACKTRACK_FEEDBACK"
      exit 10  # plan escalation
    fi

    if [[ -f "$PLAN_FILE" ]]; then
      chrome_banner "PLAN_ASSERT" "CfA Phase 2 — human reviews plan"
      chrome_bridge "$PLAN_FILE" "PLAN_ASSERT" "$TASK"
      chrome_heavy_line
    else
      # No plan.md — extract from stream and bridge the result
      PLAN_EXTRACT=$(mktemp)
      python3 "$SCRIPT_DIR/extract_result.py" < "$PLAN_STREAM" > "$PLAN_EXTRACT"
      chrome_banner "PLAN_ASSERT" "CfA Phase 2 — human reviews plan"
      chrome_bridge "$PLAN_EXTRACT" "PLAN_ASSERT" "$TASK"
      chrome_heavy_line
      rm -f "$PLAN_EXTRACT"
    fi

    # Free-text review with dialog loop
    PLAN_SUMMARY=$(head -c 500 "$PLAN_FILE" 2>/dev/null || true)
    INTENT_SUMMARY=$(head -c 500 "$WORK_DIR/INTENT.md" 2>/dev/null || true)

    if cfa_review_loop "PLAN_ASSERT" "$INTENT_SUMMARY" "$PLAN_SUMMARY" "$PLAN_FILE" "" "$TASK"; then
      case "$REVIEW_ACTION" in
        approve)
          proxy_record "PLAN_ASSERT" "approve"
          cfa_transition "approve" || cfa_set "PLAN"
          echo -e "  ${C_DIM}CfA: PLAN_ASSERT → approve → PLAN${C_RESET}" >&2
          session_log STATE "PLAN_ASSERT → approve → PLAN"
          break
          ;;
        correct)
          cfa_transition "correct" || cfa_set "PLANNING_RESPONSE"
          echo -e "  ${C_DIM}CfA: PLAN_ASSERT → correct → PLANNING_RESPONSE → synthesize → DRAFT${C_RESET}" >&2
          session_log STATE "PLAN_ASSERT → correct → PLANNING_RESPONSE → DRAFT"
          proxy_record "PLAN_ASSERT" "correct" "$REVIEW_FEEDBACK"
          echo -e "  ${C_DIM}Re-planning with feedback...${C_RESET}" >&2
          cfa_set "DRAFT"
          run_claude "$PLAN_STREAM" "Revise the plan based on this feedback: ${REVIEW_FEEDBACK}" \
            --resume "$SESSION_ID" --permission-mode plan
          if gate_plan_perm_blocks "$PLAN_STREAM"; then
            run_claude "$PLAN_STREAM" "Revise the plan based on this feedback: ${REVIEW_FEEDBACK}" \
              --resume "$SESSION_ID" --permission-mode plan
          fi
          cfa_set "PLAN_ASSERT"
          NEW_PLANS=$(ls -t ~/.claude/plans/ 2>/dev/null | head -1 || true)
          [[ -n "$NEW_PLANS" ]] && mv ~/.claude/plans/"$NEW_PLANS" "$PLAN_FILE" 2>/dev/null || true
          continue  # outer plan loop re-enters with fresh dialog
          ;;
        refine-intent)
          cfa_set "INTENT_RESPONSE"
          echo -e "  ${C_DIM}CfA: PLAN_ASSERT → refine-intent → INTENT_RESPONSE (cross-phase backtrack)${C_RESET}" >&2
          session_log STATE "PLAN_ASSERT → refine-intent → INTENT_RESPONSE (cross-phase backtrack)"
          proxy_record "PLAN_ASSERT" "correct" "$REVIEW_FEEDBACK"
          echo "$REVIEW_FEEDBACK" > "$BACKTRACK_FEEDBACK"
          exit 2
          ;;
        withdraw)
          proxy_record "PLAN_ASSERT" "withdraw"
          cfa_transition "withdraw" || cfa_set "WITHDRAWN"
          echo -e "  ${C_DIM}CfA: PLAN_ASSERT → withdraw → WITHDRAWN${C_RESET}" >&2
          session_log STATE "PLAN_ASSERT → withdraw → WITHDRAWN"
          exit 1
          ;;
      esac
    else
      # Fallback: treat raw input as plan correction
      cfa_transition "correct" || cfa_set "PLANNING_RESPONSE"
      session_log STATE "PLAN_ASSERT → correct → PLANNING_RESPONSE (fallback)"
      proxy_record "PLAN_ASSERT" "correct" "$CFA_RESPONSE"
      echo -e "  ${C_DIM}Re-planning with feedback...${C_RESET}" >&2
      cfa_set "DRAFT"
      run_claude "$PLAN_STREAM" "Revise the plan based on this feedback: ${CFA_RESPONSE}" \
        --resume "$SESSION_ID" --permission-mode plan
      if gate_plan_perm_blocks "$PLAN_STREAM"; then
        run_claude "$PLAN_STREAM" "Revise the plan based on this feedback: ${CFA_RESPONSE}" \
          --resume "$SESSION_ID" --permission-mode plan
      fi
      cfa_set "PLAN_ASSERT"
      NEW_PLANS=$(ls -t ~/.claude/plans/ 2>/dev/null | head -1 || true)
      [[ -n "$NEW_PLANS" ]] && mv ~/.claude/plans/"$NEW_PLANS" "$PLAN_FILE" 2>/dev/null || true
      continue  # outer plan loop re-enters
    fi
  done
fi

# ── INTENT.md pre-flight check ──
if [[ -f "$WORK_DIR/INTENT.md" ]]; then
  if grep -qi "open question" "$WORK_DIR/INTENT.md" 2>/dev/null; then
    echo -e "  ${C_YELLOW}[pre-flight] INTENT.md contains open questions — ensure planning resolved them.${C_RESET}" >&2
  fi
fi

# If --plan-only, exit here after plan approval
if [[ "$PLAN_ONLY" == "true" ]]; then
  echo -e "  ${C_DIM}Plan approved (plan-only mode — exiting).${C_RESET}" >&2
  exit 0
fi

# ── Execute phase (with correction loop per CfA spec) ──
cfa_set "TASK"  # Agent runs autonomously through TASK → TASK_IN_PROGRESS → ...
if [[ "$NO_PLAN" != "true" ]]; then
  chrome_header "TASK → TASK_IN_PROGRESS (CfA Phase 3: Execution)"
  session_log STATE "TASK → TASK_IN_PROGRESS (execution phase)"
fi

LEGACY_CORRECTION_MSG=""
LEGACY_SESSION_ID="$SESSION_ID"

while true; do
  if [[ -n "$LEGACY_CORRECTION_MSG" && -n "$LEGACY_SESSION_ID" ]]; then
    # Correction round: resume agent with feedback (TASK_RESPONSE → TASK_IN_PROGRESS)
    cfa_set "TASK_IN_PROGRESS"
    if [[ -n "$AGENTS_JSON" ]]; then
      run_orchestrated "$EXEC_STREAM" "$LEGACY_CORRECTION_MSG" "$LEGACY_SESSION_ID"
    else
      run_claude "$EXEC_STREAM" "$LEGACY_CORRECTION_MSG" \
        --resume "$LEGACY_SESSION_ID" --permission-mode acceptEdits
    fi
  elif [[ "$NO_PLAN" == "true" ]]; then
    if [[ -n "$AGENTS_JSON" ]]; then
      run_orchestrated "$EXEC_STREAM" "$TASK"
    else
      run_claude "$EXEC_STREAM" "$TASK" \
        --permission-mode acceptEdits
    fi
  else
    if [[ -n "$AGENTS_JSON" ]]; then
      run_orchestrated "$EXEC_STREAM" "Execute the plan." "$LEGACY_SESSION_ID"
    else
      run_claude "$EXEC_STREAM" "Execute the plan." \
        --resume "$LEGACY_SESSION_ID" --permission-mode acceptEdits
    fi
  fi

  # Extract session ID for correction rounds
  if [[ -z "$LEGACY_SESSION_ID" ]]; then
    LEGACY_SESSION_ID=$(extract_session_id < "$EXEC_STREAM")
  fi

  # ── Infrastructure failure gate ──
  if [[ $CLAUDE_EXIT -ne 0 ]]; then
    FAILURE_SUMMARY=$(extract_failure "$EXEC_STREAM" "$CLAUDE_EXIT" "$STREAM_TARGET")
    session_log STATE "Infrastructure failure (exit $CLAUDE_EXIT) during execution (legacy)"

    if [[ "$AGENT_MODE" == "true" ]]; then
      echo "$FAILURE_SUMMARY" > "$BACKTRACK_FEEDBACK"
      cfa_set "FAILED_TASK"
      exit 4
    fi

    cfa_failure_decision "$FAILURE_SUMMARY" "execution"
    case "$FAILURE_ACTION" in
      retry)    LEGACY_CORRECTION_MSG=""; continue ;;
      escalate)
        cfa_set "TASK_ESCALATE"
        echo "$FAILURE_SUMMARY" > "$STREAM_TARGET/.task-escalation.md"
        ;;  # fall through to escalation handling below
      backtrack)
        echo "$FAILURE_SUMMARY" > "$BACKTRACK_FEEDBACK"
        exit 3 ;;
      withdraw)
        cfa_set "WITHDRAWN"
        exit 1 ;;
    esac
  fi

  # ── WORK_ASSERT: human/proxy reviews the work ──
  if [[ "$PLAN_ONLY" == "true" || "$EXECUTE_ONLY" == "true" ]]; then
    break  # Skip review in these modes (handled above)
  fi

  # ── Auto-detect permission blocks → generate escalation ──
  LEGACY_TASK_ESCALATION="$STREAM_TARGET/.task-escalation.md"
  if [[ ! -f "$LEGACY_TASK_ESCALATION" ]]; then
    PERM_BLOCKS=$(python3 -c "
import json, sys
blocks = []
for line in open('$EXEC_STREAM'):
    try:
        ev = json.loads(line.strip())
    except: continue
    if ev.get('type') != 'user': continue
    for b in ev.get('message',{}).get('content',[]):
        if not isinstance(b, dict) or not b.get('is_error'): continue
        t = b.get('text','') or b.get('content','')
        if 'requires approval' in t or 'require approval' in t:
            blocks.append(t.strip())
for b in blocks[:5]: print(b)
" 2>/dev/null || true)
    if [[ -n "$PERM_BLOCKS" ]]; then
      {
        echo "## Execution blocked by permission restrictions"
        echo ""
        echo "The agent was unable to complete execution because the following"
        echo "commands were denied by the permission system:"
        echo ""
        echo "$PERM_BLOCKS" | while IFS= read -r b; do echo "- $b"; done
        echo ""
        echo "The human approved the intent and plan, but the execution"
        echo "environment blocked the commands needed to carry them out."
        echo ""
        echo "Options: grant permission and re-run, or run the commands manually."
      } > "$LEGACY_TASK_ESCALATION"
      echo -e "  ${C_DIM}Auto-detected permission blocks → TASK_ESCALATE${C_RESET}" >&2
      session_log STATE "Auto-detected permission blocks → TASK_ESCALATE (legacy)"
    fi
  fi

  # ── Check for execution escalation (TASK_ESCALATE) ──
  if [[ -f "$LEGACY_TASK_ESCALATION" ]]; then
    cfa_set "TASK_ESCALATE"
    session_log STATE "TASK_ESCALATE — agent needs clarification (legacy)"
    chrome_header "TASK_ESCALATE — agent needs clarification"
    chrome_bridge "$LEGACY_TASK_ESCALATION" "TASK_ESCALATE" "$TASK"
    chrome_heavy_line

    if [[ "$AGENT_MODE" == "true" ]]; then
      cp "$LEGACY_TASK_ESCALATION" "$BACKTRACK_FEEDBACK"
      rm -f "$LEGACY_TASK_ESCALATION"
      exit 11
    fi

    cfa_review_loop "TASK_ESCALATE" "" "" "$LEGACY_TASK_ESCALATION" "" "$TASK"
    if [[ "$REVIEW_ACTION" == "withdraw" ]]; then
      proxy_record "TASK_ESCALATE" "withdraw"
      cfa_transition "withdraw" || cfa_set "WITHDRAWN"
      session_log STATE "TASK_ESCALATE → withdraw → WITHDRAWN (legacy)"
      rm -f "$LEGACY_TASK_ESCALATION"
      exit 1
    fi

    proxy_record "TASK_ESCALATE" "clarify" "$CFA_RESPONSE"
    cfa_transition "clarify" || cfa_set "TASK_RESPONSE"
    echo -e "  ${C_DIM}CfA: TASK_ESCALATE → clarify → TASK_RESPONSE → TASK_IN_PROGRESS${C_RESET}" >&2
    session_log STATE "TASK_ESCALATE → clarify → TASK_RESPONSE → TASK_IN_PROGRESS (legacy)"
    rm -f "$LEGACY_TASK_ESCALATION"
    cfa_set "TASK_IN_PROGRESS"
    LEGACY_CORRECTION_MSG="Human clarification: $CFA_RESPONSE"
    continue  # Re-enter execution loop with clarification
  fi

  cfa_set "WORK_ASSERT"  # Agent completed: WORK_IN_PROGRESS → assert → WORK_ASSERT
  PROXY_ACTION=$(proxy_decide "WORK_ASSERT")
  session_log PROXY "WORK_ASSERT proxy=$PROXY_ACTION (legacy)"

  if [[ "$PROXY_ACTION" == "auto-approve" ]]; then
    echo -e "  ${C_DIM}CfA: WORK_ASSERT → approve → COMPLETED_WORK (proxy auto-approved)${C_RESET}" >&2
    session_log STATE "WORK_ASSERT → approve → COMPLETED_WORK (proxy auto-approved, legacy)"
    proxy_record "WORK_ASSERT" "approve"
    cfa_transition "approve" || cfa_set "COMPLETED_WORK"
    break
  elif [[ "$AGENT_MODE" == "true" ]]; then
    # Agent mode: escalate to outer scope — Execution Lead is our "human"
    echo "Work requires review — proxy not confident enough to auto-approve" > "$BACKTRACK_FEEDBACK"
    exit 11  # work escalation
  fi

  chrome_header "WORK_ASSERT (CfA Phase 3 — human reviews deliverable)"

  # Completion assertion bridge — frame what was accomplished
  WORK_SUMMARY_FILE="$STREAM_TARGET/.work-summary.md"
  python3 "$SCRIPT_DIR/extract_result.py" < "$EXEC_STREAM" > "$WORK_SUMMARY_FILE"
  chrome_bridge "$WORK_SUMMARY_FILE" "WORK_ASSERT" "$TASK"
  chrome_heavy_line

  # Free-text review with dialog loop
  PLAN_SUMMARY=$(head -c 500 "$PLAN_FILE" 2>/dev/null || true)
  INTENT_SUMMARY=$(head -c 500 "$WORK_DIR/INTENT.md" 2>/dev/null || true)

  if cfa_review_loop "WORK_ASSERT" "$INTENT_SUMMARY" "$PLAN_SUMMARY" "$PLAN_FILE" "$EXEC_STREAM" "$TASK"; then
    case "$REVIEW_ACTION" in
      approve)
        proxy_record "WORK_ASSERT" "approve"
        cfa_transition "approve" || cfa_set "COMPLETED_WORK"
        echo -e "  ${C_DIM}CfA: WORK_ASSERT → approve → COMPLETED_WORK${C_RESET}" >&2
        session_log STATE "WORK_ASSERT → approve → COMPLETED_WORK (legacy)"
        break
        ;;
      correct)
        cfa_transition "correct" || cfa_set "TASK_RESPONSE"
        echo -e "  ${C_DIM}CfA: WORK_ASSERT → correct → TASK_RESPONSE${C_RESET}" >&2
        session_log STATE "WORK_ASSERT → correct → TASK_RESPONSE (legacy)"
        proxy_record "WORK_ASSERT" "correct" "$REVIEW_FEEDBACK"
        LEGACY_CORRECTION_MSG="Apply this correction to the work: $REVIEW_FEEDBACK"
        ;;
      revise-plan)
        cfa_transition "revise-plan" || cfa_set "PLANNING_RESPONSE"
        echo -e "  ${C_DIM}CfA: WORK_ASSERT → revise-plan → PLANNING_RESPONSE (cross-phase backtrack)${C_RESET}" >&2
        session_log STATE "WORK_ASSERT → revise-plan → PLANNING_RESPONSE (legacy, cross-phase backtrack)"
        proxy_record "WORK_ASSERT" "correct" "$REVIEW_FEEDBACK"
        echo "$REVIEW_FEEDBACK" > "$BACKTRACK_FEEDBACK"
        exit 3
        ;;
      refine-intent)
        cfa_transition "refine-intent" || cfa_set "INTENT_RESPONSE"
        echo -e "  ${C_DIM}CfA: WORK_ASSERT → refine-intent → INTENT_RESPONSE (cross-phase backtrack)${C_RESET}" >&2
        session_log STATE "WORK_ASSERT → refine-intent → INTENT_RESPONSE (legacy, cross-phase backtrack)"
        proxy_record "WORK_ASSERT" "correct" "$REVIEW_FEEDBACK"
        echo "$REVIEW_FEEDBACK" > "$BACKTRACK_FEEDBACK"
        exit 2
        ;;
      withdraw)
        proxy_record "WORK_ASSERT" "withdraw"
        cfa_transition "withdraw" || cfa_set "WITHDRAWN"
        echo -e "  ${C_DIM}CfA: WORK_ASSERT → withdraw → WITHDRAWN${C_RESET}" >&2
        session_log STATE "WORK_ASSERT → withdraw → WITHDRAWN (legacy)"
        exit 1
        ;;
    esac
  else
    # Fallback: treat raw input as work correction
    cfa_transition "correct" || cfa_set "TASK_RESPONSE"
    session_log STATE "WORK_ASSERT → correct → TASK_RESPONSE (legacy, fallback)"
    proxy_record "WORK_ASSERT" "correct" "$CFA_RESPONSE"
    LEGACY_CORRECTION_MSG="Apply this correction to the work: $CFA_RESPONSE"
  fi
done

python3 "$SCRIPT_DIR/extract_result.py" < "$EXEC_STREAM"

chrome_header "done"
chrome_beep
