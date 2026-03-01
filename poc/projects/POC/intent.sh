#!/usr/bin/env bash
# intent.sh — Multi-turn intent gathering conversation.
#
# Conducts a dialog between the human and an intent team to produce INTENT.md.
# Uses claude -p with --resume for multi-turn conversation continuity.
# The intent-lead facilitates the dialog; the research-liaison dispatches
# research to the existing research subteam via relay.sh.
#
# Usage: intent.sh --cwd <worktree> --stream-dir <infra-dir> --task "<task>" \
#                  [--context-file <path>...]
#
# Exits 0 with INTENT.md written to CWD, or 1 if skipped/failed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/chrome.sh"

# Defaults
CWD=""
STREAM_DIR=""
TASK=""
CONTEXT_FILES=()

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --cwd)          CWD="$2"; shift 2 ;;
    --stream-dir)   STREAM_DIR="$2"; shift 2 ;;
    --task)         TASK="$2"; shift 2 ;;
    --context-file) CONTEXT_FILES+=("$2"); shift 2 ;;
    *)              echo "intent.sh: unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$CWD" ]]  && { echo "intent.sh: --cwd required" >&2; exit 1; }
[[ -z "$TASK" ]] && { echo "intent.sh: --task required" >&2; exit 1; }

# Default stream dir to CWD if not specified
STREAM_DIR="${STREAM_DIR:-$CWD}"
mkdir -p "$STREAM_DIR"

# ── Build initial prompt with warm-start context ──
INITIAL_PROMPT="Task: $TASK"

for ctx_file in "${CONTEXT_FILES[@]}"; do
  if [[ -f "$ctx_file" && -s "$ctx_file" ]]; then
    LABEL=$(basename "$ctx_file")
    DIR_LABEL=$(basename "$(dirname "$ctx_file")")
    INITIAL_PROMPT="$INITIAL_PROMPT

--- $LABEL ($DIR_LABEL) ---
$(cat "$ctx_file")
--- end $LABEL ---"
  fi
done

# ── Agent definition with path substitution ──
AGENTS_JSON=$(sed -e "s|__POC_DIR__|$SCRIPT_DIR|g" \
                  -e "s|__SESSION_DIR__|$STREAM_DIR|g" \
  "$SCRIPT_DIR/agents/intent-team.json")

# ── Settings: pre-approve tools needed by intent team ──
SETTINGS_FILE=$(mktemp)
trap "rm -f $SETTINGS_FILE" EXIT

python3 -c "
import json, os, sys
d = os.environ.get('SCRIPT_DIR', '.')
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

# ── Stream and session state ──
INTENT_STREAM="$STREAM_DIR/.intent-stream.jsonl"
> "$INTENT_STREAM"

# Common claude args
CLAUDE_ARGS=(-p --output-format stream-json --verbose --setting-sources user)
CLAUDE_ARGS+=(--agents "$AGENTS_JSON" --agent intent-lead)
CLAUDE_ARGS+=(--settings "$SETTINGS_FILE")
# No --add-dir: the intent agent only writes INTENT.md to CWD.
# Repo access is not needed — context is inlined in the prompt.

# ── Helper: find INTENT.md ──
find_intent_md() {
  if [[ -f "$CWD/INTENT.md" ]]; then
    echo "$CWD/INTENT.md"
  fi
}

# ── Helper: extract session ID from stream ──
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

# ── Helper: run one turn of the conversation ──
# Sends input to claude, streams output through intent_filter.py,
# saves raw stream to .intent-stream.jsonl (append mode).
run_turn() {
  local input="$1"
  shift
  local extra_args=("$@")

  local fifo
  fifo=$(mktemp -u).fifo
  mkfifo "$fifo"

  # Claude writes to FIFO in background
  (cd "$CWD" && echo "$input" | claude "${CLAUDE_ARGS[@]}" "${extra_args[@]}" > "$fifo") &
  local bg_pid=$!

  # Stream through filter for display, also append to stream file
  cat < "$fifo" \
    | tee -a "$INTENT_STREAM" \
    | python3 -u "$SCRIPT_DIR/intent_filter.py" --agent-name intent-lead >&2

  wait "$bg_pid" 2>/dev/null || true
  rm -f "$fifo"
}

# ── Banner ──
chrome_header "INTENT"
echo -e "  ${C_DIM}Type 'done' to finalize, 'skip' to bypass.${C_RESET}" >&2

# ── Turn 1: Initial prompt ──
chrome_thinking
run_turn "$INITIAL_PROMPT" --permission-mode acceptEdits --max-turns 3

# Extract session ID for --resume on subsequent turns
SESSION_ID=$(extract_session_id < "$INTENT_STREAM")
if [[ -z "$SESSION_ID" ]]; then
  echo -e "  ${C_RED}Could not extract session ID from intent agent${C_RESET}" >&2
  exit 1
fi

# ── Conversation loop ──
MAX_ROUNDS=10
round=0

while [[ $round -lt $MAX_ROUNDS ]]; do
  ((round++))

  # Check if INTENT.md was written (agent may write to CWD or ADD_DIR)
  INTENT_PATH=$(find_intent_md)
  if [[ -n "$INTENT_PATH" ]]; then
    chrome_banner "INTENT.md"
    cat "$INTENT_PATH" >&2
    echo "" >&2
    chrome_heavy_line

    chrome_approval approval
    case "$approval" in
      y|Y)
        echo -e "  ${C_GREEN}Intent approved.${C_RESET}" >&2
        exit 0
        ;;
      e|E)
        ${EDITOR:-vim} "$CWD/INTENT.md"
        echo -e "  ${C_GREEN}INTENT.md updated.${C_RESET}" >&2
        exit 0
        ;;
      n|N)
        # Human wants changes — get feedback
        echo -e "  ${C_DIM}What should change?${C_RESET}" >&2
        chrome_prompt feedback
        if [[ -z "$feedback" ]]; then
          echo -e "  ${C_DIM}No feedback provided. Continuing...${C_RESET}" >&2
          continue
        fi
        chrome_thinking
        run_turn "$feedback" --resume "$SESSION_ID" --permission-mode acceptEdits --max-turns 3
        continue
        ;;
      *)
        # Treat any other input as feedback
        chrome_thinking
        run_turn "$approval" --resume "$SESSION_ID" --permission-mode acceptEdits --max-turns 3
        continue
        ;;
    esac
  fi

  # No INTENT.md yet — get human input
  chrome_prompt human_input

  # Control commands
  case "$human_input" in
    skip|SKIP)
      echo -e "  ${C_YELLOW}Skipping intent gathering.${C_RESET}" >&2
      exit 1
      ;;
    done|DONE)
      echo -e "  ${C_DIM}Asking agent to finalize INTENT.md...${C_RESET}" >&2
      chrome_thinking
      run_turn "Please write INTENT.md now based on our conversation." \
        --resume "$SESSION_ID" --permission-mode acceptEdits --max-turns 3
      # Loop will check for INTENT.md on next iteration
      continue
      ;;
    "")
      continue
      ;;
  esac

  # Send human input to the intent team, resume the session
  chrome_thinking
  run_turn "$human_input" --resume "$SESSION_ID" --permission-mode acceptEdits --max-turns 3
done

# ── Fallback: conversation ended without INTENT.md ──
INTENT_PATH=$(find_intent_md)
if [[ -z "$INTENT_PATH" ]]; then
  echo -e "  ${C_DIM}No INTENT.md was written. Asking agent to produce it...${C_RESET}" >&2
  chrome_thinking
  run_turn "Please write the INTENT.md now based on everything we've discussed." \
    --resume "$SESSION_ID" --permission-mode acceptEdits --max-turns 3
  INTENT_PATH=$(find_intent_md)
fi

if [[ -n "$INTENT_PATH" ]]; then
  chrome_banner "INTENT.md"
  cat "$INTENT_PATH" >&2
  echo "" >&2
  chrome_heavy_line

  chrome_approval approval
  case "$approval" in
    y|Y)
      echo -e "  ${C_GREEN}Intent approved.${C_RESET}" >&2
      exit 0
      ;;
    e|E)
      ${EDITOR:-vim} "$INTENT_PATH"
      echo -e "  ${C_GREEN}INTENT.md updated.${C_RESET}" >&2
      exit 0
      ;;
    *)
      echo -e "  ${C_YELLOW}Intent rejected.${C_RESET}" >&2
      exit 1
      ;;
  esac
else
  echo -e "  ${C_RED}Intent agent did not produce INTENT.md.${C_RESET}" >&2
  exit 1
fi
