#!/usr/bin/env bash
# reap.sh — Find and kill zombie POC processes (run.sh, intent.sh, etc.)
#
# A process is a zombie if it's a POC orchestrator (run.sh, intent.sh,
# plan-execute.sh) that has been running for more than a threshold with
# no active claude child consuming CPU.
#
# Usage: ./poc/projects/POC/reap.sh          # dry run (list only)
#        ./poc/projects/POC/reap.sh --kill    # actually kill them
set -euo pipefail

KILL=false
THRESHOLD=3600  # 1 hour default

while [[ $# -gt 0 ]]; do
  case "$1" in
    --kill)      KILL=true; shift ;;
    --threshold) THRESHOLD="$2"; shift 2 ;;
    *)           echo "Usage: reap.sh [--kill] [--threshold seconds]" >&2; exit 1 ;;
  esac
done

NOW=$(date +%s)

# ── Helper: parse elapsed time (dd-HH:MM:SS or HH:MM:SS or MM:SS) to seconds ──
elapsed_to_seconds() {
  local e="$1"
  local days=0 hours=0 mins=0 secs=0

  # Strip leading/trailing whitespace
  e=$(echo "$e" | tr -d ' ')

  # dd-HH:MM:SS
  if [[ "$e" == *-* ]]; then
    days="${e%%-*}"
    e="${e#*-}"
  fi

  # Split by : and strip leading zeros (bash treats 08/09 as invalid octal)
  IFS=: read -ra parts <<< "$e"
  local n=${#parts[@]}
  if [[ $n -eq 3 ]]; then
    hours=$((10#${parts[0]}))
    mins=$((10#${parts[1]}))
    secs=$((10#${parts[2]}))
  elif [[ $n -eq 2 ]]; then
    mins=$((10#${parts[0]}))
    secs=$((10#${parts[1]}))
  elif [[ $n -eq 1 ]]; then
    secs=$((10#${parts[0]}))
  fi

  echo $(( days * 86400 + hours * 3600 + mins * 60 + secs ))
}

# ── Helper: human-readable age ──
human_age() {
  local s=$1
  if [[ $s -lt 60 ]]; then echo "${s}s"
  elif [[ $s -lt 3600 ]]; then echo "$((s / 60))m"
  elif [[ $s -lt 86400 ]]; then echo "$((s / 3600))h$((s % 3600 / 60))m"
  else echo "$((s / 86400))d$((s % 86400 / 3600))h"
  fi
}

# ── Find orchestrator processes ──
zombies=()
alive=()

for pid in $(pgrep -f "(run\.sh|intent\.sh|plan-execute\.sh)" 2>/dev/null || true); do
  [[ -z "$pid" ]] && continue
  cmd=$(ps -o command= -p "$pid" 2>/dev/null) || continue

  # Only care about POC-related processes
  [[ "$cmd" == *"run.sh"* || "$cmd" == *"intent.sh"* || "$cmd" == *"plan-execute"* ]] || continue

  elapsed=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')
  [[ -z "$elapsed" ]] && continue
  age_s=$(elapsed_to_seconds "$elapsed")

  # Under threshold — still alive
  if [[ $age_s -lt $THRESHOLD ]]; then
    alive+=("$pid")
    continue
  fi

  # Over threshold — check if it has an active claude child consuming CPU
  has_active_child=false
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    child_cmd=$(ps -o command= -p "$child" 2>/dev/null) || continue
    if [[ "$child_cmd" == *"claude"* ]]; then
      cpu=$(ps -o %cpu= -p "$child" 2>/dev/null | tr -d ' ')
      # If claude child is using >0.5% CPU, it's probably still working
      if (( $(echo "$cpu > 0.5" | bc -l 2>/dev/null || echo 0) )); then
        has_active_child=true
        break
      fi
    fi
  done

  if [[ "$has_active_child" == "true" ]]; then
    alive+=("$pid")
  else
    zombies+=("$pid")
  fi
done

# ── Report ──
if [[ ${#zombies[@]} -eq 0 ]]; then
  echo "No zombie processes found."
  exit 0
fi

echo "Found ${#zombies[@]} zombie process(es):"
echo ""

for pid in "${zombies[@]}"; do
  elapsed=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')
  age_s=$(elapsed_to_seconds "$elapsed")
  cmd=$(ps -o command= -p "$pid" 2>/dev/null | head -c 120)
  echo "  PID=$pid  age=$(human_age $age_s)  $cmd"

  # Show children that will also die
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    child_cmd=$(ps -o command= -p "$child" 2>/dev/null | head -c 100)
    echo "    └ child PID=$child  $child_cmd"
  done
done

echo ""

if [[ "$KILL" == "true" ]]; then
  for pid in "${zombies[@]}"; do
    echo "Killing PID $pid and children..."
    # Kill the process group to get children too
    kill -- -"$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
  done
  echo "Done. Killed ${#zombies[@]} zombie process tree(s)."
else
  echo "Dry run. Re-run with --kill to terminate these processes."
fi
