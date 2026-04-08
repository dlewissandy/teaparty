#!/usr/bin/env bash
# teardown-worktrees.sh — Remove worktrees created by setup-worktrees.sh.
#
# Usage:
#   ./bin/teardown-worktrees.sh <feature-prefix> [--delete-branches]
#
# Options:
#   --delete-branches   Also delete the local branches after removing worktrees

set -euo pipefail

PREFIX="${1:-}"
DELETE_BRANCHES=false

if [[ -z "$PREFIX" ]]; then
  echo "Usage: $0 <feature-prefix> [--delete-branches]"
  exit 1
fi

if [[ "${2:-}" == "--delete-branches" ]]; then
  DELETE_BRANCHES=true
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
PARENT_DIR="$(dirname "$REPO_ROOT")"

ROLES=("backend" "frontend" "tests" "docs" "ux")

echo "Removing worktrees for prefix: $PREFIX"
echo ""

for ROLE in "${ROLES[@]}"; do
  WORKTREE_DIR="$PARENT_DIR/teaparty-${ROLE}-${PREFIX}"
  BRANCH_NAME="${ROLE}/${PREFIX}"

  if [[ -d "$WORKTREE_DIR" ]]; then
    echo "  REMOVE  $WORKTREE_DIR"
    git worktree remove "$WORKTREE_DIR"
  else
    echo "  SKIP    $WORKTREE_DIR (not found)"
  fi

  if $DELETE_BRANCHES; then
    if git rev-parse --verify "$BRANCH_NAME" &>/dev/null; then
      echo "  DELETE  branch $BRANCH_NAME"
      git branch -d "$BRANCH_NAME" 2>/dev/null || \
        echo "  WARN    branch $BRANCH_NAME has unmerged changes, use -D to force"
    fi
  fi
done

git worktree prune
echo ""
echo "Done."
