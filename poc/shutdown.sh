#!/usr/bin/env bash
# POC Shutdown — kill all team processes and orphans cleanly
# Usage: ./poc/shutdown.sh [--force]
set -euo pipefail

FORCE=false
[[ "${1:-}" == "--force" ]] && FORCE=true

echo "=== POC Shutdown ==="
echo ""

# Collect all POC-related PIDs
declare -a PIDS=()

# claude -p team processes (project, art, writing, editorial)
while IFS= read -r pid; do
  [[ -n "$pid" ]] && PIDS+=("$pid")
done < <(pgrep -f 'claude.*-p.*--agents' 2>/dev/null || true)

# relay.sh processes
while IFS= read -r pid; do
  [[ -n "$pid" ]] && PIDS+=("$pid")
done < <(pgrep -f 'relay\.sh' 2>/dev/null || true)

# extract_result.py orphans
while IFS= read -r pid; do
  [[ -n "$pid" ]] && PIDS+=("$pid")
done < <(pgrep -f 'extract_result\.py' 2>/dev/null || true)

# tee processes writing to tmp files (from run.sh pipeline)
while IFS= read -r pid; do
  [[ -n "$pid" ]] && PIDS+=("$pid")
done < <(pgrep -f 'tee /.*tmp\.' 2>/dev/null || true)

# python3 stream filter (the inline python in run.sh)
while IFS= read -r pid; do
  [[ -n "$pid" ]] && PIDS+=("$pid")
done < <(pgrep -f 'python3.*-u.*-c.*stream' 2>/dev/null || true)

# Deduplicate
UNIQUE_PIDS=($(printf '%s\n' "${PIDS[@]}" 2>/dev/null | sort -u || true))

if [[ ${#UNIQUE_PIDS[@]} -eq 0 ]]; then
  echo "No POC processes found. Clean."
  exit 0
fi

echo "Found ${#UNIQUE_PIDS[@]} POC process(es):"
echo ""
for pid in "${UNIQUE_PIDS[@]}"; do
  cmd=$(ps -p "$pid" -o args= 2>/dev/null | head -c 120 || echo "(already dead)")
  elapsed=$(ps -p "$pid" -o etime= 2>/dev/null | tr -d ' ' || echo "?")
  echo "  PID=$pid  elapsed=$elapsed"
  echo "    $cmd"
done
echo ""

if [[ "$FORCE" == true ]]; then
  echo "Force killing (SIGKILL)..."
  for pid in "${UNIQUE_PIDS[@]}"; do
    kill -9 "$pid" 2>/dev/null && echo "  killed PID=$pid" || echo "  PID=$pid already dead"
  done
else
  echo "Graceful shutdown (SIGTERM, then SIGKILL after 5s)..."
  for pid in "${UNIQUE_PIDS[@]}"; do
    kill "$pid" 2>/dev/null && echo "  sent SIGTERM to PID=$pid" || echo "  PID=$pid already dead"
  done

  echo "  waiting 5s for graceful exit..."
  sleep 5

  # Check for survivors
  SURVIVORS=()
  for pid in "${UNIQUE_PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      SURVIVORS+=("$pid")
    fi
  done

  if [[ ${#SURVIVORS[@]} -gt 0 ]]; then
    echo "  ${#SURVIVORS[@]} process(es) still alive, sending SIGKILL..."
    for pid in "${SURVIVORS[@]}"; do
      kill -9 "$pid" 2>/dev/null && echo "  killed PID=$pid" || true
    done
  fi
fi

echo ""

# Final check
sleep 1
REMAINING=$(pgrep -f 'claude.*-p.*--agents|relay\.sh|extract_result\.py' 2>/dev/null || true)
if [[ -n "$REMAINING" ]]; then
  echo "WARNING: Some processes may still be alive:"
  echo "$REMAINING" | while read pid; do
    ps -p "$pid" -o pid=,etime=,args= 2>/dev/null | head -c 120
    echo ""
  done
else
  echo "All POC processes terminated."
fi
