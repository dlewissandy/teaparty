#!/usr/bin/env bash
# Promote learnings upward through the memory hierarchy.
#
# Two promotion levels via --scope:
#
#   --scope session  (session → project)
#     Reads: session MEMORY.md + all dispatch MEMORY.md files
#     Output: project MEMORY.md
#     Prompt: project-relevant insights
#
#   --scope global   (project → global)
#     Reads: project MEMORY.md
#     Output: output/MEMORY.md
#     Prompt: cross-project insights only (heavily filtered)
#
# Called by run.sh after the uber session completes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_DIR="$(dirname "$SCRIPT_DIR")"

SESSION_DIR="${POC_SESSION_DIR:-}"
PROJECT_DIR="${POC_PROJECT_DIR:-}"
OUTPUT_DIR="${POC_OUTPUT_DIR:-$POC_DIR/output}"

# Parse --scope argument
SCOPE="${1:-}"
if [[ "$SCOPE" == "--scope" ]]; then
  SCOPE="${2:-session}"
elif [[ "$SCOPE" =~ ^--scope= ]]; then
  SCOPE="${SCOPE#--scope=}"
else
  SCOPE="session"
fi

case "$SCOPE" in
  session)
    # Session → Project promotion
    if [[ -z "$SESSION_DIR" ]]; then
      echo "[promote] POC_SESSION_DIR not set, skipping." >&2
      exit 1
    fi
    if [[ -z "$PROJECT_DIR" ]]; then
      echo "[promote] POC_PROJECT_DIR not set, skipping." >&2
      exit 1
    fi

    # Collect all MEMORY.md files from this session
    CONTEXT_FILES=()

    # Session-level memory (uber lead's learnings)
    if [[ -s "$SESSION_DIR/MEMORY.md" ]]; then
      CONTEXT_FILES+=("$SESSION_DIR/MEMORY.md")
    fi

    # Dispatch-level memories (team/<dispatch>/MEMORY.md)
    for team in art writing editorial research; do
      for dispatch_mem in "$SESSION_DIR/$team"/*/MEMORY.md; do
        if [[ -s "$dispatch_mem" ]]; then
          CONTEXT_FILES+=("$dispatch_mem")
        fi
      done 2>/dev/null
    done

    if [[ ${#CONTEXT_FILES[@]} -eq 0 ]]; then
      echo "[promote] No session learnings found to promote." >&2
      exit 0
    fi

    echo "[promote] Promoting ${#CONTEXT_FILES[@]} memory file(s) to project memory..." >&2

    # Build --context args
    CONTEXT_ARGS=()
    for f in "${CONTEXT_FILES[@]}"; do
      CONTEXT_ARGS+=(--context "$f")
    done

    # Use the uber exec stream as primary source
    STREAM="$SESSION_DIR/.exec-stream.jsonl"
    if [[ ! -f "$STREAM" ]]; then
      # Fall back: use the first available dispatch stream
      for team in art writing editorial research; do
        for candidate in "$SESSION_DIR/$team"/*/.exec-stream.jsonl; do
          if [[ -f "$candidate" ]]; then
            STREAM="$candidate"
            break 2
          fi
        done 2>/dev/null
      done
    fi

    python3 "$SCRIPT_DIR/summarize_session.py" \
      --stream "$STREAM" \
      --output "$PROJECT_DIR/MEMORY.md" \
      --scope project \
      "${CONTEXT_ARGS[@]}"
    ;;

  global)
    # Project → Global promotion (filtered for cross-project insights)
    if [[ -z "$PROJECT_DIR" ]]; then
      echo "[promote] POC_PROJECT_DIR not set, skipping." >&2
      exit 1
    fi

    if [[ ! -s "$PROJECT_DIR/MEMORY.md" ]]; then
      echo "[promote] No project learnings to promote to global." >&2
      exit 0
    fi

    echo "[promote] Promoting project learnings to global memory (filtered)..." >&2

    # The project MEMORY.md is the source; we feed it as context
    # and use the uber stream for conversation reference
    STREAM="${SESSION_DIR:+$SESSION_DIR/.exec-stream.jsonl}"
    if [[ -z "$STREAM" || ! -f "$STREAM" ]]; then
      # No stream available — use a dummy; the context file has the learnings
      STREAM="/dev/null"
    fi

    python3 "$SCRIPT_DIR/summarize_session.py" \
      --stream "$STREAM" \
      --output "$OUTPUT_DIR/MEMORY.md" \
      --scope global \
      --context "$PROJECT_DIR/MEMORY.md"
    ;;

  *)
    echo "[promote] Unknown scope: $SCOPE (expected 'session' or 'global')" >&2
    exit 1
    ;;
esac
