#!/usr/bin/env bash
# Promote learnings upward through the memory hierarchy.
#
# Four main promotion levels via --scope, each producing TWO typed outputs:
#   institutional.md  — always-loaded coordination norms (prose, compact)
#   tasks/<ts>.md     — fuzzy-retrieved procedural learnings (chunked by memory_indexer.py)
#
#   --scope team     (dispatch → team)
#     Reads: dispatch MEMORY.md files for each team (backward compat input)
#     Output: session/<team>/institutional.md + session/<team>/tasks/<ts>.md
#
#   --scope session  (team → session)
#     Reads: team institutional.md + team tasks/*.md files
#     Output: session/institutional.md + session/tasks/<ts>.md
#
#   --scope project  (session → project)
#     Reads: session/institutional.md + session/tasks/*.md
#     Output: project/institutional.md + project/tasks/<ts>.md
#
#   --scope global   (project → global)
#     Reads: project/institutional.md
#     Output: projects/institutional.md + projects/tasks/<ts>.md
#
# Proxy stores (written by run.sh, not promoted):
#   proxy.md          — observations scope → always-loaded human preferences
#   proxy-tasks/<ts>  — escalation scope → fuzzy-retrieved domain thresholds
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
    # For each team that has dispatch MEMORYs, aggregate them into typed stores
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

      echo "[promote] Rolling up ${#DISPATCH_MEMS[@]} dispatch(es) → $team_name/ typed stores" >&2

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

      TS=$(date +%Y%m%d-%H%M%S)
      mkdir -p "$SESSION_DIR/$team_name/tasks"

      # Institutional pass — coordination norms for this team
      python3 "$SCRIPT_DIR/summarize_session.py" \
        --stream "$STREAM" \
        --output "$SESSION_DIR/$team_name/institutional.md" \
        --scope team-rollup-institutional \
        "${CONTEXT_ARGS[@]}" || true

      # Tasks pass — procedural learnings for this team
      python3 "$SCRIPT_DIR/summarize_session.py" \
        --stream "$STREAM" \
        --output "$SESSION_DIR/$team_name/tasks/$TS.md" \
        --scope team-rollup-tasks \
        "${CONTEXT_ARGS[@]}" || true
    done
    ;;

  session)
    # Team → Session rollup (team-agnostic filter)
    if [[ -z "$SESSION_DIR" ]]; then
      echo "[promote] POC_SESSION_DIR not set, skipping." >&2
      exit 1
    fi

    CONTEXT_FILES=()
    for team_name in art writing editorial research coding; do
      # Prefer new typed files; fall back to legacy MEMORY.md
      if [[ -s "$SESSION_DIR/$team_name/institutional.md" ]]; then
        CONTEXT_FILES+=("$SESSION_DIR/$team_name/institutional.md")
      elif [[ -s "$SESSION_DIR/$team_name/MEMORY.md" ]]; then
        CONTEXT_FILES+=("$SESSION_DIR/$team_name/MEMORY.md")
      fi
      # Include any task files from this team
      for f in "$SESSION_DIR/$team_name/tasks/"*.md; do
        [[ -s "$f" ]] && CONTEXT_FILES+=("$f")
      done 2>/dev/null
    done

    if [[ ${#CONTEXT_FILES[@]} -eq 0 ]]; then
      echo "[promote] No team learnings found to promote to session." >&2
      exit 0
    fi

    echo "[promote] Rolling up ${#CONTEXT_FILES[@]} team file(s) → session typed stores" >&2

    CONTEXT_ARGS=()
    for f in "${CONTEXT_FILES[@]}"; do
      CONTEXT_ARGS+=(--context "$f")
    done

    # Uber exec stream provides coordination context
    STREAM="$SESSION_DIR/.exec-stream.jsonl"
    [[ -f "$STREAM" ]] || STREAM="/dev/null"

    TS=$(date +%Y%m%d-%H%M%S)
    mkdir -p "$SESSION_DIR/tasks"

    # Institutional pass — cross-team coordination norms
    python3 "$SCRIPT_DIR/summarize_session.py" \
      --stream "$STREAM" \
      --output "$SESSION_DIR/institutional.md" \
      --scope session-institutional \
      "${CONTEXT_ARGS[@]}"

    # Tasks pass — cross-team procedural learnings
    python3 "$SCRIPT_DIR/summarize_session.py" \
      --stream "$STREAM" \
      --output "$SESSION_DIR/tasks/$TS.md" \
      --scope session-tasks \
      "${CONTEXT_ARGS[@]}"

    # Compact institutional to prevent monotonic growth
    python3 "$SCRIPT_DIR/compact_memory.py" --input "$SESSION_DIR/institutional.md" 2>/dev/null || true
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

    # Context: prefer new typed files; fall back to legacy session MEMORY.md
    CONTEXT_ARGS=()
    if [[ -s "$SESSION_DIR/institutional.md" ]]; then
      CONTEXT_ARGS+=(--context "$SESSION_DIR/institutional.md")
    elif [[ -s "$SESSION_DIR/MEMORY.md" ]]; then
      CONTEXT_ARGS+=(--context "$SESSION_DIR/MEMORY.md")
    fi
    for f in "$SESSION_DIR/tasks/"*.md; do
      [[ -s "$f" ]] && CONTEXT_ARGS+=(--context "$f")
    done 2>/dev/null

    if [[ ${#CONTEXT_ARGS[@]} -eq 0 ]]; then
      echo "[promote] No session learnings to promote to project." >&2
      exit 0
    fi

    echo "[promote] Promoting session learnings → project typed stores" >&2

    STREAM="$SESSION_DIR/.exec-stream.jsonl"
    [[ -f "$STREAM" ]] || STREAM="/dev/null"

    TS=$(date +%Y%m%d-%H%M%S)
    mkdir -p "$PROJECT_DIR/tasks"

    # Institutional pass — project-level conventions
    python3 "$SCRIPT_DIR/summarize_session.py" \
      --stream "$STREAM" \
      --output "$PROJECT_DIR/institutional.md" \
      --scope project-institutional \
      "${CONTEXT_ARGS[@]}"

    # Tasks pass — project-specific procedural patterns
    python3 "$SCRIPT_DIR/summarize_session.py" \
      --stream "$STREAM" \
      --output "$PROJECT_DIR/tasks/$TS.md" \
      --scope project-tasks \
      "${CONTEXT_ARGS[@]}"

    # Compact institutional to prevent monotonic growth
    python3 "$SCRIPT_DIR/compact_memory.py" --input "$PROJECT_DIR/institutional.md" 2>/dev/null || true
    ;;

  global)
    # Project → Global promotion (filtered for cross-project insights)
    if [[ -z "$PROJECT_DIR" ]]; then
      echo "[promote] POC_PROJECT_DIR not set, skipping." >&2
      exit 1
    fi

    # Institutional memory lives at the projects/ folder level (parent of project dir)
    PROJECTS_DIR="$(dirname "$PROJECT_DIR")"

    # Context: prefer new typed files; fall back to legacy MEMORY.md
    CONTEXT_ARGS=()
    if [[ -s "$PROJECT_DIR/institutional.md" ]]; then
      CONTEXT_ARGS+=(--context "$PROJECT_DIR/institutional.md")
    elif [[ -s "$PROJECT_DIR/MEMORY.md" ]]; then
      CONTEXT_ARGS+=(--context "$PROJECT_DIR/MEMORY.md")
    fi

    if [[ ${#CONTEXT_ARGS[@]} -eq 0 ]]; then
      echo "[promote] No project learnings to promote to global." >&2
      exit 0
    fi

    echo "[promote] Promoting project learnings → global typed stores (project-agnostic filter)" >&2

    STREAM="${SESSION_DIR:+$SESSION_DIR/.exec-stream.jsonl}"
    if [[ -z "$STREAM" || ! -f "$STREAM" ]]; then
      STREAM="/dev/null"
    fi

    TS=$(date +%Y%m%d-%H%M%S)
    mkdir -p "$PROJECTS_DIR/tasks"

    # Institutional pass — cross-project coordination norms
    python3 "$SCRIPT_DIR/summarize_session.py" \
      --stream "$STREAM" \
      --output "$PROJECTS_DIR/institutional.md" \
      --scope global-institutional \
      "${CONTEXT_ARGS[@]}"

    # Tasks pass — cross-project procedural patterns
    python3 "$SCRIPT_DIR/summarize_session.py" \
      --stream "$STREAM" \
      --output "$PROJECTS_DIR/tasks/$TS.md" \
      --scope global-tasks \
      "${CONTEXT_ARGS[@]}"

    # Compact institutional to prevent monotonic growth
    python3 "$SCRIPT_DIR/compact_memory.py" --input "$PROJECTS_DIR/institutional.md" 2>/dev/null || true
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
    echo "[promote] Extracting prospective learnings → project/tasks/" >&2
    TS=$(date +%Y%m%d-%H%M%S)
    mkdir -p "$PROJECT_DIR/tasks"
    python3 "$SCRIPT_DIR/summarize_session.py" \
      --stream "$STREAM" \
      --output "$PROJECT_DIR/tasks/$TS-prospective.md" \
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
    echo "[promote] Extracting in-flight learnings → project/tasks/" >&2
    TS=$(date +%Y%m%d-%H%M%S)
    mkdir -p "$PROJECT_DIR/tasks"
    python3 "$SCRIPT_DIR/summarize_session.py" \
      --stream "$STREAM" \
      --output "$PROJECT_DIR/tasks/$TS-inflight.md" \
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
    echo "[promote] Extracting corrective learnings → project/tasks/" >&2
    TS=$(date +%Y%m%d-%H%M%S)
    mkdir -p "$PROJECT_DIR/tasks"
    python3 "$SCRIPT_DIR/summarize_session.py" \
      --stream "$STREAM" \
      --output "$PROJECT_DIR/tasks/$TS-corrective.md" \
      --scope corrective || true
    ;;

  *)
    echo "[promote] Unknown scope: $SCOPE (expected 'team', 'session', 'project', 'global', 'prospective', 'in-flight', or 'corrective')" >&2
    exit 1
    ;;
esac
