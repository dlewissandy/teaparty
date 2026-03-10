#!/usr/bin/env bash
# ui.sh — Shared terminal UI primitives for the POC CLI.
# Source this file: source "$SCRIPT_DIR/ui.sh"

# ── Width ──
CHROME_WIDTH=60

# ── ANSI Colors ──
C_RESET='\033[0m'
C_DIM='\033[2m'
C_BOLD='\033[1m'
C_CYAN='\033[36m'       # agent names
C_GREEN='\033[32m'      # user / success
C_YELLOW='\033[33m'     # phase indicators
C_RED='\033[31m'        # errors

# ── Session Chat Log ──
# Writes structured, timestamped entries to $SESSION_LOG (set by run.sh).
# Categories: SESSION, STATE, HUMAN, AGENT, PROXY, DISPATCH
session_log() {
  local category="$1"; shift
  local message="$*"
  printf '[%s] %-8s | %s\n' "$(date +%H:%M:%S)" "$category" "$message" \
    >> "${SESSION_LOG:-/dev/null}"
}

# Session stream logger — pipes JSONL agent output into session.log.
# Usage: ... | tee >(session_stream_log [prefix])
session_stream_log() {
  local prefix="${1:-}"
  local args=(--session-log "${SESSION_LOG:-/dev/null}")
  [[ -n "$prefix" ]] && args+=(--prefix "$prefix")
  python3 -u "$SCRIPT_DIR/stream/session_logger.py" "${args[@]}"
}

# ── Box Drawing ──

chrome_heavy_line() {
  local line
  line=$(printf '%*s' "$CHROME_WIDTH" '' | tr ' ' '━')
  echo -e "$line" >&2
}

chrome_header() {
  # Phase separator: ── PHASE ─────────────────
  local label="$1"
  local pad_len=$(( CHROME_WIDTH - ${#label} - 5 ))
  [[ $pad_len -lt 2 ]] && pad_len=2
  local pad
  pad=$(printf '%*s' "$pad_len" '' | tr ' ' '─')
  echo "" >&2
  echo -e "${C_YELLOW}── ${label} ${pad}${C_RESET}" >&2
  session_log SESSION "-- $label --"
}

chrome_banner() {
  # Heavy box for major sections
  local title="$1"
  local subtitle="${2:-}"
  echo "" >&2
  chrome_heavy_line
  echo -e "  ${C_BOLD}${title}${C_RESET}" >&2
  [[ -n "$subtitle" ]] && echo -e "  ${C_DIM}${subtitle}${C_RESET}" >&2
  chrome_heavy_line
  echo "" >&2
}

# ── Audio ──

chrome_beep() {
  printf '\a' >&2
}

# ── Agent / User Display ──

chrome_user() {
  # Echo back what the user typed
  local text="$1"
  echo -e "${C_GREEN}[you]:${C_RESET} ${text}" >&2
}

chrome_thinking() {
  echo -e "  ${C_DIM}[thinking...]${C_RESET}" >&2
}

# ── Prompts ──

chrome_prompt() {
  # Beep + colored prompt, reads into named variable
  # Usage: chrome_prompt VARNAME
  local varname="$1"
  chrome_beep
  echo "" >&2
  read -p "$(echo -e "${C_GREEN}[you]${C_RESET} > ")" "$varname" </dev/tty
  session_log HUMAN "${!varname}"
}

chrome_approval() {
  # Approval prompt with clear labeled options
  # Usage: chrome_approval VARNAME
  local varname="$1"
  chrome_beep
  echo "" >&2
  echo -e "  ${C_YELLOW}(y)${C_RESET} approve   ${C_YELLOW}(n)${C_RESET} reject   ${C_YELLOW}(e)${C_RESET} edit   ${C_YELLOW}(w)${C_RESET} withdraw" >&2
  read -p "$(echo -e "${C_GREEN}[you]${C_RESET} > ")" "$varname" </dev/tty
  session_log HUMAN "${!varname}"
}

# ── Conversational Bridge ──

# ── Natural Language Review Classification ──

# Sets REVIEW_ACTION and REVIEW_FEEDBACK for the caller.
# Returns 0 on success, 1 when fallback to old menu is needed.
classify_review() {
  local state="$1" response="$2"
  local intent_summary="${3:-}" plan_summary="${4:-}"
  local dialog_history="${5:-}"
  local args=(--state "$state" --response "$response")
  [[ -n "$intent_summary" ]] && args+=(--intent-summary "$intent_summary")
  [[ -n "$plan_summary" ]] && args+=(--plan-summary "$plan_summary")
  [[ -n "$dialog_history" ]] && args+=(--dialog-history "$dialog_history")
  local raw
  raw=$(python3 "$SCRIPT_DIR/scripts/classify_review.py" \
    "${args[@]}" 2>/dev/null) || { REVIEW_ACTION="__fallback__"; return 1; }
  REVIEW_ACTION=$(printf '%s' "$raw" | cut -f1)
  REVIEW_FEEDBACK=$(printf '%s' "$raw" | cut -f2-)
  [[ "$REVIEW_ACTION" == "__fallback__" ]] && return 1
  return 0
}

# ── Dialog Response Generator ──

# Generates agent-voice response to human question during review dialog.
# Sets DIALOG_REPLY for the caller.
dialog_response() {
  local state="$1" question="$2"
  local artifact="${3:-}" exec_stream="${4:-}"
  local task="${5:-}" dialog_history="${6:-}"
  local args=(--state "$state" --question "$question")
  [[ -n "$artifact" ]]       && args+=(--artifact "$artifact")
  [[ -n "$exec_stream" ]]    && args+=(--exec-stream "$exec_stream")
  [[ -n "$task" ]]           && args+=(--task "$task")
  [[ -n "$dialog_history" ]] && args+=(--dialog-history "$dialog_history")
  DIALOG_REPLY=$(python3 "$SCRIPT_DIR/scripts/generate_dialog_response.py" \
    "${args[@]}" 2>/dev/null) || \
    DIALOG_REPLY="I'm not sure I can answer that. Could you rephrase, or let me know your decision?"
}

chrome_dialog_reply() {
  echo -e "  ${C_CYAN}[agent]${C_RESET} $1" >&2
  session_log AGENT "$1"
}

# ── CfA Review Loop ──

# Dialog-capable review prompt. Loops until the human makes a non-dialog decision.
# Handles dialog turns internally (question → agent response → re-prompt).
#
# Usage: cfa_review_loop STATE [INTENT_SUMMARY] [PLAN_SUMMARY] [ARTIFACT] [EXEC_STREAM] [TASK]
#
# On return, these globals are set:
#   CFA_RESPONSE    — the human's final response text
#   REVIEW_ACTION   — classified action (from classify_review)
#   REVIEW_FEEDBACK — extracted feedback (from classify_review)
#
# Returns 0 if classification succeeded, 1 if fallback needed.
cfa_review_loop() {
  local state="$1"
  local intent_summary="${2:-}"
  local plan_summary="${3:-}"
  local artifact="${4:-}"
  local exec_stream="${5:-}"
  local task="${6:-}"

  local dialog_hist
  dialog_hist=$(mktemp)
  local classify_ok=1

  CFA_RESPONSE=""
  REVIEW_DIALOG_HISTORY=""

  while true; do
    chrome_prompt CFA_RESPONSE

    local dh=""
    [[ -s "$dialog_hist" ]] && dh=$(cat "$dialog_hist")

    if classify_review "$state" "$CFA_RESPONSE" "$intent_summary" "$plan_summary" "$dh"; then
      classify_ok=0
      if [[ "$REVIEW_ACTION" == "dialog" ]]; then
        echo "HUMAN: $CFA_RESPONSE" >> "$dialog_hist"
        dialog_response "$state" "$CFA_RESPONSE" "$artifact" "$exec_stream" "$task" "$dh"
        chrome_dialog_reply "$DIALOG_REPLY"
        echo "AGENT: $DIALOG_REPLY" >> "$dialog_hist"
        # Trim history at 4000 chars
        if [[ $(wc -c < "$dialog_hist") -gt 4000 ]]; then
          tail -c 4000 "$dialog_hist" > "${dialog_hist}.tmp"
          mv "${dialog_hist}.tmp" "$dialog_hist"
        fi
        continue
      fi
    else
      classify_ok=1
    fi
    break
  done

  # Log final decision to session log
  if [[ $classify_ok -eq 0 ]]; then
    session_log HUMAN "Decision: $REVIEW_ACTION${REVIEW_FEEDBACK:+ -- $REVIEW_FEEDBACK}"
  else
    session_log HUMAN "Response: $CFA_RESPONSE"
  fi

  # Preserve dialog history for correction feedback — the agent that
  # produced the artifact never participated in this dialog and needs
  # the full exchange to understand the correction.
  REVIEW_DIALOG_HISTORY=""
  if [[ $classify_ok -eq 0 && "$REVIEW_ACTION" == "correct" && -s "$dialog_hist" ]]; then
    REVIEW_DIALOG_HISTORY=$(cat "$dialog_hist")
  fi

  rm -f "$dialog_hist"
  return $classify_ok
}

chrome_bridge() {
  # Replace document dumps with LLM-generated conversational summaries.
  # Falls back to path + first 5 lines if LLM unavailable.
  # Usage: chrome_bridge <file_path> <cfa_state> [task]
  local file_path="$1" cfa_state="$2" task="${3:-}"
  local bridge
  bridge=$(python3 "$SCRIPT_DIR/scripts/generate_review_bridge.py" \
    --file "$file_path" --state "$cfa_state" \
    ${task:+--task "$task"} 2>/dev/null) || bridge=""
  if [[ -n "$bridge" ]]; then
    echo -e "\n  ${C_DIM}${bridge}${C_RESET}\n" >&2
    session_log AGENT "[$cfa_state] ${bridge:0:200}"
  else
    echo -e "\n  ${C_DIM}Review: ${file_path}${C_RESET}" >&2
    head -5 "$file_path" >&2
    echo -e "  ${C_DIM}...${C_RESET}\n" >&2
    session_log AGENT "[$cfa_state] Review: $(basename "$file_path")"
  fi
}

# ── Failure Handling ──

# Extract a concise failure summary from stream + exit code + sentinels.
# Usage: extract_failure STREAM_FILE EXIT_CODE [STREAM_TARGET]
# Prints markdown summary to stdout.
extract_failure() {
  local stream_file="$1"
  local exit_code="$2"
  local stream_target="${3:-$(dirname "$stream_file")}"
  local parts=()

  # Exit code
  if [[ $exit_code -ne 0 ]]; then
    parts+=("Process exited with code $exit_code")
  fi

  # Stall watchdog sentinel
  if [[ -f "$stream_target/.failure-reason" ]]; then
    local reason
    reason=$(cat "$stream_target/.failure-reason")
    parts+=("Failure reason: $reason")
  fi

  # Scan stream for error events and is_error blocks (last 5)
  if [[ -f "$stream_file" && -s "$stream_file" ]]; then
    local stream_errors
    stream_errors=$(python3 -c "
import json, sys
errors = []
for line in open(sys.argv[1]):
    try:
        ev = json.loads(line.strip())
    except: continue
    # Error result blocks
    if ev.get('type') == 'result' and ev.get('is_error'):
        errors.append(ev.get('error', 'unknown error'))
    # Tool use errors
    for b in ev.get('message', {}).get('content', []):
        if isinstance(b, dict) and b.get('is_error'):
            t = b.get('text', '') or b.get('content', '')
            if t: errors.append(t.strip()[:200])
for e in errors[-5:]:
    print(e)
" "$stream_file" 2>/dev/null || true)
    if [[ -n "$stream_errors" ]]; then
      parts+=("Stream errors:")
      while IFS= read -r err; do
        parts+=("  - $err")
      done <<< "$stream_errors"
    fi
  elif [[ ! -s "$stream_file" ]]; then
    parts+=("Process produced no output")
  fi

  if [[ ${#parts[@]} -eq 0 ]]; then
    parts+=("Process failed (no details available)")
  fi

  printf '%s\n' "${parts[@]}"
}

# Present a failure to the human/proxy and collect a decision.
# Sets FAILURE_ACTION for the caller: retry | escalate | backtrack | withdraw
#
# Usage: cfa_failure_decision FAILURE_SUMMARY [PHASE]
#   PHASE: "intent" | "planning" | "execution" (default)
#   - intent: only retry | withdraw (nothing upstream)
#   - planning: retry | backtrack | withdraw (backtrack = re-enter intent)
#   - execution: retry | escalate | backtrack | withdraw
cfa_failure_decision() {
  local failure_summary="$1"
  local phase="${2:-execution}"

  chrome_header "FAILURE — process did not complete"
  echo -e "  ${C_RED}${failure_summary}${C_RESET}" >&2
  session_log STATE "FAILURE during $phase phase"

  # Consult proxy — auto-retry for transient failures
  local proxy_action
  proxy_action=$(proxy_decide "FAILURE" 2>/dev/null || echo "escalate")
  session_log PROXY "FAILURE proxy=$proxy_action"
  if [[ "$proxy_action" == "auto-approve" ]]; then
    echo -e "  ${C_DIM}Human proxy: auto-retrying (transient failure)${C_RESET}" >&2
    session_log STATE "FAILURE → retry (proxy auto-retry)"
    FAILURE_ACTION="retry"
    return
  fi

  # Build options based on phase
  local options
  case "$phase" in
    intent)   options="retry, withdraw" ;;
    planning) options="retry, backtrack to intent, withdraw" ;;
    *)        options="retry, escalate, backtrack to planning, withdraw" ;;
  esac
  echo -e "  ${C_DIM}Options: ${options}${C_RESET}" >&2
  chrome_heavy_line

  # Human decision via classify_review
  chrome_prompt CFA_RESPONSE

  if classify_review "FAILURE" "$CFA_RESPONSE"; then
    FAILURE_ACTION="$REVIEW_ACTION"
  else
    # Fallback: default to retry
    FAILURE_ACTION="retry"
  fi

  # Validate action is valid for this phase
  case "$phase" in
    intent)
      [[ "$FAILURE_ACTION" == "retry" || "$FAILURE_ACTION" == "withdraw" ]] || FAILURE_ACTION="retry"
      ;;
    planning)
      [[ "$FAILURE_ACTION" == "retry" || "$FAILURE_ACTION" == "backtrack" || "$FAILURE_ACTION" == "withdraw" ]] || FAILURE_ACTION="retry"
      ;;
    # execution: all actions valid
  esac

  session_log HUMAN "Failure decision: $FAILURE_ACTION"
}

# Generate a structured failure report to the session directory.
# Produces .failure-report.md with evidence pointers (file + line numbers),
# not embedded error text.  Called alongside extract_failure, before
# cfa_failure_decision.
#
# Usage: generate_failure_report STREAM_FILE PHASE AGENT_NAME
#   Uses env: STREAM_TARGET, TASK, CLAUDE_EXIT
generate_failure_report() {
  local stream_file="$1" phase="$2" agent_name="$3"
  local session_dir="${STREAM_TARGET:-$(dirname "$stream_file")}"
  python3 "$SCRIPT_DIR/scripts/generate_failure_report.py" \
      --session-dir "$session_dir" \
      --stream "$stream_file" \
      --phase "$phase" \
      --agent "$agent_name" \
      --exit-code "${CLAUDE_EXIT:-1}" \
      --task "${TASK:-unknown}" \
      2>/dev/null || true
  if [[ -f "$session_dir/.failure-report.md" ]]; then
    echo -e "  ${C_DIM}Report: $session_dir/.failure-report.md${C_RESET}" >&2
    session_log STATE "Failure report: $session_dir/.failure-report.md"
  fi
}

# ── CfA State Helpers ──

# Validated transition: checks the action is legal from the current state.
# Returns 0 on success, 1 on failure.
cfa_transition() {
  local action="$1"
  if [[ -n "${CFA_STATE_FILE:-}" && -f "${CFA_STATE_FILE:-}" ]]; then
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
  if [[ -n "${CFA_STATE_FILE:-}" && -f "${CFA_STATE_FILE:-}" ]]; then
    python3 "$SCRIPT_DIR/scripts/cfa_state.py" --set-state \
      --state-file "$CFA_STATE_FILE" --target "$target" 2>/dev/null || true
  fi
}

# ── Approval Gate Helpers ──

# Queries the approval gate to decide whether to auto-approve or escalate.
# Returns "auto-approve" or "escalate" on stdout.
proxy_decide() {
  local state="$1"
  local artifact="${2:-}"
  local task_type="${POC_PROJECT:-default}"
  if [[ -n "${PROXY_MODEL:-}" && -f "${PROXY_MODEL:-}" ]]; then
    python3 "$SCRIPT_DIR/scripts/human_proxy.py" \
      --decide --state "$state" --task-type "$task_type" \
      --model "$PROXY_MODEL" \
      ${artifact:+--artifact "$artifact"} \
      2>/dev/null || echo "escalate"
  else
    echo "escalate"
  fi
}

# Records outcome to the human proxy model.
# Usage: proxy_record STATE OUTCOME [DIFF_SUMMARY [ARTIFACT_PATH [CONVERSATION_TEXT]]]
proxy_record() {
  local state="$1" outcome="$2"
  local diff_summary="${3:-}"
  local artifact="${4:-}"
  local conversation_text="${5:-}"
  local task_type="${POC_PROJECT:-default}"
  if [[ -n "${PROXY_MODEL:-}" ]]; then
    local diff_args=()
    [[ -n "$diff_summary" ]]       && diff_args=(--diff "$diff_summary")
    local artifact_args=()
    [[ -n "$artifact" ]]           && artifact_args=(--artifact "$artifact")
    local conv_args=()
    [[ -n "$conversation_text" ]]  && conv_args=(--conversation "$conversation_text")
    python3 "$SCRIPT_DIR/scripts/human_proxy.py" \
      --record --state "$state" --task-type "$task_type" \
      --outcome "$outcome" \
      ${diff_args[@]+"${diff_args[@]}"} \
      ${artifact_args[@]+"${artifact_args[@]}"} \
      ${conv_args[@]+"${conv_args[@]}"} \
      --model "$PROXY_MODEL" 2>/dev/null || true
  fi
}
