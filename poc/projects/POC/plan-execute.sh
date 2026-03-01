#!/usr/bin/env bash
# plan-execute.sh — Plan-then-execute lifecycle for agent teams.
#
# Works at both levels:
#   Uber:    plan-execute.sh --agents "$JSON" --agent project-lead "Design a book"
#   Subteam: plan-execute.sh --agents "$JSON" --agent art-lead --auto-approve "Create diagrams"
#
# Flow:
#   1. Plan  — claude -p --permission-mode plan (agent plans, calls ExitPlanMode)
#   2. Approve — human gate (or --auto-approve for subteams)
#   3. Execute — claude -p --resume $SESSION_ID (agent executes the plan)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/chrome.sh"

# Defaults
AGENTS_JSON=""
LEAD=""
AUTO_APPROVE=false
SETTINGS_FILE=""
PLAN_TURNS=15
EXEC_TURNS=30
CWD=""
ADD_DIR=""
FILTER_PREFIX=""
STREAM_DIR=""
TASK=""

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --agents)        AGENTS_JSON="$2"; shift 2 ;;
    --agent)         LEAD="$2"; shift 2 ;;
    --auto-approve)  AUTO_APPROVE=true; shift ;;
    --settings)      SETTINGS_FILE="$2"; shift 2 ;;
    --plan-turns)    PLAN_TURNS="$2"; shift 2 ;;
    --exec-turns)    EXEC_TURNS="$2"; shift 2 ;;
    --cwd)           CWD="$2"; shift 2 ;;
    --add-dir)       ADD_DIR="$2"; shift 2 ;;
    --stream-dir)    STREAM_DIR="$2"; shift 2 ;;
    --filter-prefix) FILTER_PREFIX="$2"; shift 2 ;;
    -*)              echo "Unknown option: $1" >&2; exit 1 ;;
    *)               TASK="$1"; shift ;;
  esac
done

[[ -z "$TASK" ]] && { echo "Usage: plan-execute.sh [options] <task>" >&2; exit 1; }

# Build common claude args
CLAUDE_ARGS=(-p --output-format stream-json --verbose --setting-sources user)
[[ -n "$AGENTS_JSON" ]]   && CLAUDE_ARGS+=(--agents "$AGENTS_JSON")
[[ -n "$LEAD" ]]           && CLAUDE_ARGS+=(--agent "$LEAD")
[[ -n "$SETTINGS_FILE" ]]  && CLAUDE_ARGS+=(--settings "$SETTINGS_FILE")
[[ -n "$ADD_DIR" ]]        && CLAUDE_ARGS+=(--add-dir "$ADD_DIR")

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

# ── Stall watchdog ──
# Claude Code can spawn `tail -f <task-output> | head -N` as Bash tool calls.
# When the task output file is deleted, tail -f blocks forever, deadlocking the
# entire pipeline (claude → FIFO → cat|tee → plan-execute → relay → uber claude).
# The watchdog monitors stream file mtime and kills the claude process tree if
# no output is produced for STALL_TIMEOUT seconds with no active dispatches.
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
  # Grace period: let claude start up before checking
  sleep 120
  while kill -0 "$pid" 2>/dev/null; do
    sleep 60
    # Stream mtime check (macOS stat -f%m, Linux stat -c%Y)
    local mtime now age
    mtime=$(stat -f%m "$stream" 2>/dev/null || stat -c%Y "$stream" 2>/dev/null || echo 0)
    now=$(date +%s)
    age=$(( now - mtime ))
    if [[ $age -ge $STALL_TIMEOUT ]]; then
      # Check for active dispatches before killing — a running dispatch
      # means claude is legitimately waiting for a relay.sh result.
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

# Stream filter — appends to shared conversation log if set, otherwise stderr.
# CONVERSATION_LOG env var is set by run.sh and inherited through relay.sh.
filter_stream() {
  local dest="${CONVERSATION_LOG:-/dev/stderr}"
  if [[ -n "$FILTER_PREFIX" ]]; then
    python3 -u "$SCRIPT_DIR/stream_filter.py" | sed -u "s/^/$FILTER_PREFIX/" >> "$dest"
  else
    python3 -u "$SCRIPT_DIR/stream_filter.py" >> "$dest"
  fi
}

# Extract session ID from stream-json init event
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

# Run claude, capture stream output, wait for natural exit.
# Uses a named pipe so stream is observable via tee while claude runs.
# $1 = stream output file, $2 = task input text, remaining args passed to claude.
run_claude() {
  local stream_file="$1"; shift
  local task_input="$1"; shift

  local fifo
  fifo=$(mktemp -u).fifo
  mkfifo "$fifo"

  # Claude writes to FIFO in background
  (cd "$WORK_DIR" && echo "$task_input" | claude "${CLAUDE_ARGS[@]}" "$@" > "$fifo") &
  local bg_pid=$!

  # Start stall watchdog — kills claude if stream goes stale
  stall_watchdog "$bg_pid" "$stream_file" &
  local watchdog_pid=$!

  # Read until claude exits (EOF on FIFO)
  cat < "$fifo" \
    | tee "$stream_file" \
    | tee >(filter_stream) > /dev/null

  wait "$bg_pid" 2>/dev/null || true

  # Stop the watchdog
  kill "$watchdog_pid" 2>/dev/null || true
  wait "$watchdog_pid" 2>/dev/null || true

  rm -f "$fifo"
}

# ── Phase 1: Plan ──
chrome_header "PLAN"

# Snapshot ~/.claude/plans/ before plan phase so we can relocate any new plan files
PLANS_BEFORE=$(mktemp)
ls ~/.claude/plans/ 2>/dev/null | sort > "$PLANS_BEFORE" || true

run_claude "$PLAN_STREAM" "$TASK" \
  --permission-mode plan --max-turns "$PLAN_TURNS"

SESSION_ID=$(extract_session_id < "$PLAN_STREAM")

if [[ -z "$SESSION_ID" ]]; then
  echo -e "  ${C_RED}Could not extract session ID from plan output${C_RESET}" >&2
  exit 1
fi

echo -e "  ${C_DIM}plan complete (session: ${SESSION_ID:0:8}...)${C_RESET}" >&2

# Relocate plan files that Claude Code wrote to ~/.claude/plans/ back into stream target dir
PLANS_AFTER=$(mktemp)
ls ~/.claude/plans/ 2>/dev/null | sort > "$PLANS_AFTER" || true
NEW_PLANS=$(comm -13 "$PLANS_BEFORE" "$PLANS_AFTER" || true)
for plan in $NEW_PLANS; do
  mv ~/.claude/plans/"$plan" "$STREAM_TARGET/plan.md"
  echo -e "  ${C_DIM}Relocated plan: $plan${C_RESET}" >&2
  break  # Only one plan expected per session
done
rm -f "$PLANS_BEFORE" "$PLANS_AFTER"

# ── Phase 2: Approve ──
PLAN_FILE="$STREAM_TARGET/plan.md"

if [[ "$AUTO_APPROVE" != "true" ]]; then
  chrome_header "APPROVE"

  if [[ -f "$PLAN_FILE" ]]; then
    chrome_banner "Plan"
    cat "$PLAN_FILE" >&2
    echo "" >&2
    chrome_heavy_line
  else
    # No plan.md written — extract plan from result
    chrome_banner "Plan"
    python3 "$SCRIPT_DIR/extract_result.py" < "$PLAN_STREAM" >&2
    echo "" >&2
    chrome_heavy_line
  fi

  chrome_approval approval
  case "$approval" in
    n|N) echo -e "  ${C_YELLOW}Aborted.${C_RESET}" >&2; exit 0 ;;
    e|E) ${EDITOR:-vim} "$PLAN_FILE" ;;
  esac
fi

# ── Phase 3: Execute ──
chrome_header "EXECUTE"

run_claude "$EXEC_STREAM" "Execute the plan." \
  --resume "$SESSION_ID" --permission-mode acceptEdits --max-turns "$EXEC_TURNS"

# Output the final result to stdout (for relay.sh to capture)
python3 "$SCRIPT_DIR/extract_result.py" < "$EXEC_STREAM"

chrome_header "done"
chrome_beep
