#!/usr/bin/env bash
# POC Status Dashboard — what's running, is anything hung?
# Usage: ./poc/status.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECTS_DIR="$SCRIPT_DIR/output/projects"
NOW=$(date +%s)

echo "=== POC Status ==="
echo "$(date '+%H:%M:%S')"
echo ""

# ── Discover processes ──
UBER_PIDS=$(pgrep -f 'claude.*-p.*--agent.*project-lead' 2>/dev/null || true)
ART_PIDS=$(pgrep -f 'claude.*-p.*--agents.*art-lead' 2>/dev/null || true)
WRITING_PIDS=$(pgrep -f 'claude.*-p.*--agents.*writing-lead' 2>/dev/null || true)
EDITORIAL_PIDS=$(pgrep -f 'claude.*-p.*--agents.*editorial-lead' 2>/dev/null || true)
RESEARCH_PIDS=$(pgrep -f 'claude.*-p.*--agents.*research-lead' 2>/dev/null || true)
CODING_PIDS=$(pgrep -f 'claude.*-p.*--agents.*coding-lead' 2>/dev/null || true)

ALL_SUBTEAM_PIDS="$ART_PIDS $WRITING_PIDS $EDITORIAL_PIDS $RESEARCH_PIDS $CODING_PIDS"

# PID → project map via cwd
PID_MAP=$(mktemp)
trap "rm -f $PID_MAP" EXIT

for pid in $UBER_PIDS $ALL_SUBTEAM_PIDS; do
  [[ -z "$pid" ]] && continue
  cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | awk '/^n/{print substr($0,2); exit}')
  if [[ -n "$cwd" && "$cwd" == *"/output/"* ]]; then
    proj=$(echo "$cwd" | sed -n 's|.*/output/projects/\([^/]*\)/.*|\1|p')
    [[ -n "$proj" ]] && echo "$pid:$proj" >> "$PID_MAP"
  fi
done

pid_project() { awk -F: -v pid="$1" '$1==pid {print $2; exit}' "$PID_MAP"; }

# Stream health for a project: check mtime of most recent session stream
# Returns: 🟢 (<5m), 🟡 (5-10m), 🔴 (>10m), empty (no stream)
project_health() {
  local proj_dir="$1"
  [[ -d "$proj_dir/.sessions" ]] || return
  local sess_dir
  sess_dir=$(ls -td "$proj_dir/.sessions"/[0-9]*/ 2>/dev/null | head -1)
  [[ -d "$sess_dir" ]] || return

  local stream=""
  for sf in "$sess_dir/.exec-stream.jsonl" "$sess_dir/.plan-stream.jsonl"; do
    [[ -f "$sf" ]] && { stream="$sf"; break; }
  done
  [[ -z "$stream" ]] && return

  local mtime age_s
  mtime=$(stat -f%m "$stream" 2>/dev/null || stat -c%Y "$stream" 2>/dev/null || echo "$NOW")
  age_s=$(( NOW - mtime ))

  if [[ $age_s -ge 3600 ]]; then
    echo "⚫"
  elif [[ $age_s -ge 1800 ]]; then
    echo "🔴"
  elif [[ $age_s -ge 600 ]]; then
    echo "🟡"
  else
    echo "🟢"
  fi
}

# ── Processes ──
echo "── Processes ──"

if [[ -z "$UBER_PIDS" ]]; then
  echo "  (none)"
else
  for pid in $UBER_PIDS; do
    elapsed=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')
    cpu=$(ps -o %cpu= -p "$pid" 2>/dev/null | tr -d ' ')
    proj=$(pid_project "$pid")
    proj_dir="$PROJECTS_DIR/${proj:-_none_}"

    health=$(project_health "$proj_dir")
    echo "  ${health:-  } UBER  ${proj:-?}  elapsed=$elapsed  cpu=${cpu}%"

    # Show subteams belonging to this project
    for label_pids in "ART:$ART_PIDS" "WRITING:$WRITING_PIDS" "EDITORIAL:$EDITORIAL_PIDS" "RESEARCH:$RESEARCH_PIDS" "CODING:$CODING_PIDS"; do
      label="${label_pids%%:*}"
      pids="${label_pids#*:}"
      for spid in $pids; do
        [[ -z "$spid" ]] && continue
        sproj=$(pid_project "$spid")
        if [[ "$sproj" == "$proj" ]]; then
          selapsed=$(ps -o etime= -p "$spid" 2>/dev/null | tr -d ' ')
          echo "     └ $label  PID=$spid  elapsed=$selapsed"
        fi
      done
    done
  done
fi

echo ""

# ── Dispatches ──
echo "── Dispatches ──"

had_dispatches=false
for proj_dir in "$PROJECTS_DIR"/*/; do
  [[ -d "$proj_dir/.sessions" ]] || continue
  proj=$(basename "$proj_dir")

  # Find active session (most recent)
  sess_dir=$(ls -td "$proj_dir/.sessions"/[0-9]*/ 2>/dev/null | head -1)
  [[ -d "$sess_dir" ]] || continue

  line=""
  for team in art writing editorial research coding; do
    team_dir="$sess_dir/$team"
    [[ -d "$team_dir" ]] || continue
    total=$( (ls -d "$team_dir"/[0-9]*/ 2>/dev/null || true) | wc -l | tr -d ' ')
    [[ "$total" -eq 0 ]] && continue

    # Count active (.running sentinel) and compute age of active dispatch
    active=0
    active_age=""
    for dd in "$team_dir"/[0-9]*/; do
      if [[ -f "$dd/.running" ]]; then
        active=$((active + 1))
        mtime=$(stat -f%m "$dd/.running" 2>/dev/null || stat -c%Y "$dd/.running" 2>/dev/null || echo "$NOW")
        age_s=$(( NOW - mtime ))
        if [[ $age_s -lt 60 ]]; then
          active_age="${age_s}s"
        else
          active_age="$((age_s / 60))m"
        fi
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
