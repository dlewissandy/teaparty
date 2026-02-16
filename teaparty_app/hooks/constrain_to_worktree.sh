#!/usr/bin/env bash
#
# PreToolUse hook: validate that file operations stay within the worktree.
#
# Usage: constrain_to_worktree.sh <worktree_path>
#
# Reads tool input JSON from stdin.  Exits 0 (allow) or 2 (block).
#
set -euo pipefail

WORKTREE_PATH="${1:?Usage: constrain_to_worktree.sh <worktree_path>}"
WORKTREE_REAL="$(cd "$WORKTREE_PATH" 2>/dev/null && pwd -P)" || exit 0

# Read JSON from stdin
INPUT=$(cat)

# Extract file_path from common tool input shapes
# Handles: {"file_path": "..."}, {"path": "..."}, {"command": "..."}
FILE_PATH=$(echo "$INPUT" | python3 -c "
import json, sys
data = json.load(sys.stdin)
# Check common path fields
for key in ('file_path', 'path', 'source_path', 'dest_path'):
    val = data.get(key, '')
    if val:
        print(val)
        sys.exit(0)
# For Bash tool, we can't reliably parse commands — allow
if 'command' in data:
    sys.exit(0)
" 2>/dev/null) || exit 0

# If no path found, allow (non-file tool invocation)
[ -z "$FILE_PATH" ] && exit 0

# Resolve the path relative to the worktree
if [[ "$FILE_PATH" = /* ]]; then
    RESOLVED="$(cd "$(dirname "$FILE_PATH")" 2>/dev/null && pwd -P)/$(basename "$FILE_PATH")" || exit 0
else
    RESOLVED="$(cd "$WORKTREE_REAL" 2>/dev/null && pwd -P)/$FILE_PATH"
fi

# Check if resolved path is under the worktree
case "$RESOLVED" in
    "$WORKTREE_REAL"/*)
        exit 0  # Allow
        ;;
    "$WORKTREE_REAL")
        exit 0  # Allow (exact match)
        ;;
    *)
        echo "BLOCKED: Path '$FILE_PATH' is outside the worktree '$WORKTREE_PATH'" >&2
        exit 2  # Block
        ;;
esac
