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
PLAN_TURNS=15
EXEC_TURNS=30
CWD=""
ADD_DIR=""
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
    --plan-turns)      PLAN_TURNS="$2"; shift 2 ;;
    --exec-turns)      EXEC_TURNS="$2"; shift 2 ;;
    --cwd)             CWD="$2"; shift 2 ;;
    --add-dir)         ADD_DIR="$2"; shift 2 ;;
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
[[ -n "$ADD_DIR" ]]        && CLAUDE_ARGS+=(--add-dir "$ADD_DIR")

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
    | tee >(filter_stream) > /dev/null

  wait "$bg_pid" 2>/dev/null || true

  kill "$watchdog_pid" 2>/dev/null || true
  wait "$watchdog_pid" 2>/dev/null || true

  rm -f "$fifo"
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
  cfa_set "TASK"  # Agent runs autonomously through TASK → TASK_IN_PROGRESS → ...

  EXEC_SESSION_ID="$RESUME_SESSION"
  CORRECTION_MSG=""

  # ── Execution loop: run → review → (correct → re-run) or (exit) ──
  # Per spec: WORK_ASSERT correct → TASK_RESPONSE → agent fixes → WORK_ASSERT
  while true; do
    if [[ -n "$CORRECTION_MSG" && -n "$EXEC_SESSION_ID" ]]; then
      # Correction round: resume agent with feedback (TASK_RESPONSE → TASK_IN_PROGRESS)
      cfa_set "TASK_IN_PROGRESS"
      run_claude "$EXEC_STREAM" "$CORRECTION_MSG" \
        --resume "$EXEC_SESSION_ID" --permission-mode acceptEdits --max-turns "$EXEC_TURNS"
    elif [[ -n "$EXEC_SESSION_ID" ]]; then
      run_claude "$EXEC_STREAM" "Execute the plan." \
        --resume "$EXEC_SESSION_ID" --permission-mode acceptEdits --max-turns "$EXEC_TURNS"
    else
      run_claude "$EXEC_STREAM" "$TASK" \
        --permission-mode acceptEdits --max-turns "$EXEC_TURNS"
    fi

    # Extract session ID for correction rounds
    if [[ -z "$EXEC_SESSION_ID" ]]; then
      EXEC_SESSION_ID=$(extract_session_id < "$EXEC_STREAM")
    fi

    # ── Check for execution escalation (TASK_ESCALATE) ──
    TASK_ESCALATION="$STREAM_TARGET/.task-escalation.md"
    if [[ -f "$TASK_ESCALATION" ]]; then
      cfa_set "TASK_ESCALATE"
      chrome_header "TASK_ESCALATE — agent needs clarification"
      chrome_bridge "$TASK_ESCALATION" "TASK_ESCALATE" "$TASK"
      chrome_heavy_line

      if [[ "$AGENT_MODE" == "true" ]]; then
        cp "$TASK_ESCALATION" "$BACKTRACK_FEEDBACK"
        rm -f "$TASK_ESCALATION"
        exit 11
      fi

      echo -e "  ${C_DIM}Answer the question above, or (w)ithdraw:${C_RESET}" >&2
      read -p "$(echo -e "${C_GREEN}[you]${C_RESET} > ")" task_clarification </dev/tty

      if [[ "$task_clarification" == "w" || "$task_clarification" == "W" ]]; then
        proxy_record "TASK_ESCALATE" "withdraw"
        cfa_transition "withdraw" || cfa_set "WITHDRAWN"
        rm -f "$TASK_ESCALATION"
        exit 1
      fi

      proxy_record "TASK_ESCALATE" "clarify" "$task_clarification"
      cfa_transition "clarify" || cfa_set "TASK_RESPONSE"
      echo -e "  ${C_DIM}CfA: TASK_ESCALATE → clarify → TASK_RESPONSE → TASK_IN_PROGRESS${C_RESET}" >&2
      rm -f "$TASK_ESCALATION"
      cfa_set "TASK_IN_PROGRESS"
      CORRECTION_MSG="Human clarification: $task_clarification"
      continue  # Re-enter execution loop with clarification
    fi

    # ── WORK_ASSERT: human/proxy reviews the work ──
    cfa_set "WORK_ASSERT"  # Agent completed: WORK_IN_PROGRESS → assert → WORK_ASSERT
    chrome_header "WORK_ASSERT (CfA Phase 3 — human reviews deliverable)"
    PROXY_ACTION=$(proxy_decide "WORK_ASSERT")

    if [[ "$PROXY_ACTION" == "auto-approve" ]]; then
      echo -e "  ${C_DIM}CfA: WORK_ASSERT → approve → COMPLETED_WORK (proxy auto-approved)${C_RESET}" >&2
      proxy_record "WORK_ASSERT" "approve"
      cfa_transition "approve" || cfa_set "COMPLETED_WORK"
      break
    elif [[ "$AGENT_MODE" == "true" ]]; then
      # Agent mode: escalate to outer scope — Execution Lead is our "human"
      echo "Work requires review — proxy not confident enough to auto-approve" > "$BACKTRACK_FEEDBACK"
      exit 11  # work escalation
    fi

    # Interactive review
    while true; do
      echo -e "  ${C_DIM}Review the work. Options:${C_RESET}" >&2
      echo -e "  ${C_DIM}  (y) approve — work complete${C_RESET}" >&2
      echo -e "  ${C_DIM}  (c) correct — targeted fix (agent re-executes)${C_RESET}" >&2
      echo -e "  ${C_DIM}  (p) revise plan — rework needed (backtrack to planning)${C_RESET}" >&2
      echo -e "  ${C_DIM}  (i) refine intent — scope/intent misalignment (backtrack to intent)${C_RESET}" >&2
      echo -e "  ${C_DIM}  (n) withdraw${C_RESET}" >&2

      read -p "$(echo -e "${C_GREEN}[you]${C_RESET} > ")" work_review </dev/tty || work_review="y"
      case "$work_review" in
        y|Y)
          proxy_record "WORK_ASSERT" "approve"
          cfa_transition "approve" || cfa_set "COMPLETED_WORK"
          echo -e "  ${C_DIM}CfA: WORK_ASSERT → approve → COMPLETED_WORK${C_RESET}" >&2
          break 2  # Exit both loops — work complete
          ;;
        c|C)
          cfa_transition "correct" || cfa_set "TASK_RESPONSE"
          echo -e "  ${C_DIM}CfA: WORK_ASSERT → correct → TASK_RESPONSE${C_RESET}" >&2
          echo -e "  ${C_DIM}Describe the correction:${C_RESET}" >&2
          read -p "$(echo -e "${C_GREEN}[you]${C_RESET} > ")" correction </dev/tty || correction=""
          proxy_record "WORK_ASSERT" "correct" "$correction"
          CORRECTION_MSG="Apply this correction to the work: $correction"
          break  # Exit inner loop → re-enter outer loop (agent fixes)
          ;;
        p|P)
          cfa_transition "revise-plan" || cfa_set "PLANNING_RESPONSE"
          echo -e "  ${C_DIM}CfA: WORK_ASSERT → revise-plan → PLANNING_RESPONSE (cross-phase backtrack)${C_RESET}" >&2
          echo -e "  ${C_DIM}What needs replanning:${C_RESET}" >&2
          read -p "$(echo -e "${C_GREEN}[you]${C_RESET} > ")" replan_reason </dev/tty || replan_reason=""
          proxy_record "WORK_ASSERT" "correct" "$replan_reason"
          echo "$replan_reason" > "$BACKTRACK_FEEDBACK"
          exit 3
          ;;
        i|I)
          cfa_transition "refine-intent" || cfa_set "INTENT_RESPONSE"
          echo -e "  ${C_DIM}CfA: WORK_ASSERT → refine-intent → INTENT_RESPONSE (cross-phase backtrack)${C_RESET}" >&2
          echo -e "  ${C_DIM}Describe the intent misalignment:${C_RESET}" >&2
          read -p "$(echo -e "${C_GREEN}[you]${C_RESET} > ")" intent_issue </dev/tty || intent_issue=""
          proxy_record "WORK_ASSERT" "correct" "$intent_issue"
          echo "$intent_issue" > "$BACKTRACK_FEEDBACK"
          exit 2
          ;;
        n|N)
          proxy_record "WORK_ASSERT" "withdraw"
          cfa_transition "withdraw" || cfa_set "WITHDRAWN"
          echo -e "  ${C_DIM}CfA: WORK_ASSERT → withdraw → WITHDRAWN${C_RESET}" >&2
          exit 1
          ;;
        *)
          echo -e "  ${C_YELLOW}Unrecognized option: '$work_review'. Try y/c/p/i/n.${C_RESET}" >&2
          continue
          ;;
      esac
    done
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
  cfa_set "DRAFT"  # Agent runs autonomously through DRAFT (planning)

  PLANS_BEFORE=$(mktemp)
  ls ~/.claude/plans/ 2>/dev/null | sort > "$PLANS_BEFORE" || true

  run_claude "$PLAN_STREAM" "$TASK" \
    --permission-mode plan --max-turns "$PLAN_TURNS"

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

    echo -e "  ${C_DIM}Answer the questions above, or (w)ithdraw:${C_RESET}" >&2
    read -p "$(echo -e "${C_GREEN}[you]${C_RESET} > ")" plan_clarification </dev/tty

    if [[ "$plan_clarification" == "w" || "$plan_clarification" == "W" ]]; then
      proxy_record "PLANNING_ESCALATE" "withdraw"
      cfa_transition "withdraw" || cfa_set "WITHDRAWN"
      rm -f "$PLAN_ESCALATION"
      exit 1
    fi

    proxy_record "PLANNING_ESCALATE" "clarify" "$plan_clarification"
    cfa_transition "clarify" || cfa_set "PLANNING_RESPONSE"
    echo -e "  ${C_DIM}CfA: PLANNING_ESCALATE → clarify → PLANNING_RESPONSE → synthesize → DRAFT${C_RESET}" >&2
    rm -f "$PLAN_ESCALATION"
    cfa_set "DRAFT"
    run_claude "$PLAN_STREAM" "Human clarification: $plan_clarification" \
      --resume "$SESSION_ID" --permission-mode plan --max-turns "$PLAN_TURNS"
  done

  cfa_set "PLAN_ASSERT"  # Agent completed planning: DRAFT → assert → PLAN_ASSERT
  echo -e "  ${C_DIM}plan complete (session: ${SESSION_ID:0:8}...)${C_RESET}" >&2

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
fi

# ── Approve phase (CfA: PLAN_ASSERT) ──
PLAN_FILE="$STREAM_TARGET/plan.md"

if [[ "$NO_PLAN" != "true" ]]; then
  # CfA plan approval loop — always consult proxy, supports revision and backtracking
  while true; do
    chrome_header "PLAN_ASSERT (CfA Phase 2 — human reviews plan)"

    # Always check human proxy confidence — no more bypassing
    PROXY_ACTION=$(proxy_decide "PLAN_ASSERT")

    if [[ "$PROXY_ACTION" == "auto-approve" ]]; then
      echo -e "  ${C_DIM}CfA: PLAN_ASSERT → approve → PLAN (proxy auto-approved)${C_RESET}" >&2
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
      local PLAN_EXTRACT
      PLAN_EXTRACT=$(mktemp)
      python3 "$SCRIPT_DIR/extract_result.py" < "$PLAN_STREAM" > "$PLAN_EXTRACT"
      chrome_banner "PLAN_ASSERT" "CfA Phase 2 — human reviews plan"
      chrome_bridge "$PLAN_EXTRACT" "PLAN_ASSERT" "$TASK"
      chrome_heavy_line
      rm -f "$PLAN_EXTRACT"
    fi

    echo -e "  ${C_DIM}Options: (y) approve  (n) reject  (e) edit  (r) re-plan  (b) backtrack to intent${C_RESET}" >&2
    read -p "$(echo -e "${C_GREEN}[you]${C_RESET} > ")" approval </dev/tty || approval="y"
    case "$approval" in
      y|Y)
        proxy_record "PLAN_ASSERT" "approve"
        cfa_transition "approve" || cfa_set "PLAN"
        echo -e "  ${C_DIM}CfA: PLAN_ASSERT → approve → PLAN${C_RESET}" >&2
        break
        ;;
      n|N)
        proxy_record "PLAN_ASSERT" "reject"
        cfa_transition "withdraw" || cfa_set "WITHDRAWN"
        echo -e "  ${C_DIM}CfA: PLAN_ASSERT → withdraw → WITHDRAWN${C_RESET}" >&2
        exit 1
        ;;
      e|E)
        ${EDITOR:-vim} "$PLAN_FILE"
        proxy_record "PLAN_ASSERT" "approve"
        cfa_transition "approve" || cfa_set "PLAN"
        echo -e "  ${C_DIM}CfA: PLAN_ASSERT → approve → PLAN (human-edited)${C_RESET}" >&2
        break  # Human-edited plan is approved (records as approve since the human accepted the result)
        ;;
      r|R)
        # Re-plan: stay within planning phase (PLAN_ASSERT → correct → PLANNING_RESPONSE → DRAFT)
        cfa_transition "correct" || cfa_set "PLANNING_RESPONSE"
        echo -e "  ${C_DIM}CfA: PLAN_ASSERT → correct → PLANNING_RESPONSE → synthesize → DRAFT${C_RESET}" >&2
        echo -e "  ${C_DIM}Describe what the plan should change:${C_RESET}" >&2
        read -p "$(echo -e "${C_GREEN}[you]${C_RESET} > ")" plan_feedback </dev/tty || plan_feedback=""
        proxy_record "PLAN_ASSERT" "correct" "$plan_feedback"
        if [[ -n "$plan_feedback" ]]; then
          echo -e "  ${C_DIM}Re-planning with feedback...${C_RESET}" >&2
          cfa_set "DRAFT"  # Agent re-enters DRAFT after receiving feedback
          run_claude "$PLAN_STREAM" "Revise the plan based on this feedback: ${plan_feedback}" \
            --resume "$SESSION_ID" --permission-mode plan --max-turns "$PLAN_TURNS"
          cfa_set "PLAN_ASSERT"  # Agent completed: back to assertion
          # Relocate new plan file if written
          NEW_PLANS=$(ls -t ~/.claude/plans/ 2>/dev/null | head -1 || true)
          [[ -n "$NEW_PLANS" ]] && mv ~/.claude/plans/"$NEW_PLANS" "$PLAN_FILE" 2>/dev/null || true
        fi
        continue  # Loop back to show revised plan
        ;;
      b|B)
        # Cross-phase backtrack to intent alignment
        cfa_set "INTENT_RESPONSE"
        echo -e "  ${C_DIM}CfA: PLAN_ASSERT → refine-intent → INTENT_RESPONSE (cross-phase backtrack)${C_RESET}" >&2
        echo -e "  ${C_DIM}What needs clarification in the intent:${C_RESET}" >&2
        read -p "$(echo -e "${C_GREEN}[you]${C_RESET} > ")" intent_feedback </dev/tty || intent_feedback=""
        proxy_record "PLAN_ASSERT" "correct" "$intent_feedback"
        echo "$intent_feedback" > "$BACKTRACK_FEEDBACK"
        exit 2  # Signal run.sh to re-enter intent phase
        ;;
      *)
        # Unrecognized input — re-prompt
        echo -e "  ${C_YELLOW}Unrecognized option: '$approval'. Try y/n/e/r/b.${C_RESET}" >&2
        continue
        ;;
    esac
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
fi

LEGACY_CORRECTION_MSG=""
LEGACY_SESSION_ID="$SESSION_ID"

while true; do
  if [[ -n "$LEGACY_CORRECTION_MSG" && -n "$LEGACY_SESSION_ID" ]]; then
    # Correction round: resume agent with feedback (TASK_RESPONSE → TASK_IN_PROGRESS)
    cfa_set "TASK_IN_PROGRESS"
    run_claude "$EXEC_STREAM" "$LEGACY_CORRECTION_MSG" \
      --resume "$LEGACY_SESSION_ID" --permission-mode acceptEdits --max-turns "$EXEC_TURNS"
  elif [[ "$NO_PLAN" == "true" ]]; then
    run_claude "$EXEC_STREAM" "$TASK" \
      --permission-mode acceptEdits --max-turns "$EXEC_TURNS"
  else
    run_claude "$EXEC_STREAM" "Execute the plan." \
      --resume "$LEGACY_SESSION_ID" --permission-mode acceptEdits --max-turns "$EXEC_TURNS"
  fi

  # Extract session ID for correction rounds
  if [[ -z "$LEGACY_SESSION_ID" ]]; then
    LEGACY_SESSION_ID=$(extract_session_id < "$EXEC_STREAM")
  fi

  # ── WORK_ASSERT: human/proxy reviews the work ──
  if [[ "$PLAN_ONLY" == "true" || "$EXECUTE_ONLY" == "true" ]]; then
    break  # Skip review in these modes (handled above)
  fi

  # ── Check for execution escalation (TASK_ESCALATE) ──
  LEGACY_TASK_ESCALATION="$STREAM_TARGET/.task-escalation.md"
  if [[ -f "$LEGACY_TASK_ESCALATION" ]]; then
    cfa_set "TASK_ESCALATE"
    chrome_header "TASK_ESCALATE — agent needs clarification"
    chrome_bridge "$LEGACY_TASK_ESCALATION" "TASK_ESCALATE" "$TASK"
    chrome_heavy_line

    if [[ "$AGENT_MODE" == "true" ]]; then
      cp "$LEGACY_TASK_ESCALATION" "$BACKTRACK_FEEDBACK"
      rm -f "$LEGACY_TASK_ESCALATION"
      exit 11
    fi

    echo -e "  ${C_DIM}Answer the question above, or (w)ithdraw:${C_RESET}" >&2
    read -p "$(echo -e "${C_GREEN}[you]${C_RESET} > ")" task_clarification </dev/tty

    if [[ "$task_clarification" == "w" || "$task_clarification" == "W" ]]; then
      proxy_record "TASK_ESCALATE" "withdraw"
      cfa_transition "withdraw" || cfa_set "WITHDRAWN"
      rm -f "$LEGACY_TASK_ESCALATION"
      exit 1
    fi

    proxy_record "TASK_ESCALATE" "clarify" "$task_clarification"
    cfa_transition "clarify" || cfa_set "TASK_RESPONSE"
    echo -e "  ${C_DIM}CfA: TASK_ESCALATE → clarify → TASK_RESPONSE → TASK_IN_PROGRESS${C_RESET}" >&2
    rm -f "$LEGACY_TASK_ESCALATION"
    cfa_set "TASK_IN_PROGRESS"
    LEGACY_CORRECTION_MSG="Human clarification: $task_clarification"
    continue  # Re-enter execution loop with clarification
  fi

  cfa_set "WORK_ASSERT"  # Agent completed: WORK_IN_PROGRESS → assert → WORK_ASSERT
  PROXY_ACTION=$(proxy_decide "WORK_ASSERT")

  if [[ "$PROXY_ACTION" == "auto-approve" ]]; then
    echo -e "  ${C_DIM}CfA: WORK_ASSERT → approve → COMPLETED_WORK (proxy auto-approved)${C_RESET}" >&2
    proxy_record "WORK_ASSERT" "approve"
    cfa_transition "approve" || cfa_set "COMPLETED_WORK"
    break
  elif [[ "$AGENT_MODE" == "true" ]]; then
    # Agent mode: escalate to outer scope — Execution Lead is our "human"
    echo "Work requires review — proxy not confident enough to auto-approve" > "$BACKTRACK_FEEDBACK"
    exit 11  # work escalation
  fi

  chrome_header "WORK_ASSERT (CfA Phase 3 — human reviews deliverable)"
  while true; do
    echo -e "  ${C_DIM}Review the work. Options:${C_RESET}" >&2
    echo -e "  ${C_DIM}  (y) approve — work complete${C_RESET}" >&2
    echo -e "  ${C_DIM}  (c) correct — targeted fix (agent re-executes)${C_RESET}" >&2
    echo -e "  ${C_DIM}  (p) revise plan — rework needed (backtrack to planning)${C_RESET}" >&2
    echo -e "  ${C_DIM}  (i) refine intent — scope/intent misalignment (backtrack to intent)${C_RESET}" >&2
    echo -e "  ${C_DIM}  (n) withdraw${C_RESET}" >&2

    read -p "$(echo -e "${C_GREEN}[you]${C_RESET} > ")" final_review </dev/tty || final_review="y"
    case "$final_review" in
      y|Y)
        proxy_record "WORK_ASSERT" "approve"
        cfa_transition "approve" || cfa_set "COMPLETED_WORK"
        echo -e "  ${C_DIM}CfA: WORK_ASSERT → approve → COMPLETED_WORK${C_RESET}" >&2
        break 2  # Exit both loops — work complete
        ;;
      c|C)
        cfa_transition "correct" || cfa_set "TASK_RESPONSE"
        echo -e "  ${C_DIM}CfA: WORK_ASSERT → correct → TASK_RESPONSE${C_RESET}" >&2
        echo -e "  ${C_DIM}Describe the correction:${C_RESET}" >&2
        read -p "$(echo -e "${C_GREEN}[you]${C_RESET} > ")" correction </dev/tty || correction=""
        proxy_record "WORK_ASSERT" "correct" "$correction"
        LEGACY_CORRECTION_MSG="Apply this correction to the work: $correction"
        break  # Exit inner loop → re-enter outer loop (agent fixes)
        ;;
      p|P)
        cfa_transition "revise-plan" || cfa_set "PLANNING_RESPONSE"
        echo -e "  ${C_DIM}CfA: WORK_ASSERT → revise-plan → PLANNING_RESPONSE (cross-phase backtrack)${C_RESET}" >&2
        echo -e "  ${C_DIM}What needs replanning:${C_RESET}" >&2
        read -p "$(echo -e "${C_GREEN}[you]${C_RESET} > ")" replan_reason </dev/tty || replan_reason=""
        proxy_record "WORK_ASSERT" "correct" "$replan_reason"
        echo "$replan_reason" > "$BACKTRACK_FEEDBACK"
        exit 3
        ;;
      i|I)
        cfa_transition "refine-intent" || cfa_set "INTENT_RESPONSE"
        echo -e "  ${C_DIM}CfA: WORK_ASSERT → refine-intent → INTENT_RESPONSE (cross-phase backtrack)${C_RESET}" >&2
        echo -e "  ${C_DIM}Describe the intent misalignment:${C_RESET}" >&2
        read -p "$(echo -e "${C_GREEN}[you]${C_RESET} > ")" intent_issue </dev/tty || intent_issue=""
        proxy_record "WORK_ASSERT" "correct" "$intent_issue"
        echo "$intent_issue" > "$BACKTRACK_FEEDBACK"
        exit 2
        ;;
      n|N)
        proxy_record "WORK_ASSERT" "withdraw"
        cfa_transition "withdraw" || cfa_set "WITHDRAWN"
        echo -e "  ${C_DIM}CfA: WORK_ASSERT → withdraw → WITHDRAWN${C_RESET}" >&2
        exit 1
        ;;
      *)
        echo -e "  ${C_YELLOW}Unrecognized option: '$final_review'. Try y/c/p/i/n.${C_RESET}" >&2
        continue
        ;;
    esac
  done
done

python3 "$SCRIPT_DIR/extract_result.py" < "$EXEC_STREAM"

chrome_header "done"
chrome_beep
