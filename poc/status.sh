#!/usr/bin/env bash
# POC Health & Status Dashboard
# Run anytime to see what's happening: ./poc/status.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== POC Status Dashboard ==="
echo "$(date)"
echo ""

# ── Running processes ──
echo "── Processes ──"
UBER_PIDS=$(pgrep -f 'claude.*-p.*--agent.*project-lead' 2>/dev/null || true)
ART_PIDS=$(pgrep -f 'claude.*-p.*--agents.*art-lead' 2>/dev/null || true)
WRITING_PIDS=$(pgrep -f 'claude.*-p.*--agents.*writing-lead' 2>/dev/null || true)
EDITORIAL_PIDS=$(pgrep -f 'claude.*-p.*--agents.*editorial-lead' 2>/dev/null || true)
RESEARCH_PIDS=$(pgrep -f 'claude.*-p.*--agents.*research-lead' 2>/dev/null || true)
RELAY_PIDS=$(ps -eo pid,args 2>/dev/null \
  | awk '/bash.*\/relay\.sh --team/ && !/plan-execute/ && !/claude -p/ {print $1}' \
  || true)

if [[ -n "$UBER_PIDS" ]]; then
  for pid in $UBER_PIDS; do
    elapsed=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')
    cpu=$(ps -o %cpu= -p "$pid" 2>/dev/null | tr -d ' ')
    mem=$(ps -o rss= -p "$pid" 2>/dev/null | awk '{printf "%.0fMB", $1/1024}')
    echo "  UBER TEAM      PID=$pid  elapsed=$elapsed  cpu=${cpu}%  mem=$mem"
  done
else
  echo "  UBER TEAM      not running"
fi

if [[ -n "$ART_PIDS" ]]; then
  for pid in $ART_PIDS; do
    elapsed=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')
    echo "  ART TEAM       PID=$pid  elapsed=$elapsed"
  done
else
  echo "  ART TEAM       not running"
fi

if [[ -n "$WRITING_PIDS" ]]; then
  for pid in $WRITING_PIDS; do
    elapsed=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')
    echo "  WRITING TEAM   PID=$pid  elapsed=$elapsed"
  done
else
  echo "  WRITING TEAM   not running"
fi

if [[ -n "$EDITORIAL_PIDS" ]]; then
  for pid in $EDITORIAL_PIDS; do
    elapsed=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')
    echo "  EDITORIAL TEAM PID=$pid  elapsed=$elapsed"
  done
else
  echo "  EDITORIAL TEAM not running"
fi

if [[ -n "$RESEARCH_PIDS" ]]; then
  for pid in $RESEARCH_PIDS; do
    elapsed=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')
    echo "  RESEARCH TEAM  PID=$pid  elapsed=$elapsed"
  done
else
  echo "  RESEARCH TEAM  not running"
fi

if [[ -n "$RELAY_PIDS" ]]; then
  for pid in $RELAY_PIDS; do
    # Try to figure out which team this relay is for
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
    # Format as relative time if recent
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

# ── Stream output (tee temp file) ──
echo "── Stream Activity ──"
# Find latest session directory (timestamped)
LATEST_SESSION=$(ls -td "$SCRIPT_DIR/output"/[0-9]*/ 2>/dev/null | head -1)

# Look for stream file in latest session, fall back to old location
TMPFILE=""
if [[ -n "$LATEST_SESSION" ]]; then
  # New layout: streams are inside session dir
  for sf in "$LATEST_SESSION/.exec-stream.jsonl" "$LATEST_SESSION/.plan-stream.jsonl"; do
    if [[ -f "$sf" ]]; then
      TMPFILE="$sf"
      break
    fi
  done
fi
# Fall back to old-style pointer
if [[ -z "$TMPFILE" ]]; then
  STREAM_POINTER="$SCRIPT_DIR/output/.stream-file"
  if [[ -f "$STREAM_POINTER" ]]; then
    TMPFILE=$(cat "$STREAM_POINTER" 2>/dev/null)
  fi
fi

if [[ -n "$TMPFILE" && -f "$TMPFILE" ]]; then
  LINES=$(wc -l < "$TMPFILE" 2>/dev/null || echo 0)
  SIZE=$(du -h "$TMPFILE" 2>/dev/null | cut -f1 || echo "?")
  echo "  Stream file: $TMPFILE ($LINES events, $SIZE)"
  echo ""

  # Count event types and team activity
  echo "  Event breakdown:"
  python3 -c "
import json, sys
from collections import Counter
counts = Counter()
team_activity = Counter()
errors = []
last_agent_text = ''
with open('$TMPFILE') as f:
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

for k, v in sorted(counts.items()):
    print(f'    {k}: {v}')

if team_activity:
    print()
    print('  Team coordination:')
    for k, v in sorted(team_activity.items()):
        print(f'    {k}: {v}')

if errors:
    print()
    print('  Errors:')
    for e in errors[-5:]:
        print(f'    ! {e}')
if last_agent_text:
    print()
    print(f'  Last agent message:')
    print(f'    {last_agent_text}')
" 2>/dev/null || echo "  (could not parse stream file)"
else
  echo "  No stream file found (run may not have started yet)"
fi

echo ""

# ── Output files ──
echo "── Output Files ──"

# Cross-session memory
CROSS_MEM="$SCRIPT_DIR/output/MEMORY.md"
if [[ -s "$CROSS_MEM" ]]; then
  size=$(du -h "$CROSS_MEM" 2>/dev/null | cut -f1)
  echo "  MEMORY.md ($size) — cross-session learnings"
elif [[ -f "$CROSS_MEM" ]]; then
  echo "  MEMORY.md (empty) — cross-session learnings"
fi

# List sessions
SESSIONS=$(ls -td "$SCRIPT_DIR/output"/[0-9]*/ 2>/dev/null || true)
if [[ -n "$SESSIONS" ]]; then
  SESSION_COUNT=$(echo "$SESSIONS" | wc -l | tr -d ' ')
  echo "  Sessions: $SESSION_COUNT"
  echo ""
fi

# Latest session detail
if [[ -n "$LATEST_SESSION" ]]; then
  echo "  Latest session: $(basename "$LATEST_SESSION")"

  # Session-level memory
  if [[ -s "$LATEST_SESSION/MEMORY.md" ]]; then
    echo "    MEMORY.md (session learnings)"
  fi

  for team in art writing editorial research; do
    dir="$LATEST_SESSION/$team"
    if [[ -d "$dir" ]]; then
      count=$(find "$dir" -type f -not -name '.*' 2>/dev/null | wc -l | tr -d ' ')
      has_mem=""
      [[ -f "$dir/MEMORY.md" ]] && has_mem=" [+MEMORY.md]"
      if [[ "$count" -gt 0 ]]; then
        echo "    $team/ ($count files)$has_mem:"
        find "$dir" -type f -not -name '.*' -exec ls -lh {} \; 2>/dev/null \
          | awk '{print "      " $NF " (" $5 ")"}'
      else
        echo "    $team/ (empty)$has_mem"
      fi
    fi
  done
else
  # Fall back to old flat layout
  for team in art writing editorial research; do
    dir="$SCRIPT_DIR/output/$team"
    if [[ -d "$dir" ]]; then
      count=$(find "$dir" -type f -not -name '.*' 2>/dev/null | wc -l | tr -d ' ')
      if [[ "$count" -gt 0 ]]; then
        echo "  $team/ ($count files):"
        find "$dir" -type f -not -name '.*' -exec ls -lh {} \; 2>/dev/null | awk '{print "    " $NF " (" $5 ")"}'
      else
        echo "  $team/ (empty)"
      fi
    fi
  done
fi

# Check for files written directly in poc/ (like the previous run did)
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
echo "── Summary ──"
RUNNING=0
[[ -n "$UBER_PIDS" ]] && RUNNING=$((RUNNING + 1))
[[ -n "$ART_PIDS" ]] && RUNNING=$((RUNNING + 1))
[[ -n "$WRITING_PIDS" ]] && RUNNING=$((RUNNING + 1))
[[ -n "$EDITORIAL_PIDS" ]] && RUNNING=$((RUNNING + 1))
[[ -n "$RESEARCH_PIDS" ]] && RUNNING=$((RUNNING + 1))

if [[ $RUNNING -eq 0 ]]; then
  echo "  Status: IDLE (no team processes running)"
elif [[ $RUNNING -eq 1 && -n "$UBER_PIDS" ]]; then
  if [[ -n "$RELAY_PIDS" ]]; then
    echo "  Status: TEAM ACTIVE (uber team running, relay in progress)"
  else
    echo "  Status: TEAM ACTIVE (uber team running, coordinating)"
  fi
else
  echo "  Status: ACTIVE ($RUNNING team processes running)"
fi
