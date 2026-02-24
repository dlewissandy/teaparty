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
PROJECT_PIDS=$(pgrep -f 'claude.*-p.*--agents.*project-lead' 2>/dev/null || true)
ART_PIDS=$(pgrep -f 'claude.*-p.*--agents.*art-lead' 2>/dev/null || true)
WRITING_PIDS=$(pgrep -f 'claude.*-p.*--agents.*writing-lead' 2>/dev/null || true)
EDITORIAL_PIDS=$(pgrep -f 'claude.*-p.*--agents.*editorial-lead' 2>/dev/null || true)
RELAY_PIDS=$(pgrep -f 'relay\.sh' 2>/dev/null || true)

if [[ -n "$PROJECT_PIDS" ]]; then
  for pid in $PROJECT_PIDS; do
    elapsed=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')
    cpu=$(ps -o %cpu= -p "$pid" 2>/dev/null | tr -d ' ')
    mem=$(ps -o rss= -p "$pid" 2>/dev/null | awk '{printf "%.0fMB", $1/1024}')
    echo "  PROJECT TEAM   PID=$pid  elapsed=$elapsed  cpu=${cpu}%  mem=$mem"
  done
else
  echo "  PROJECT TEAM   not running"
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

# ── Stream output (tee temp file) ──
echo "── Stream Activity ──"
# run.sh writes the temp file path to output/.stream-file
STREAM_POINTER="$SCRIPT_DIR/output/.stream-file"
TMPFILE=""
if [[ -f "$STREAM_POINTER" ]]; then
  TMPFILE=$(cat "$STREAM_POINTER" 2>/dev/null)
fi

if [[ -n "$TMPFILE" && -f "$TMPFILE" ]]; then
  LINES=$(wc -l < "$TMPFILE" 2>/dev/null || echo 0)
  SIZE=$(du -h "$TMPFILE" 2>/dev/null | cut -f1 || echo "?")
  echo "  Stream file: $TMPFILE ($LINES events, $SIZE)"
  echo ""

  # Count event types
  echo "  Event breakdown:"
  python3 -c "
import json, sys
from collections import Counter
counts = Counter()
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
                if isinstance(b, dict) and b.get('type') == 'text' and b.get('text','').strip():
                    last_agent_text = b['text'][:150]

for k, v in sorted(counts.items()):
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
for team in art writing editorial; do
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
[[ -n "$PROJECT_PIDS" ]] && RUNNING=$((RUNNING + 1))
[[ -n "$ART_PIDS" ]] && RUNNING=$((RUNNING + 1))
[[ -n "$WRITING_PIDS" ]] && RUNNING=$((RUNNING + 1))
[[ -n "$EDITORIAL_PIDS" ]] && RUNNING=$((RUNNING + 1))

if [[ $RUNNING -eq 0 ]]; then
  echo "  Status: IDLE (no team processes running)"
elif [[ $RUNNING -eq 1 && -n "$PROJECT_PIDS" ]]; then
  if [[ -n "$RELAY_PIDS" ]]; then
    echo "  Status: DISPATCHING (project team active, relay in progress)"
  else
    echo "  Status: COORDINATING (project team active, no subteams spawned yet)"
  fi
else
  echo "  Status: ACTIVE ($RUNNING team processes running)"
fi
