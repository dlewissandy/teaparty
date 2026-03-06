#!/usr/bin/env bash
# chrome.sh — Shared visual primitives for the POC CLI.
# Source this file: source "$SCRIPT_DIR/chrome.sh"

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
  python3 -u "$SCRIPT_DIR/session_stream_logger.py" "${args[@]}"
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
