#!/usr/bin/env bash
# PreToolUse hook: block writes outside the project scope.
#
# In linked-repo mode, the agent's --add-dir grants read+write to the full
# worktree. This hook restricts writes to the project subdirectory only.
#
# Expects POC_PROJECT_WORKDIR env var (set via settings.json env section).
# If unset, allows all writes (standalone/non-scoped mode).
set -euo pipefail

WRITE_SCOPE="${POC_PROJECT_WORKDIR:-}"
[[ -z "$WRITE_SCOPE" ]] && exit 0  # No scope set — allow all writes

# Read hook input from stdin
INPUT=$(cat)

# Extract file_path from tool_input, resolve to absolute path
FILE_PATH=$(echo "$INPUT" | python3 -c "
import json, sys, os
try:
    d = json.load(sys.stdin)
    fp = d.get('tool_input', {}).get('file_path', '')
    if fp:
        print(os.path.realpath(fp))
    else:
        print('')
except:
    print('')
" 2>/dev/null) || true

# No file path — not a write tool, allow
[[ -z "$FILE_PATH" ]] && exit 0

# Resolve scope to real path for consistent comparison
REAL_SCOPE=$(python3 -c "import os; print(os.path.realpath('$WRITE_SCOPE'))" 2>/dev/null) || REAL_SCOPE="$WRITE_SCOPE"

# Allow: project workdir, temp dirs, session infra dir
case "$FILE_PATH" in
  "$REAL_SCOPE"/*|"$REAL_SCOPE") exit 0 ;;
  /tmp/*|/private/tmp/*|/var/folders/*) exit 0 ;;
esac

# Allow session infra dir (stream files, escalation files, etc.)
if [[ -n "${POC_SESSION_DIR:-}" ]]; then
  REAL_SESSION=$(python3 -c "import os; print(os.path.realpath('${POC_SESSION_DIR}'))" 2>/dev/null) || REAL_SESSION="$POC_SESSION_DIR"
  case "$FILE_PATH" in
    "$REAL_SESSION"/*|"$REAL_SESSION") exit 0 ;;
  esac
fi

# Block — output deny JSON
jq -n \
  --arg reason "Write blocked: path '$FILE_PATH' is outside project scope '$REAL_SCOPE'. Write only to your project directory." \
  '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
