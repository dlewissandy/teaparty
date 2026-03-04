#!/usr/bin/env bash
# Promote learnings upward through the memory hierarchy.
#
# Four promotion levels via --scope:
#
#   --scope team     (dispatch → team)
#     Reads: dispatch MEMORY.md files for each team
#     Output: session/<team>/MEMORY.md (one per team)
#     Prompt: team-rollup (aggregate dispatch patterns)
#
#   --scope session  (team → session)
#     Reads: team MEMORY.md files + uber exec stream
#     Output: session/MEMORY.md
#     Prompt: session (team-agnostic coordination learnings)
#
#   --scope project  (session → project)
#     Reads: session MEMORY.md
#     Output: project/MEMORY.md
#     Prompt: project (patterns across sessions)
#
#   --scope global   (project → global)
#     Reads: project MEMORY.md
#     Output: output/MEMORY.md
#     Prompt: global (project-agnostic insights only)
#
# Called by run.sh after the uber session completes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"

SESSION_DIR="${POC_SESSION_DIR:-}"
PROJECT_DIR="${POC_PROJECT_DIR:-}"
OUTPUT_DIR="${POC_OUTPUT_DIR:-$POC_DIR}"

# Parse --scope argument
SCOPE="${1:-}"
if [[ "$SCOPE" == "--scope" ]]; then
  SCOPE="${2:-team}"
elif [[ "$SCOPE" =~ ^--scope= ]]; then
  SCOPE="${SCOPE#--scope=}"
else
  SCOPE="team"
fi

case "$SCOPE" in
  team)
    # Dispatch → Team rollup
    # For each team that has dispatch MEMORYs, aggregate them into team/MEMORY.md
    if [[ -z "$SESSION_DIR" ]]; then
      echo "[promote] POC_SESSION_DIR not set, skipping." >&2
      exit 1
    fi

    for team_name in art writing editorial research coding; do
      DISPATCH_MEMS=()
      for dispatch_mem in "$SESSION_DIR/$team_name"/*/MEMORY.md; do
        [[ -s "$dispatch_mem" ]] && DISPATCH_MEMS+=("$dispatch_mem")
      done 2>/dev/null

      [[ ${#DISPATCH_MEMS[@]} -eq 0 ]] && continue

      echo "[promote] Rolling up ${#DISPATCH_MEMS[@]} dispatch(es) → $team_name/MEMORY.md" >&2

      CONTEXT_ARGS=()
      for f in "${DISPATCH_MEMS[@]}"; do
        CONTEXT_ARGS+=(--context "$f")
      done

      # Use the first available dispatch exec stream for conversation context
      STREAM="/dev/null"
      for candidate in "$SESSION_DIR/$team_name"/*/.exec-stream.jsonl; do
        if [[ -f "$candidate" ]]; then
          STREAM="$candidate"
          break
        fi
      done 2>/dev/null

      python3 "$SCRIPT_DIR/summarize_session.py" \
        --stream "$STREAM" \
        --output "$SESSION_DIR/$team_name/MEMORY.md" \
        --scope team-rollup \
        "${CONTEXT_ARGS[@]}" || true
    done
    ;;

  session)
    # Team → Session rollup (team-agnostic filter)
    # Read team-level MEMORYs and uber exec stream, extract cross-team patterns
    if [[ -z "$SESSION_DIR" ]]; then
      echo "[promote] POC_SESSION_DIR not set, skipping." >&2
      exit 1
    fi

    CONTEXT_FILES=()
    for team_name in art writing editorial research coding; do
      if [[ -s "$SESSION_DIR/$team_name/MEMORY.md" ]]; then
        CONTEXT_FILES+=("$SESSION_DIR/$team_name/MEMORY.md")
      fi
    done

    if [[ ${#CONTEXT_FILES[@]} -eq 0 ]]; then
      echo "[promote] No team learnings found to promote to session." >&2
      exit 0
    fi

    echo "[promote] Rolling up ${#CONTEXT_FILES[@]} team(s) → session MEMORY.md (team-agnostic)" >&2

    CONTEXT_ARGS=()
    for f in "${CONTEXT_FILES[@]}"; do
      CONTEXT_ARGS+=(--context "$f")
    done

    # Uber exec stream provides coordination context
    STREAM="$SESSION_DIR/.exec-stream.jsonl"
    [[ -f "$STREAM" ]] || STREAM="/dev/null"

    python3 "$SCRIPT_DIR/summarize_session.py" \
      --stream "$STREAM" \
      --output "$SESSION_DIR/MEMORY.md" \
      --scope session \
      "${CONTEXT_ARGS[@]}"
    # Compact to prevent monotonic growth (Phase 1)
    python3 "$SCRIPT_DIR/compact_memory.py" --input "$SESSION_DIR/MEMORY.md" 2>/dev/null || true
    ;;

  project)
    # Session → Project promotion
    if [[ -z "$SESSION_DIR" ]]; then
      echo "[promote] POC_SESSION_DIR not set, skipping." >&2
      exit 1
    fi
    if [[ -z "$PROJECT_DIR" ]]; then
      echo "[promote] POC_PROJECT_DIR not set, skipping." >&2
      exit 1
    fi

    if [[ ! -s "$SESSION_DIR/MEMORY.md" ]]; then
      echo "[promote] No session learnings to promote to project." >&2
      exit 0
    fi

    echo "[promote] Promoting session learnings → project MEMORY.md" >&2

    STREAM="$SESSION_DIR/.exec-stream.jsonl"
    [[ -f "$STREAM" ]] || STREAM="/dev/null"

    python3 "$SCRIPT_DIR/summarize_session.py" \
      --stream "$STREAM" \
      --output "$PROJECT_DIR/MEMORY.md" \
      --scope project \
      --context "$SESSION_DIR/MEMORY.md"
    # Compact to prevent monotonic growth (Phase 1)
    python3 "$SCRIPT_DIR/compact_memory.py" --input "$PROJECT_DIR/MEMORY.md" 2>/dev/null || true
    ;;

  global)
    # Project → Global promotion (filtered for cross-project insights)
    if [[ -z "$PROJECT_DIR" ]]; then
      echo "[promote] POC_PROJECT_DIR not set, skipping." >&2
      exit 1
    fi

    # Institutional memory lives at the projects/ folder level (parent of project dir)
    PROJECTS_DIR="$(dirname "$PROJECT_DIR")"

    if [[ ! -s "$PROJECT_DIR/MEMORY.md" ]]; then
      echo "[promote] No project learnings to promote to global." >&2
      exit 0
    fi

    echo "[promote] Promoting project learnings → global MEMORY.md (project-agnostic)" >&2

    # The project MEMORY.md is the source; we feed it as context
    STREAM="${SESSION_DIR:+$SESSION_DIR/.exec-stream.jsonl}"
    if [[ -z "$STREAM" || ! -f "$STREAM" ]]; then
      STREAM="/dev/null"
    fi

    python3 "$SCRIPT_DIR/summarize_session.py" \
      --stream "$STREAM" \
      --output "$PROJECTS_DIR/MEMORY.md" \
      --scope global \
      --context "$PROJECT_DIR/MEMORY.md"
    # Compact to prevent monotonic growth (Phase 1)
    python3 "$SCRIPT_DIR/compact_memory.py" --input "$PROJECTS_DIR/MEMORY.md" 2>/dev/null || true
    ;;

  prospective)
    if [[ -z "$SESSION_DIR" || -z "$PROJECT_DIR" ]]; then
      echo "[promote] POC_SESSION_DIR or POC_PROJECT_DIR not set, skipping." >&2
      exit 1
    fi
    PREMORTEM="${POC_PREMORTEM_FILE:-$SESSION_DIR/.premortem.md}"
    STREAM="$SESSION_DIR/.exec-stream.jsonl"
    [[ -f "$STREAM" ]] || STREAM="/dev/null"
    if [[ ! -s "$PREMORTEM" ]]; then
      echo "[promote] No pre-mortem file found, skipping prospective extraction." >&2
      exit 0
    fi
    echo "[promote] Extracting prospective learnings from pre-mortem + execution" >&2
    python3 "$SCRIPT_DIR/summarize_session.py" \
      --stream "$STREAM" \
      --output "$PROJECT_DIR/MEMORY.md" \
      --scope prospective \
      --context "$PREMORTEM" || true
    ;;

  in-flight)
    if [[ -z "$SESSION_DIR" || -z "$PROJECT_DIR" ]]; then
      echo "[promote] POC_SESSION_DIR or POC_PROJECT_DIR not set, skipping." >&2
      exit 1
    fi
    ASSUMPTIONS="${POC_ASSUMPTIONS_FILE:-$SESSION_DIR/.assumptions.jsonl}"
    STREAM="$SESSION_DIR/.exec-stream.jsonl"
    [[ -f "$STREAM" ]] || STREAM="/dev/null"
    if [[ ! -s "$ASSUMPTIONS" ]]; then
      echo "[promote] No assumption checkpoint file found, skipping in-flight extraction." >&2
      exit 0
    fi
    echo "[promote] Extracting in-flight learnings from milestone checkpoints" >&2
    python3 "$SCRIPT_DIR/summarize_session.py" \
      --stream "$STREAM" \
      --output "$PROJECT_DIR/MEMORY.md" \
      --scope in-flight \
      --context "$ASSUMPTIONS" || true
    ;;

  corrective)
    if [[ -z "$SESSION_DIR" || -z "$PROJECT_DIR" ]]; then
      echo "[promote] POC_SESSION_DIR or POC_PROJECT_DIR not set, skipping." >&2
      exit 1
    fi
    STREAM="$SESSION_DIR/.exec-stream.jsonl"
    [[ -f "$STREAM" ]] || { echo "[promote] No exec stream, skipping corrective." >&2; exit 0; }
    echo "[promote] Extracting corrective learnings from error events" >&2
    python3 "$SCRIPT_DIR/summarize_session.py" \
      --stream "$STREAM" \
      --output "$PROJECT_DIR/MEMORY.md" \
      --scope corrective || true
    ;;

  *)
    echo "[promote] Unknown scope: $SCOPE (expected 'team', 'session', 'project', 'global', 'prospective', 'in-flight', or 'corrective')" >&2
    exit 1
    ;;
esac
