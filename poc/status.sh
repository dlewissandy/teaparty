#!/usr/bin/env bash
# POC Health & Status Dashboard
# Run anytime to see what's happening: ./poc/status.sh
# Supports multiple concurrent uber sessions across projects.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECTS_DIR="$SCRIPT_DIR/output/projects"

echo "=== POC Status Dashboard ==="
echo "$(date)"
echo ""

# ── Discover running processes ──
UBER_PIDS=$(pgrep -f 'claude.*-p.*--agent.*project-lead' 2>/dev/null || true)
ART_PIDS=$(pgrep -f 'claude.*-p.*--agents.*art-lead' 2>/dev/null || true)
WRITING_PIDS=$(pgrep -f 'claude.*-p.*--agents.*writing-lead' 2>/dev/null || true)
EDITORIAL_PIDS=$(pgrep -f 'claude.*-p.*--agents.*editorial-lead' 2>/dev/null || true)
RESEARCH_PIDS=$(pgrep -f 'claude.*-p.*--agents.*research-lead' 2>/dev/null || true)
RELAY_PIDS=$(ps -eo pid,args 2>/dev/null \
  | awk '/bash.*\/relay\.sh --team/ && !/plan-execute/ && !/claude -p/ {print $1}' \
  || true)

# ── Build PID → session correlation via cwd ──
# Each claude process's cwd is its session dir (set by plan-execute.sh)
PID_MAP=$(mktemp)
trap "rm -f $PID_MAP" EXIT

for pid in $UBER_PIDS $ART_PIDS $WRITING_PIDS $EDITORIAL_PIDS $RESEARCH_PIDS; do
  [[ -z "$pid" ]] && continue
  cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | awk '/^n/{print substr($0,2); exit}')
  if [[ -n "$cwd" && "$cwd" == *"/output/"* ]]; then
    # Extract project and session from path
    # Pattern: .../output/projects/<project>/<session>/...
    proj=$(echo "$cwd" | sed -n 's|.*/output/projects/\([^/]*\)/.*|\1|p')
    sess=$(echo "$cwd" | sed -n 's|.*/output/projects/[^/]*/\([0-9][0-9]*-[0-9]*\).*|\1|p')
    sess_dir=$(echo "$cwd" | sed -n 's|\(.*/output/projects/[^/]*/[0-9][0-9]*-[0-9]*\).*|\1|p')
    if [[ -n "$proj" && -n "$sess" ]]; then
      echo "$pid:$proj:$sess:$sess_dir" >> "$PID_MAP"
    fi
  fi
done

# Helper: look up project for a PID
pid_project() { awk -F: -v pid="$1" '$1==pid {print $2; exit}' "$PID_MAP"; }
pid_session() { awk -F: -v pid="$1" '$1==pid {print $3; exit}' "$PID_MAP"; }

# Collect unique active session dirs (for uber processes only)
ACTIVE_SESSIONS=""
if [[ -n "$UBER_PIDS" ]]; then
  for pid in $UBER_PIDS; do
    sess_dir=$(awk -F: -v pid="$pid" '$1==pid {print $4; exit}' "$PID_MAP")
    if [[ -n "$sess_dir" ]]; then
      ACTIVE_SESSIONS="$ACTIVE_SESSIONS $sess_dir"
    fi
  done
fi

# ── Processes ──
echo "── Processes ──"

if [[ -n "$UBER_PIDS" ]]; then
  for pid in $UBER_PIDS; do
    elapsed=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')
    cpu=$(ps -o %cpu= -p "$pid" 2>/dev/null | tr -d ' ')
    mem=$(ps -o rss= -p "$pid" 2>/dev/null | awk '{printf "%.0fMB", $1/1024}')
    proj=$(pid_project "$pid")
    sess=$(pid_session "$pid")
    context=""
    [[ -n "$proj" ]] && context="  project=$proj"
    [[ -n "$sess" ]] && context="$context  session=$sess"
    echo "  UBER TEAM      PID=$pid$context  elapsed=$elapsed  cpu=${cpu}%  mem=$mem"
  done
else
  echo "  UBER TEAM      not running"
fi

show_team_pids() {
  local label="$1" pids="$2"
  if [[ -n "$pids" ]]; then
    for pid in $pids; do
      elapsed=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')
      proj=$(pid_project "$pid")
      context=""
      [[ -n "$proj" ]] && context="  project=$proj"
      echo "  $label PID=$pid$context  elapsed=$elapsed"
    done
  else
    echo "  $label not running"
  fi
}

show_team_pids "ART TEAM      " "$ART_PIDS"
show_team_pids "WRITING TEAM  " "$WRITING_PIDS"
show_team_pids "EDITORIAL TEAM" "$EDITORIAL_PIDS"
show_team_pids "RESEARCH TEAM " "$RESEARCH_PIDS"

if [[ -n "$RELAY_PIDS" ]]; then
  for pid in $RELAY_PIDS; do
    relay_args=$(ps -o args= -p "$pid" 2>/dev/null || true)
    team=$(echo "$relay_args" | sed -n 's/.*--team \([a-z]*\).*/\1/p' 2>/dev/null)
    team="${team:-?}"
    echo "  RELAY          PID=$pid  team=$team"
  done
fi

echo ""

# ── Agent teams (from ~/.claude/teams/) ──
echo "── Agent Teams ──"
TEAMS_DIR="$HOME/.claude/teams"
if [[ -d "$TEAMS_DIR" ]]; then
  python3 -c "
import json, os, glob, sys

poc_dir = '$SCRIPT_DIR'
teams_dir = os.path.expanduser('~/.claude/teams')
tasks_dir = os.path.expanduser('~/.claude/tasks')
found = 0

for config_path in sorted(glob.glob(os.path.join(teams_dir, '*/config.json'))):
    try:
        with open(config_path) as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, IOError):
        continue

    # Check if this team is POC-related (any member cwd under poc dir)
    members = cfg.get('members', [])
    cwds = [m.get('cwd', '') for m in members]
    if not any(poc_dir in cwd for cwd in cwds):
        continue

    team_name = cfg.get('name', os.path.basename(os.path.dirname(config_path)))
    member_names = [m.get('name', '?') for m in members]

    # Count tasks
    team_dir_name = os.path.basename(os.path.dirname(config_path))
    task_dir = os.path.join(tasks_dir, team_dir_name)
    task_count = 0
    if os.path.isdir(task_dir):
        task_count = len([f for f in os.listdir(task_dir) if f.endswith('.json')])

    created = cfg.get('createdAt', 0)
    import time
    age_s = time.time() - (created / 1000) if created else 0
    if age_s < 60:
        age = f'{int(age_s)}s ago'
    elif age_s < 3600:
        age = f'{int(age_s/60)}m ago'
    elif age_s < 86400:
        age = f'{int(age_s/3600)}h ago'
    else:
        age = f'{int(age_s/86400)}d ago'

    print(f'  {team_name} ({len(members)} members, {task_count} tasks, {age})')
    print(f'    members: {', '.join(member_names)}')
    found += 1

if found == 0:
    print('  No POC-related teams found')
" 2>/dev/null || echo "  (could not read team files)"
else
  echo "  No teams directory found"
fi

echo ""

# ── Stream Activity ──
# Shows streams for all active sessions, falls back to most recent if idle.
echo "── Stream Activity ──"

# Python function for parsing a stream file — called per session
show_stream() {
  local stream_file="$1" label="$2"
  [[ -f "$stream_file" ]] || return

  local lines size
  lines=$(wc -l < "$stream_file" 2>/dev/null || echo 0)
  size=$(du -h "$stream_file" 2>/dev/null | cut -f1 || echo "?")
  echo "  [$label] $(basename "$(dirname "$stream_file")")/ ($lines events, $size)"

  python3 -c "
import json, sys
from collections import Counter
counts = Counter()
team_activity = Counter()
errors = []
last_agent_text = ''
with open('$stream_file') as f:
    for line in f:
        line = line.strip()
        if not line: continue
        try:
            ev = json.loads(line)
        except: continue
        t = ev.get('type', 'unknown')
        counts[t] += 1
        if t == 'user':
            for b in ev.get('message',{}).get('content',[]):
                if isinstance(b, dict) and b.get('is_error'):
                    errors.append(b.get('content','')[:80])
        elif t == 'assistant':
            content = ev.get('message',{}).get('content',[])
            for b in content:
                if not isinstance(b, dict): continue
                bt = b.get('type','')
                if bt == 'text' and b.get('text','').strip():
                    last_agent_text = b['text'][:150]
                elif bt == 'tool_use':
                    name = b.get('name','')
                    if name == 'TeamCreate':
                        team_activity['TeamCreate'] += 1
                    elif name == 'SendMessage':
                        msg_type = b.get('input',{}).get('type','message')
                        if msg_type == 'broadcast':
                            team_activity['SendMessage (broadcast)'] += 1
                        elif msg_type in ('shutdown_request', 'shutdown_response'):
                            team_activity[f'SendMessage ({msg_type})'] += 1
                        else:
                            team_activity['SendMessage (DM)'] += 1
                    elif name == 'TeamDelete':
                        team_activity['TeamDelete'] += 1
                    elif name == 'Task':
                        team_activity['Task (dispatch)'] += 1

print('    ' + '  '.join(f'{k}: {v}' for k, v in sorted(counts.items())))

if team_activity:
    print('    coordination: ' + '  '.join(f'{k}: {v}' for k, v in sorted(team_activity.items())))

if errors:
    for e in errors[-3:]:
        print(f'    ! {e}')
if last_agent_text:
    print(f'    last: {last_agent_text}')
" 2>/dev/null || echo "    (could not parse stream)"
  echo ""
}

SHOWED_STREAM=false

# Show streams for all active sessions first
if [[ -n "$ACTIVE_SESSIONS" ]]; then
  for sess_dir in $ACTIVE_SESSIONS; do
    proj=$(basename "$(dirname "$sess_dir")")
    for sf in "$sess_dir/.exec-stream.jsonl" "$sess_dir/.plan-stream.jsonl"; do
      if [[ -f "$sf" ]]; then
        show_stream "$sf" "$proj"
        SHOWED_STREAM=true
        break
      fi
    done
  done
fi

# If nothing active, fall back to most recent session across all projects
if [[ "$SHOWED_STREAM" != "true" ]]; then
  FALLBACK_SESSION=""
  FALLBACK_PROJECT=""

  if [[ -d "$PROJECTS_DIR" ]]; then
    for proj_dir in "$PROJECTS_DIR"/*/; do
      [[ -d "$proj_dir" ]] || continue
      for sess_dir in $(ls -td "$proj_dir"[0-9]*/ 2>/dev/null | head -1); do
        sess_ts=$(basename "$sess_dir")
        if [[ -z "$FALLBACK_SESSION" ]] || [[ "$sess_ts" > "$(basename "$FALLBACK_SESSION")" ]]; then
          FALLBACK_SESSION="$sess_dir"
          FALLBACK_PROJECT="$(basename "$proj_dir")"
        fi
      done
    done
  fi

  # Check old layout too
  OLD_LATEST=$(ls -td "$SCRIPT_DIR/output"/[0-9]*/ 2>/dev/null | head -1)
  if [[ -n "$OLD_LATEST" ]]; then
    if [[ -z "$FALLBACK_SESSION" ]] || [[ "$(basename "$OLD_LATEST")" > "$(basename "$FALLBACK_SESSION")" ]]; then
      FALLBACK_SESSION="$OLD_LATEST"
      FALLBACK_PROJECT="(legacy)"
    fi
  fi

  if [[ -n "$FALLBACK_SESSION" ]]; then
    for sf in "$FALLBACK_SESSION/.exec-stream.jsonl" "$FALLBACK_SESSION/.plan-stream.jsonl"; do
      if [[ -f "$sf" ]]; then
        show_stream "$sf" "${FALLBACK_PROJECT:-?}"
        SHOWED_STREAM=true
        break
      fi
    done
  fi

  # Final fallback: old-style stream pointer
  if [[ "$SHOWED_STREAM" != "true" ]]; then
    STREAM_POINTER="$SCRIPT_DIR/output/.stream-file"
    if [[ -f "$STREAM_POINTER" ]]; then
      sf=$(cat "$STREAM_POINTER" 2>/dev/null)
      if [[ -n "$sf" && -f "$sf" ]]; then
        show_stream "$sf" "legacy"
        SHOWED_STREAM=true
      fi
    fi
  fi

  if [[ "$SHOWED_STREAM" != "true" ]]; then
    echo "  No stream file found (run may not have started yet)"
    echo ""
  fi
fi

# ── Output files ──
echo "── Output Files ──"

# Helper: check if a session dir is active
is_active_session() {
  local dir="$1"
  for d in $ACTIVE_SESSIONS; do
    [[ "$d" == "$dir" || "$d/" == "$dir" ]] && return 0
  done
  return 1
}

# Global memory
GLOBAL_MEM="$SCRIPT_DIR/output/MEMORY.md"
if [[ -s "$GLOBAL_MEM" ]]; then
  size=$(du -h "$GLOBAL_MEM" 2>/dev/null | cut -f1)
  echo "  MEMORY.md ($size) — global learnings (all projects)"
elif [[ -f "$GLOBAL_MEM" ]]; then
  echo "  MEMORY.md (empty) — global learnings"
fi

# List projects
if [[ -d "$PROJECTS_DIR" ]]; then
  PROJECT_NAMES=$(ls -d "$PROJECTS_DIR"/*/ 2>/dev/null || true)
  if [[ -n "$PROJECT_NAMES" ]]; then
    PROJECT_COUNT=$(echo "$PROJECT_NAMES" | wc -l | tr -d ' ')
    echo "  Projects: $PROJECT_COUNT"
    echo ""

    for proj_dir in "$PROJECTS_DIR"/*/; do
      [[ -d "$proj_dir" ]] || continue
      proj_name="$(basename "$proj_dir")"
      session_count=$(ls -d "$proj_dir"[0-9]*/ 2>/dev/null | wc -l | tr -d ' ')
      has_mem=""
      [[ -s "$proj_dir/MEMORY.md" ]] && has_mem=" [+MEMORY.md]"
      echo "  $proj_name/ ($session_count sessions)$has_mem"

      # Show sessions for this project (latest first, limit to 3)
      sess_shown=0
      for sess_dir in $(ls -td "$proj_dir"[0-9]*/ 2>/dev/null); do
        [[ -d "$sess_dir" ]] || continue
        sess_name="$(basename "$sess_dir")"
        active_tag=""
        is_active_session "$sess_dir" && active_tag=" [ACTIVE]"

        # Only show detail for active sessions or the latest
        if [[ -n "$active_tag" || $sess_shown -eq 0 ]]; then
          echo "    $sess_name/$active_tag"

          # Session-level memory
          if [[ -s "$sess_dir/MEMORY.md" ]]; then
            echo "      MEMORY.md (session learnings)"
          fi

          for team in art writing editorial research; do
            team_dir="$sess_dir/$team"
            if [[ -d "$team_dir" ]]; then
              dispatch_count=$(ls -d "$team_dir"/[0-9]*/ 2>/dev/null | wc -l | tr -d ' ')
              file_count=$(find "$team_dir" -type f -not -name '.*' 2>/dev/null | wc -l | tr -d ' ')
              has_team_mem=""
              for dm in "$team_dir"/*/MEMORY.md; do
                if [[ -s "$dm" ]]; then
                  has_team_mem=" [+MEMORY.md]"
                  break
                fi
              done 2>/dev/null
              if [[ "$dispatch_count" -gt 0 ]]; then
                echo "      $team/ ($dispatch_count dispatches, $file_count files)$has_team_mem"
              elif [[ "$file_count" -gt 0 ]]; then
                echo "      $team/ ($file_count files)$has_team_mem"
              fi
            fi
          done
        else
          # Compact listing for older non-active sessions
          file_count=$(find "$sess_dir" -type f -not -name '.*' 2>/dev/null | wc -l | tr -d ' ')
          echo "    $sess_name/ ($file_count files)"
        fi

        sess_shown=$((sess_shown + 1))
        [[ $sess_shown -ge 3 ]] && break
      done

      # Note if there are more sessions not shown
      if [[ "$session_count" -gt 3 ]]; then
        echo "    ... and $((session_count - 3)) older sessions"
      fi
    done
  fi
fi

# Old-layout sessions (backwards compat)
OLD_SESSIONS=$(ls -td "$SCRIPT_DIR/output"/[0-9]*/ 2>/dev/null || true)
if [[ -n "$OLD_SESSIONS" ]]; then
  OLD_COUNT=$(echo "$OLD_SESSIONS" | wc -l | tr -d ' ')
  echo ""
  echo "  Legacy sessions (flat layout): $OLD_COUNT"
fi

# Stray files in poc/
STRAY=$(find "$SCRIPT_DIR" -maxdepth 1 -name '*.md' -o -name '*.svg' -o -name '*.dot' -o -name '*.tex' 2>/dev/null)
if [[ -n "$STRAY" ]]; then
  echo ""
  echo "  Stray files in poc/ (written outside output dirs):"
  echo "$STRAY" | while read f; do
    size=$(du -h "$f" | cut -f1)
    echo "    $(basename "$f") ($size)"
  done
fi

echo ""

# ── Summary ──
echo "── Summary ──"

# Count running processes
UBER_COUNT=0
SUBTEAM_COUNT=0
[[ -n "$UBER_PIDS" ]] && UBER_COUNT=$(echo "$UBER_PIDS" | wc -w | tr -d ' ')
for pids in "$ART_PIDS" "$WRITING_PIDS" "$EDITORIAL_PIDS" "$RESEARCH_PIDS"; do
  [[ -n "$pids" ]] && SUBTEAM_COUNT=$((SUBTEAM_COUNT + $(echo "$pids" | wc -w | tr -d ' ')))
done
TOTAL_PROCS=$((UBER_COUNT + SUBTEAM_COUNT))

# Count unique active projects
ACTIVE_PROJECTS=""
if [[ -s "$PID_MAP" ]]; then
  ACTIVE_PROJECTS=$(awk -F: '{print $2}' "$PID_MAP" | sort -u | paste -sd ',' -)
fi

if [[ $TOTAL_PROCS -eq 0 ]]; then
  echo "  Status: IDLE (no team processes running)"
elif [[ $UBER_COUNT -eq 1 && $SUBTEAM_COUNT -eq 0 ]]; then
  proj=$(pid_project "$(echo "$UBER_PIDS" | awk '{print $1}')")
  if [[ -n "$RELAY_PIDS" ]]; then
    echo "  Status: ACTIVE (project: ${proj:-?} | uber + relay in progress)"
  else
    echo "  Status: ACTIVE (project: ${proj:-?} | uber coordinating)"
  fi
elif [[ $UBER_COUNT -gt 1 ]]; then
  echo "  Status: ACTIVE ($UBER_COUNT projects: $ACTIVE_PROJECTS | $TOTAL_PROCS processes)"
else
  echo "  Status: ACTIVE (${ACTIVE_PROJECTS:-?} | $TOTAL_PROCS processes)"
fi
