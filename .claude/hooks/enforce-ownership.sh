#!/usr/bin/env bash
# enforce-ownership.sh — Blocks Edit/Write calls outside an agent's allowed paths.
#
# Called as a PreToolUse hook. Reads tool input JSON from stdin.
# Environment:
#   CLAUDE_AGENT_NAME — set by Claude Code when running inside a subagent
#
# Exit codes:
#   0 — allow (path is within ownership boundaries, or agent name not recognized)
#   2 — block with feedback message to the agent

set -euo pipefail

# If not running as a named agent, allow everything
if [[ -z "${CLAUDE_AGENT_NAME:-}" ]]; then
  exit 0
fi

# Extract the file_path from the tool input JSON on stdin
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
# Edit tool uses 'file_path', Write tool uses 'file_path'
print(data.get('file_path', ''))
" 2>/dev/null || echo "")

# If we couldn't extract a file path, allow (might be a non-file tool)
if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

# Normalize to a path relative to the project root
PROJECT_ROOT="$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel 2>/dev/null || echo "")"
if [[ -n "$PROJECT_ROOT" ]]; then
  # Strip project root prefix to get relative path
  REL_PATH="${FILE_PATH#$PROJECT_ROOT/}"
else
  REL_PATH="$FILE_PATH"
fi

# Define ownership boundaries per agent
case "$CLAUDE_AGENT_NAME" in
  backend-engineer)
    ALLOWED="teaparty_app/"
    ;;
  frontend-engineer)
    ALLOWED="web/"
    ;;
  test-engineer)
    ALLOWED="tests/"
    ;;
  ux-designer)
    ALLOWED="web/"
    ;;
  graphic-artist)
    ALLOWED="web/"
    ;;
  doc-writer)
    # Allow docs/, README.md, ROADMAP.md, TASKLIST.md, TOOL_GAPS.md
    if [[ "$REL_PATH" == docs/* ]] || \
       [[ "$REL_PATH" == "README.md" ]] || \
       [[ "$REL_PATH" == "ROADMAP.md" ]] || \
       [[ "$REL_PATH" == "TASKLIST.md" ]] || \
       [[ "$REL_PATH" == "TOOL_GAPS.md" ]]; then
      exit 0
    fi
    echo "BLOCKED: doc-writer can only edit docs/, README.md, ROADMAP.md, TASKLIST.md, TOOL_GAPS.md. You tried to edit: $REL_PATH"
    exit 2
    ;;
  social-architect)
    # Owns docs/SocialArchitecture.md and docs/ for related analysis
    if [[ "$REL_PATH" == docs/* ]]; then
      exit 0
    fi
    echo "BLOCKED: social-architect can only edit files under docs/. You tried to edit: $REL_PATH"
    exit 2
    ;;
  cognitive-architect)
    # Owns docs/CognitiveArchitecture.md and docs/ for related analysis
    if [[ "$REL_PATH" == docs/* ]]; then
      exit 0
    fi
    echo "BLOCKED: cognitive-architect can only edit files under docs/. You tried to edit: $REL_PATH"
    exit 2
    ;;
  researcher)
    # Owns docs/research/ for the research library
    if [[ "$REL_PATH" == docs/research/* ]]; then
      exit 0
    fi
    echo "BLOCKED: researcher can only edit files under docs/research/. You tried to edit: $REL_PATH"
    exit 2
    ;;
  code-reviewer|architect)
    # These agents should have no Edit/Write tools, but block as a safety net
    echo "BLOCKED: $CLAUDE_AGENT_NAME is read-only and cannot edit files."
    exit 2
    ;;
  *)
    # Unknown agent — allow
    exit 0
    ;;
esac

# Check if the relative path starts with the allowed prefix
if [[ "$REL_PATH" == ${ALLOWED}* ]]; then
  exit 0
fi

echo "BLOCKED: $CLAUDE_AGENT_NAME can only edit files under ${ALLOWED}. You tried to edit: $REL_PATH"
exit 2
