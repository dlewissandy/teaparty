#!/usr/bin/env bash
# POC Status Dashboard — what's running, is anything hung?
# Usage: ./poc/status.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROJECTS_DIR="$POC_ROOT/projects"
NOW=$(date +%s)

echo "=== POC Status ==="
echo "$(date '+%H:%M:%S')"
echo ""

# ── Helper: age in human-readable form ──
human_age() {
  local s=$1
  if [[ $s -lt 60 ]]; then echo "${s}s"
  elif [[ $s -lt 3600 ]]; then echo "$((s / 60))m"
  else echo "$((s / 3600))h$((s % 3600 / 60))m"
  fi
}

# ── Helper: stream health + phase for a session dir ──
# Returns "<emoji> <phase> <age_seconds>" — e.g. "🟢 intent 23"
session_health() {
  local sess_dir="$1"
  local stream="" phase="" best_mtime=0

  for sf_phase in \
    "$sess_dir/.intent-stream.jsonl:intent" \
    "$sess_dir/.plan-stream.jsonl:plan" \
    "$sess_dir/.exec-stream.jsonl:execute"; do
    local sf="${sf_phase%%:*}"
    local ph="${sf_phase#*:}"
    [[ -f "$sf" ]] || continue
    local mt
    mt=$(stat -f%m "$sf" 2>/dev/null || stat -c%Y "$sf" 2>/dev/null || echo 0)
    if [[ $mt -ge $best_mtime ]]; then
      best_mtime=$mt
      stream="$sf"
      phase="$ph"
    fi
  done
  [[ -z "$stream" ]] && return

  local age_s=$(( NOW - best_mtime ))
  local emoji
  if [[ $age_s -ge 3600 ]]; then emoji="⚫"
  elif [[ $age_s -ge 1800 ]]; then emoji="🔴"
  elif [[ $age_s -ge 300 ]]; then emoji="🟡"
  else emoji="🟢"
  fi

  echo "$emoji $phase $age_s"
}

# ── Helper: find PIDs associated with a project ──
# Checks run.sh, intent.sh, plan-execute.sh, and claude -p processes.
# Returns newline-separated "PID LABEL" pairs.
project_pids() {
  local proj="$1"
  local proj_dir="$2"

  # Look for orchestrator processes (run.sh, intent.sh, plan-execute.sh)
  # that reference this project in their arguments or CWD
  for pid in $(pgrep -f "(run\.sh|intent\.sh|plan-execute\.sh)" 2>/dev/null || true); do
    [[ -z "$pid" ]] && continue
    local cmd
    cmd=$(ps -o command= -p "$pid" 2>/dev/null) || continue
    # Match by project path in command args
    if [[ "$cmd" == *"$proj_dir"* || "$cmd" == *"--project $proj "* || "$cmd" == *"--project $proj" ]]; then
      # Determine label from command
      local label="run.sh"
      [[ "$cmd" == *"intent.sh"* ]] && label="intent"
      [[ "$cmd" == *"plan-execute"* ]] && label="plan-exec"
      echo "$pid $label"
    fi
  done

  # Look for claude -p processes with CWD in this project
  for pid in $(pgrep -f "claude.*-p" 2>/dev/null || true); do
    [[ -z "$pid" ]] && continue
    local cwd
    cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | awk '/^n/{print substr($0,2); exit}')
    if [[ -n "$cwd" && ( "$cwd" == *"/$proj/"* || "$cwd" == *"/$proj" ) ]]; then
      local cpu
      cpu=$(ps -o %cpu= -p "$pid" 2>/dev/null | tr -d ' ')
      echo "$pid claude(${cpu}%)"
    fi
  done
}

# ── Sessions ──
echo "── Sessions ──"

found_sessions=false
for proj_dir in "$PROJECTS_DIR"/*/; do
  [[ -d "$proj_dir/.sessions" ]] || continue
  proj=$(basename "$proj_dir")

  sess_dir=$(ls -td "$proj_dir/.sessions"/[0-9]*/ 2>/dev/null | head -1)
  [[ -d "$sess_dir" ]] || continue

  health_info=$(session_health "$sess_dir")
  [[ -z "$health_info" ]] && continue

  emoji="${health_info%% *}"
  rest="${health_info#* }"
  phase="${rest%% *}"
  age_s="${rest#* }"

  # Find processes associated with this project
  pids_info=$(project_pids "$proj" "$proj_dir")

  # Skip dead sessions: stale (> 2 hours) with no running process
  if [[ $age_s -ge 7200 && -z "$pids_info" ]]; then
    continue
  fi

  # Determine if alive (has process) or just has recent stream activity
  sess_ts=$(basename "$sess_dir")
  if [[ -n "$pids_info" ]]; then
    # Show with process info
    pid_line=""
    while IFS= read -r pid_entry; do
      pid_num="${pid_entry%% *}"
      pid_label="${pid_entry#* }"
      elapsed=$(ps -o etime= -p "$pid_num" 2>/dev/null | tr -d ' ')
      if [[ -n "$pid_line" ]]; then
        pid_line="$pid_line, $pid_label PID=$pid_num ($elapsed)"
      else
        pid_line="$pid_label PID=$pid_num ($elapsed)"
      fi
    done <<< "$pids_info"
    echo "  $emoji $proj  phase=$phase  age=$(human_age $age_s)  session=$sess_ts"
    echo "     └ $pid_line"
  else
    # No process but recent enough to show — mark as stopped
    echo "  ⏹  $proj  phase=$phase  age=$(human_age $age_s)  session=$sess_ts  (no process)"
  fi
  found_sessions=true
done

if [[ "$found_sessions" == "false" ]]; then
  echo "  (none)"
fi

echo ""

# ── Dispatches ──
echo "── Dispatches ──"

had_dispatches=false
for proj_dir in "$PROJECTS_DIR"/*/; do
  [[ -d "$proj_dir/.sessions" ]] || continue
  proj=$(basename "$proj_dir")

  sess_dir=$(ls -td "$proj_dir/.sessions"/[0-9]*/ 2>/dev/null | head -1)
  [[ -d "$sess_dir" ]] || continue

  line=""
  for team in intent art writing editorial research coding; do
    team_dir="$sess_dir/$team"
    [[ -d "$team_dir" ]] || continue
    total=$( (ls -d "$team_dir"/[0-9]*/ 2>/dev/null || true) | wc -l | tr -d ' ')
    [[ "$total" -eq 0 ]] && continue

    active=0
    active_age=""
    for dd in "$team_dir"/[0-9]*/; do
      if [[ -f "$dd/.running" ]]; then
        active=$((active + 1))
        mtime=$(stat -f%m "$dd/.running" 2>/dev/null || stat -c%Y "$dd/.running" 2>/dev/null || echo "$NOW")
        age_s=$(( NOW - mtime ))
        active_age="$(human_age $age_s)"
      fi
    done 2>/dev/null

    done_count=$((total - active))
    if [[ "$active" -gt 0 ]]; then
      tag="$active RUNNING ($active_age)"
      [[ "$done_count" -gt 0 ]] && tag="$tag, $done_count done"
      line="$line  $team: $tag"
    else
      line="$line  $team: $total done"
    fi
  done

  if [[ -n "$line" ]]; then
    echo "  $proj"
    echo "   $line"
    had_dispatches=true
  fi
done

if [[ "$had_dispatches" == "false" ]]; then
  echo "  (none)"
fi
