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
  else
    echo -e "\n  ${C_DIM}Review: ${file_path}${C_RESET}" >&2
    head -5 "$file_path" >&2
    echo -e "  ${C_DIM}...${C_RESET}\n" >&2
  fi
}
