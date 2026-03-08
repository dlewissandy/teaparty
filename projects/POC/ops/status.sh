#!/usr/bin/env bash
# POC Status Dashboard — what's running, is anything hung?
# Usage: ./projects/POC/ops/status.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROJECTS_DIR="$POC_ROOT"
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

# ── Helper: read CfA state file → "phase STATE backtrack_count" ──
read_cfa() {
  local f="$1"
  [[ -f "$f" ]] || return
  python3 -c "
import json, sys
with open(sys.argv[1]) as f: d = json.load(f)
print(d.get('phase','?'), d.get('state','?'), d.get('backtrack_count',0))
" "$f" 2>/dev/null
}

# ── Helper: format CfA info as "phase/STATE [↩N]" ──
format_cfa() {
  local cfa_info="$1"
  [[ -z "$cfa_info" ]] && return
  local cfa_phase="${cfa_info%% *}"
  local cfa_rest="${cfa_info#* }"
  local cfa_state="${cfa_rest%% *}"
  local cfa_bt="${cfa_rest#* }"
  local bt_tag=""
  [[ "$cfa_bt" -gt 0 ]] 2>/dev/null && bt_tag="  ↩${cfa_bt}"
  echo "$cfa_phase/$cfa_state$bt_tag"
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

  # Show root CfA state if present
  cfa_info=$(read_cfa "$sess_dir/.cfa-state.json")
  cfa_fmt=$(format_cfa "$cfa_info")
  [[ -n "$cfa_fmt" ]] && echo "     └ cfa: $cfa_fmt"

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

  team_output=""
  for team in art writing editorial research coding; do
    team_dir="$sess_dir/$team"
    [[ -d "$team_dir" ]] || continue

    # Collect dispatch info — most recent first
    dispatches=()
    active=0
    done_count=0
    for dd in $(ls -td "$team_dir"/[0-9]*/ 2>/dev/null); do
      [[ -d "$dd" ]] || continue
      dispatch_ts=$(basename "$dd")
      if [[ -f "$dd/.running" ]]; then
        active=$((active + 1))
        # Read CfA state for active dispatch
        dcfa=$(read_cfa "$dd/.cfa-state.json")
        dcfa_fmt=$(format_cfa "$dcfa")
        if [[ -n "$dcfa_fmt" ]]; then
          dispatches+=("▶ $dispatch_ts  $dcfa_fmt")
        else
          mtime=$(stat -f%m "$dd/.running" 2>/dev/null || stat -c%Y "$dd/.running" 2>/dev/null || echo "$NOW")
          age_s=$(( NOW - mtime ))
          dispatches+=("▶ $dispatch_ts  running $(human_age $age_s)")
        fi
      else
        done_count=$((done_count + 1))
      fi
    done

    [[ $active -eq 0 && $done_count -eq 0 ]] && continue

    # Build team summary
    summary=""
    [[ $active -gt 0 ]] && summary="$active active"
    [[ $done_count -gt 0 ]] && summary="${summary:+$summary, }$done_count done"
    team_output="${team_output}    $team ($summary)\n"

    # Show active dispatch details
    for dline in "${dispatches[@]+"${dispatches[@]}"}"; do
      [[ -z "$dline" ]] && continue
      team_output="${team_output}      $dline\n"
    done
  done

  if [[ -n "$team_output" ]]; then
    echo "  $proj"
    echo -e "$team_output"
    had_dispatches=true
  fi
done

if [[ "$had_dispatches" == "false" ]]; then
  echo "  (none)"
fi
