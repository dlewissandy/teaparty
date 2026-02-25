#!/usr/bin/env bash
# POC Shutdown — kill all team processes, orphans, and clean up team artifacts
# Usage: ./poc/shutdown.sh [--force] [--clean]
#   --force  SIGKILL immediately (no graceful shutdown)
#   --clean  Only clean up stale team/task directories (no process killing)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

FORCE=false
CLEAN_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=true ;;
    --clean) CLEAN_ONLY=true ;;
  esac
done

echo "=== POC Shutdown ==="
echo ""

# ── Clean up team/task directories ──
cleanup_teams() {
  local TEAMS_DIR="$HOME/.claude/teams"

  if [[ ! -d "$TEAMS_DIR" ]]; then
    echo "  No teams directory found"
    return
  fi

  # Find and remove POC-related teams by checking member cwd
  python3 -c "
import json, os, glob, shutil

poc_dir = '$SCRIPT_DIR'
teams_dir = os.path.expanduser('~/.claude/teams')
tasks_dir = os.path.expanduser('~/.claude/tasks')
cleaned = 0

for config_path in sorted(glob.glob(os.path.join(teams_dir, '*/config.json'))):
    try:
        with open(config_path) as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, IOError):
        continue

    members = cfg.get('members', [])
    cwds = [m.get('cwd', '') for m in members]
    if not any(poc_dir in cwd for cwd in cwds):
        continue

    team_dir = os.path.dirname(config_path)
    dir_name = os.path.basename(team_dir)
    team_name = cfg.get('name', dir_name)
    member_names = [m.get('name', '?') for m in members]

    members_str = ', '.join(member_names)
    print(f'  Cleaning: {team_name} ({len(members)} members: {members_str})')

    shutil.rmtree(team_dir, ignore_errors=True)
    print(f'    removed ~/.claude/teams/{dir_name}/')

    task_dir = os.path.join(tasks_dir, dir_name)
    if os.path.isdir(task_dir):
        shutil.rmtree(task_dir, ignore_errors=True)
        print(f'    removed ~/.claude/tasks/{dir_name}/')

    cleaned += 1

if cleaned == 0:
    print('  No POC-related team artifacts to clean')
"
}

# If --clean flag, only do artifact cleanup
if [[ "$CLEAN_ONLY" == true ]]; then
  echo "── Cleaning Team Artifacts ──"
  cleanup_teams
  echo ""
  echo "Done."
  exit 0
fi

# ── Collect all POC-related PIDs ──
declare -a PIDS=()

# claude -p team processes (uber, art, writing, editorial)
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

# python3 stream filter
while IFS= read -r pid; do
  [[ -n "$pid" ]] && PIDS+=("$pid")
done < <(pgrep -f 'python3.*stream_filter\.py' 2>/dev/null || true)

# Deduplicate
UNIQUE_PIDS=($(printf '%s\n' "${PIDS[@]}" 2>/dev/null | sort -u || true))

if [[ ${#UNIQUE_PIDS[@]} -eq 0 ]]; then
  echo "No POC processes found."
else
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
  REMAINING=$(pgrep -f 'claude.*-p.*--agents|relay\.sh|extract_result\.py|stream_filter\.py' 2>/dev/null || true)
  if [[ -n "$REMAINING" ]]; then
    echo "WARNING: Some processes may still be alive:"
    echo "$REMAINING" | while read pid; do
      ps -p "$pid" -o pid=,etime=,args= 2>/dev/null | head -c 120
      echo ""
    done
  else
    echo "All POC processes terminated."
  fi
fi

# ── Clean up team/task directories ──
echo ""
echo "── Cleaning Team Artifacts ──"
cleanup_teams
