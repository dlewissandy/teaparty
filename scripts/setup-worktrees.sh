#!/usr/bin/env bash
# setup-worktrees.sh — Create git worktrees for parallel agent sessions.
#
# Creates one worktree per agent role, each on its own branch, in a sibling
# directory. Run separate Claude Code sessions in each worktree for true
# isolation (separate files, separate branch, no clobbering).
#
# Usage:
#   ./scripts/setup-worktrees.sh [feature-prefix]
#
# Example:
#   ./scripts/setup-worktrees.sh add-auth
#
# Creates:
#   ../teaparty-backend-add-auth/    (branch: backend/add-auth)
#   ../teaparty-frontend-add-auth/   (branch: frontend/add-auth)
#   ../teaparty-tests-add-auth/      (branch: tests/add-auth)
#   ../teaparty-docs-add-auth/       (branch: docs/add-auth)
#   ../teaparty-ux-add-auth/         (branch: ux/add-auth)
#
# Teardown:
#   ./scripts/teardown-worktrees.sh [feature-prefix]

set -euo pipefail

PREFIX="${1:-}"

if [[ -z "$PREFIX" ]]; then
  echo "Usage: $0 <feature-prefix>"
  echo ""
  echo "Example: $0 add-auth"
  echo ""
  echo "This creates worktrees for each agent role:"
  echo "  ../teaparty-backend-<prefix>/   (branch: backend/<prefix>)"
  echo "  ../teaparty-frontend-<prefix>/  (branch: frontend/<prefix>)"
  echo "  ../teaparty-tests-<prefix>/     (branch: tests/<prefix>)"
  echo "  ../teaparty-docs-<prefix>/      (branch: docs/<prefix>)"
  echo "  ../teaparty-ux-<prefix>/        (branch: ux/<prefix>)"
  exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
PARENT_DIR="$(dirname "$REPO_ROOT")"
BASE_BRANCH="$(git rev-parse --abbrev-ref HEAD)"

# Agent roles that do implementation work (read-only agents don't need worktrees)
ROLES=("backend" "frontend" "tests" "docs" "ux")

echo "Creating worktrees from branch: $BASE_BRANCH"
echo "Parent directory: $PARENT_DIR"
echo ""

for ROLE in "${ROLES[@]}"; do
  WORKTREE_DIR="$PARENT_DIR/teaparty-${ROLE}-${PREFIX}"
  BRANCH_NAME="${ROLE}/${PREFIX}"

  if [[ -d "$WORKTREE_DIR" ]]; then
    echo "  SKIP  $WORKTREE_DIR (already exists)"
    continue
  fi

  echo "  CREATE  $WORKTREE_DIR  →  branch: $BRANCH_NAME"
  git worktree add -b "$BRANCH_NAME" "$WORKTREE_DIR" "$BASE_BRANCH"
done

echo ""
echo "Done. To start working:"
echo ""
for ROLE in "${ROLES[@]}"; do
  echo "  cd $PARENT_DIR/teaparty-${ROLE}-${PREFIX} && claude"
done
echo ""
echo "When finished, merge branches and clean up with:"
echo "  ./scripts/teardown-worktrees.sh $PREFIX"
