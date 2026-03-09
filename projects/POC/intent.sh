#!/usr/bin/env bash
# intent.sh — CfA-driven intent gathering.
#
# The intent agent runs autonomously and produces INTENT.md. The human
# reviews the result: approve, edit, reject with feedback. Rejection
# feeds back into the agent (INTENT_RESPONSE → PROPOSAL cycle).
#
# There is no round counter, no "done"/"skip", no per-turn prompting.
# The CfA state machine drives the loop:
#   PROPOSAL → INTENT_ASSERT → approve (exit 0) or reject → INTENT_RESPONSE → PROPOSAL → ...
#   PROPOSAL → INTENT_ESCALATE → clarify → INTENT_RESPONSE → PROPOSAL → ...
#
# Usage: intent.sh --cwd <worktree> --stream-dir <infra-dir> --task "<task>" \
#                  [--context-file <path>...] [--backtrack-context "<feedback>"]
#
# Exits 0 with INTENT.md written to CWD, or 1 if rejected/failed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/ui.sh"

# Defaults
CWD=""
STREAM_DIR=""
TASK=""
PROJECT_DIR=""
BACKTRACK_CONTEXT=""
PROXY_MODEL=""
CONTEXT_FILES=()

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --cwd)               CWD="$2"; shift 2 ;;
    --stream-dir)        STREAM_DIR="$2"; shift 2 ;;
    --task)              TASK="$2"; shift 2 ;;
    --project-dir)       PROJECT_DIR="$2"; shift 2 ;;
    --backtrack-context) BACKTRACK_CONTEXT="$2"; shift 2 ;;
    --proxy-model)       PROXY_MODEL="$2"; shift 2 ;;
    --context-file)      CONTEXT_FILES+=("$2"); shift 2 ;;
    *)                   echo "intent.sh: unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$CWD" ]]  && { echo "intent.sh: --cwd required" >&2; exit 1; }
[[ -z "$TASK" ]] && { echo "intent.sh: --task required" >&2; exit 1; }

# Default stream dir to CWD if not specified
STREAM_DIR="${STREAM_DIR:-$CWD}"
mkdir -p "$STREAM_DIR"

# ── Build initial prompt with warm-start context ──
INITIAL_PROMPT="Task: $TASK

Write INTENT.md to: $CWD/INTENT.md (this is the absolute path to your working directory)"

for ctx_file in ${CONTEXT_FILES[@]+"${CONTEXT_FILES[@]}"}; do
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
    'Bash(' + d + '/dispatch.sh:*)',
    'Bash(' + d + '/tools/yt-transcript.sh:*)',
    'WebFetch',
    'WebSearch',
    'Write',
]
json.dump({'permissions': {'allow': rules}, 'env': {
    'SCRIPT_DIR': d,
    'POC_OUTPUT_DIR': os.environ.get('POC_OUTPUT_DIR', ''),
    'POC_PROJECT': os.environ.get('POC_PROJECT', ''),
    'POC_PROJECT_DIR': os.environ.get('POC_PROJECT_DIR', ''),
    'POC_SESSION_DIR': os.environ.get('POC_SESSION_DIR', ''),
    'POC_SESSION_WORKTREE': os.environ.get('POC_SESSION_WORKTREE', ''),
    'POC_CFA_STATE': os.environ.get('POC_CFA_STATE', ''),
}}, sys.stdout)
" > "$SETTINGS_FILE"

# ── CfA state helpers — update root state if exported by run.sh ──
intent_cfa_transition() {
  local action="$1"
  if [[ -n "${POC_CFA_STATE:-}" && -f "${POC_CFA_STATE:-}" ]]; then
    if ! python3 "$SCRIPT_DIR/scripts/cfa_state.py" --transition \
        --state-file "$POC_CFA_STATE" --action "$action" 2>/dev/null; then
      return 1
    fi
  fi
}

intent_cfa_set() {
  local target="$1"
  if [[ -n "${POC_CFA_STATE:-}" && -f "${POC_CFA_STATE:-}" ]]; then
    python3 "$SCRIPT_DIR/scripts/cfa_state.py" --set-state \
      --state-file "$POC_CFA_STATE" --target "$target" 2>/dev/null || true
  fi
}

# Approval gate helpers (proxy_decide, proxy_record) are in ui.sh

# ── Stream and session state ──
INTENT_STREAM="$STREAM_DIR/.intent-stream.jsonl"
> "$INTENT_STREAM"

# Common claude args
CLAUDE_ARGS=(-p --output-format stream-json --verbose --setting-sources user)
CLAUDE_ARGS+=(--agents "$AGENTS_JSON" --agent intent-lead)
CLAUDE_ARGS+=(--settings "$SETTINGS_FILE")
# Grant read access to session worktree and projects dir
[[ -n "${POC_SESSION_WORKTREE:-}" ]] && CLAUDE_ARGS+=(--add-dir "$POC_SESSION_WORKTREE")
[[ -n "${PROJECTS_DIR:-}" ]]         && CLAUDE_ARGS+=(--add-dir "$PROJECTS_DIR")

# ── Helper: find INTENT.md (only if written during THIS session) ──
INTENT_SESSION_START=$(date +%s)

find_intent_md() {
  # Primary: check exact CWD path (where we told the agent to write)
  if [[ -f "$CWD/INTENT.md" ]]; then
    local mtime
    mtime=$(stat -f%m "$CWD/INTENT.md" 2>/dev/null || stat -c%Y "$CWD/INTENT.md" 2>/dev/null || echo 0)
    if [[ $mtime -ge $INTENT_SESSION_START ]]; then
      echo "$CWD/INTENT.md"
      return
    fi
  fi
  # Fallback: agent may have written to a nearby path — search worktree
  local found
  found=$(find "$CWD" -maxdepth 2 -name "INTENT.md" -newer "$INTENT_STREAM" 2>/dev/null | head -1)
  if [[ -n "$found" ]]; then
    # Move it to the expected location
    mv "$found" "$CWD/INTENT.md"
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

# ── INTENT.md version management ──
INTENT_VERSION=0

bump_intent_version() {
  local intent_path="$1"
  local change_summary="${2:-revision}"
  INTENT_VERSION=$((INTENT_VERSION + 1))
  local version_str="v0.$INTENT_VERSION"
  local timestamp
  timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  local version_header="<!-- INTENT VERSION: $version_str | Updated: $timestamp | Change: $change_summary -->"

  if grep -q "<!-- INTENT VERSION:" "$intent_path" 2>/dev/null; then
    local tmp
    tmp=$(mktemp)
    echo "$version_header" > "$tmp"
    grep -v "<!-- INTENT VERSION:" "$intent_path" >> "$tmp"
    mv "$tmp" "$intent_path"
  else
    local tmp
    tmp=$(mktemp)
    echo "$version_header" > "$tmp"
    cat "$intent_path" >> "$tmp"
    mv "$tmp" "$intent_path"
  fi
  echo -e "  ${C_DIM}INTENT.md $version_str${C_RESET}" >&2
}

# ── Helper: run one turn of the conversation ──
run_turn() {
  local input="$1"
  shift
  local extra_args=("$@")

  local fifo
  fifo=$(mktemp -u).fifo
  mkfifo "$fifo"

  (cd "$CWD" && echo "$input" | claude "${CLAUDE_ARGS[@]}" "${extra_args[@]}" > "$fifo") &
  local bg_pid=$!

  cat < "$fifo" \
    | tee -a "$INTENT_STREAM" \
    | tee >(session_stream_log) \
    | python3 -u "$SCRIPT_DIR/stream/intent_display.py" --agent-name intent-lead >&2

  CLAUDE_EXIT=0
  wait "$bg_pid" 2>/dev/null || CLAUDE_EXIT=$?
  rm -f "$fifo"
}

# ── Present INTENT.md for human review (CfA: INTENT_ASSERT) ──
# Returns: 0 = approved, 1 = rejected (feedback in $REJECTION_FEEDBACK)
REJECTION_FEEDBACK=""

review_intent() {
  local intent_path="$1"
  intent_cfa_set "INTENT_ASSERT"

  # ── Proxy gate: auto-approve if confident ──
  PROXY_ACTION=$(proxy_decide "INTENT_ASSERT" "$intent_path")
  session_log PROXY "INTENT_ASSERT proxy=$PROXY_ACTION"
  if [[ "$PROXY_ACTION" == "auto-approve" ]]; then
    proxy_record "INTENT_ASSERT" "approve" "" "$intent_path"
    bump_intent_version "$intent_path" "proxy-approved"
    echo -e "  ${C_DIM}CfA: INTENT_ASSERT → approve → INTENT (proxy auto-approved)${C_RESET}" >&2
    session_log STATE "INTENT_ASSERT → approve → INTENT (proxy auto-approved)"
    return 0
  fi

  chrome_banner "INTENT_ASSERT" "CfA Phase 1 — human reviews intent document"
  local ver
  ver=$(grep "<!-- INTENT VERSION:" "$intent_path" 2>/dev/null | grep -o 'v[0-9.]*' | head -1 || echo "v0.0")
  echo -e "  ${C_DIM}Version: $ver${C_RESET}" >&2
  chrome_bridge "$intent_path" "INTENT_ASSERT" "$TASK"
  chrome_heavy_line

  # Free-text review with dialog loop
  local intent_summary
  intent_summary=$(head -c 500 "$intent_path" 2>/dev/null || true)

  if cfa_review_loop "INTENT_ASSERT" "$intent_summary" "" "$intent_path" "" "$TASK"; then
    case "$REVIEW_ACTION" in
      approve)
        proxy_record "INTENT_ASSERT" "approve" "" "$intent_path"
        bump_intent_version "$intent_path" "approved"
        echo -e "  ${C_DIM}CfA: INTENT_ASSERT → approve → INTENT${C_RESET}" >&2
        session_log STATE "INTENT_ASSERT → approve → INTENT"
        return 0
        ;;
      withdraw)
        proxy_record "INTENT_ASSERT" "withdraw"
        intent_cfa_transition "withdraw" || intent_cfa_set "WITHDRAWN"
        echo -e "  ${C_YELLOW}Intent withdrawn.${C_RESET}" >&2
        session_log STATE "INTENT_ASSERT → withdraw → WITHDRAWN"
        exit 1
        ;;
      correct)
        REJECTION_FEEDBACK="$REVIEW_FEEDBACK"
        _CONV_TEXT=""
        [[ -n "${REVIEW_DIALOG_HISTORY:-}" ]] && _CONV_TEXT="${REVIEW_DIALOG_HISTORY}

"
        _CONV_TEXT="${_CONV_TEXT}${CFA_RESPONSE}"
        proxy_record "INTENT_ASSERT" "correct" "$REVIEW_FEEDBACK" "$intent_path" "$_CONV_TEXT"
        echo -e "  ${C_DIM}CfA: INTENT_ASSERT → correct → INTENT_RESPONSE${C_RESET}" >&2
        session_log STATE "INTENT_ASSERT → correct → INTENT_RESPONSE"
        return 1
        ;;
    esac
  fi

  # Fallback: treat raw input as correction feedback
  REJECTION_FEEDBACK="$CFA_RESPONSE"
  proxy_record "INTENT_ASSERT" "correct" "$CFA_RESPONSE" "$intent_path" "$CFA_RESPONSE"
  return 1
}

# ══════════════════════════════════════════════════════════════
#  CfA Intent Loop
#
#  PROPOSAL: Agent runs autonomously
#    → writes INTENT.md: enter INTENT_ASSERT
#    → writes .intent-escalation.md: enter INTENT_ESCALATE
#  INTENT_ASSERT: Human/proxy reviews INTENT.md
#    → approve: exit 0
#    → reject with feedback: INTENT_RESPONSE → agent revises → PROPOSAL
#  INTENT_ESCALATE: Agent has focused questions for the human
#    → clarify: INTENT_RESPONSE → agent incorporates → PROPOSAL
#    → withdraw: exit 1
# ══════════════════════════════════════════════════════════════

# ── Banner ──
if [[ -n "$BACKTRACK_CONTEXT" ]]; then
  chrome_header "INTENT_RESPONSE → PROPOSAL (CfA backtrack re-entry)"
  echo -e "  ${C_YELLOW}Re-entering intent alignment from downstream phase.${C_RESET}" >&2
  echo -e "  ${C_DIM}Feedback: ${BACKTRACK_CONTEXT:0:200}${C_RESET}" >&2
else
  chrome_header "PROPOSAL (CfA Phase 1: Intent Alignment)"
fi

# ── Build first prompt ──
if [[ -n "$BACKTRACK_CONTEXT" ]]; then
  INITIAL_PROMPT="[CfA BACKTRACK: Re-entering intent alignment from a downstream phase.]

The planning or execution phase discovered that the intent needs refinement:

--- Backtrack Feedback ---
$BACKTRACK_CONTEXT
--- end Backtrack Feedback ---

Original task: $TASK

Revise INTENT.md to address this feedback. Update the relevant sections — do not start from scratch.

$INITIAL_PROMPT"
fi

# ── PROPOSAL: Agent's first autonomous pass ──
intent_cfa_set "PROPOSAL"
session_log STATE "PROPOSAL (intent phase)"
chrome_thinking
run_turn "$INITIAL_PROMPT" --permission-mode acceptEdits

# ── Intent infrastructure failure gate ──
if [[ $CLAUDE_EXIT -ne 0 ]]; then
  FAILURE_SUMMARY=$(extract_failure "$INTENT_STREAM" "$CLAUDE_EXIT" "$STREAM_DIR")
  generate_failure_report "$INTENT_STREAM" "intent" "intent-lead"
  session_log STATE "Infrastructure failure (exit $CLAUDE_EXIT) during intent"

  cfa_failure_decision "$FAILURE_SUMMARY" "intent"
  case "$FAILURE_ACTION" in
    retry)
      run_turn "$INITIAL_PROMPT" --permission-mode acceptEdits
      if [[ $CLAUDE_EXIT -ne 0 ]]; then
        session_log STATE "Infrastructure failure persists after retry — withdrawing"
        intent_cfa_set "WITHDRAWN"
        exit 1
      fi
      ;;
    *)
      intent_cfa_set "WITHDRAWN"
      exit 1 ;;
  esac
fi

# Extract session ID for --resume on revisions
SESSION_ID=$(extract_session_id < "$INTENT_STREAM")
if [[ -z "$SESSION_ID" ]]; then
  echo -e "  ${C_RED}Could not extract session ID from intent agent${C_RESET}" >&2
  exit 1
fi

# ── CfA assert/revise loop (unbounded — spec imposes no cap) ──
revision=0

while true; do
  # ── Check for escalation (INTENT_ESCALATE) ──
  # Agent writes .intent-escalation.md when it has focused questions
  # instead of writing INTENT.md directly.
  ESCALATION_FILE="$CWD/.intent-escalation.md"
  if [[ -f "$ESCALATION_FILE" ]]; then
    intent_cfa_set "INTENT_ESCALATE"
    session_log STATE "INTENT_ESCALATE — agent needs clarification"
    chrome_header "INTENT_ESCALATE — agent needs clarification"
    chrome_bridge "$ESCALATION_FILE" "INTENT_ESCALATE" "$TASK"
    chrome_heavy_line

    cfa_review_loop "INTENT_ESCALATE" "" "" "$ESCALATION_FILE" "" "$TASK"
    if [[ "$REVIEW_ACTION" == "withdraw" ]]; then
      proxy_record "INTENT_ESCALATE" "withdraw"
      intent_cfa_transition "withdraw" || intent_cfa_set "WITHDRAWN"
      exit 1
    fi

    # Feed clarification back to agent
    proxy_record "INTENT_ESCALATE" "clarify" "$CFA_RESPONSE"
    intent_cfa_transition "clarify" || intent_cfa_set "INTENT_RESPONSE"
    session_log STATE "INTENT_ESCALATE → clarify → INTENT_RESPONSE → PROPOSAL"
    rm -f "$ESCALATION_FILE"
    chrome_user "$CFA_RESPONSE"
    echo -e "  ${C_DIM}CfA: INTENT_RESPONSE → synthesize → PROPOSAL${C_RESET}" >&2
    chrome_thinking
    intent_cfa_set "PROPOSAL"
    run_turn "Human clarification: $CFA_RESPONSE" \
      --resume "$SESSION_ID" --permission-mode acceptEdits
    if [[ $CLAUDE_EXIT -ne 0 ]]; then
      FAILURE_SUMMARY=$(extract_failure "$INTENT_STREAM" "$CLAUDE_EXIT" "$STREAM_DIR")
      generate_failure_report "$INTENT_STREAM" "intent" "intent-lead"
      session_log STATE "Infrastructure failure (exit $CLAUDE_EXIT) during intent revision"
      cfa_failure_decision "$FAILURE_SUMMARY" "intent"
      [[ "$FAILURE_ACTION" != "retry" ]] && { intent_cfa_set "WITHDRAWN"; exit 1; }
    fi
    continue  # Re-check: agent may escalate again or write INTENT.md
  fi

  # ── Check for INTENT.md FIRST ──
  # If the agent produced INTENT.md despite intermediate permission errors,
  # those errors were non-fatal.  Only check permission blocks if no output.
  INTENT_PATH=$(find_intent_md)

  if [[ -z "$INTENT_PATH" ]]; then
    # No INTENT.md — check if permission blocks caused the failure.
    # Only counts file-access denials (Read/Glob), not Bash approval
    # prompts or interactive tool prompts (non-fatal in automated context).
    INTENT_PERM_BLOCKS=$(python3 -c "
import json, sys
blocks = []
for line in open('$INTENT_STREAM'):
    try:
        ev = json.loads(line.strip())
    except: continue
    if ev.get('type') != 'user': continue
    for b in ev.get('message',{}).get('content',[]):
        if not isinstance(b, dict) or not b.get('is_error'): continue
        t = b.get('text','') or b.get('content','')
        if 'denied' in t.lower() or 'not allowed' in t.lower():
            blocks.append(t.strip())
for b in blocks[:5]: print(b)
" 2>/dev/null || true)

    if [[ -n "$INTENT_PERM_BLOCKS" ]]; then
      echo -e "  ${C_RED}Intent agent blocked by permissions — cannot produce trustworthy intent.${C_RESET}" >&2
      generate_failure_report "$INTENT_STREAM" "intent" "intent-lead"
      session_log STATE "Intent blocked by permission restrictions"
      exit 1
    fi

    # No permission blocks either — agent just didn't finish.
    # Ask it to complete, but do NOT tell it to skip reading.
    echo -e "  ${C_DIM}No INTENT.md yet — asking agent to complete it.${C_RESET}" >&2
    chrome_thinking
    run_turn "You have not yet written INTENT.md. If the task references files or documents you haven't read yet, read them now. Then write INTENT.md." \
      --resume "$SESSION_ID" --permission-mode acceptEdits
    INTENT_PATH=$(find_intent_md)
  fi

  if [[ -z "$INTENT_PATH" ]]; then
    echo -e "  ${C_RED}Intent agent did not produce INTENT.md.${C_RESET}" >&2
    exit 1
  fi

  # ── INTENT_ASSERT: Human reviews ──
  if review_intent "$INTENT_PATH"; then
    exit 0
  fi

  # ── INTENT_RESPONSE: Human rejected — feed back to agent ──
  ((revision++))
  intent_cfa_transition "correct" || intent_cfa_set "INTENT_RESPONSE"
  echo -e "  ${C_DIM}CfA: INTENT_ASSERT → correct → INTENT_RESPONSE (revision $revision)${C_RESET}" >&2
  session_log STATE "INTENT_ASSERT → correct → INTENT_RESPONSE (revision $revision)"
  chrome_user "$REJECTION_FEEDBACK"
  echo -e "  ${C_DIM}CfA: INTENT_RESPONSE → synthesize → PROPOSAL${C_RESET}" >&2
  chrome_thinking
  intent_cfa_set "PROPOSAL"  # Agent re-enters PROPOSAL after receiving feedback
  REVISION_MSG="The human rejected INTENT.md."
  if [[ -n "$REVIEW_DIALOG_HISTORY" ]]; then
    REVISION_MSG="${REVISION_MSG}

During the review, this dialog took place:
${REVIEW_DIALOG_HISTORY}"
  fi
  REVISION_MSG="${REVISION_MSG}

The human's correction: ${REJECTION_FEEDBACK}"
  run_turn "$REVISION_MSG" \
    --resume "$SESSION_ID" --permission-mode acceptEdits
  if [[ $CLAUDE_EXIT -ne 0 ]]; then
    FAILURE_SUMMARY=$(extract_failure "$INTENT_STREAM" "$CLAUDE_EXIT" "$STREAM_DIR")
    generate_failure_report "$INTENT_STREAM" "intent" "intent-lead"
    session_log STATE "Infrastructure failure (exit $CLAUDE_EXIT) during intent revision"
    cfa_failure_decision "$FAILURE_SUMMARY" "intent"
    [[ "$FAILURE_ACTION" != "retry" ]] && { intent_cfa_set "WITHDRAWN"; exit 1; }
  fi
done
