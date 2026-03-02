#!/usr/bin/env bash
# smart-merge.sh — Robust squash-merge with progressive conflict resolution
#
# Replaces the fragile inline merge logic in run.sh and relay.sh.
# Handles: untracked file conflicts, modified file conflicts, content conflicts.
# Falls back to file-by-file checkout when merge mechanics fail entirely.
#
# Usage:
#   smart-merge.sh --target-dir <dir> --branch <branch> [--label <label>]
#
# Exit codes:
#   0 — merge succeeded (changes staged, ready for caller to commit)
#   1 — merge failed after all recovery attempts
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/chrome.sh"

TARGET_DIR=""
BRANCH=""
LABEL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target-dir) TARGET_DIR="$2"; shift 2 ;;
    --branch)     BRANCH="$2"; shift 2 ;;
    --label)      LABEL="$2"; shift 2 ;;
    *)            echo "smart-merge: unknown arg: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$TARGET_DIR" ]] && { echo "smart-merge: --target-dir required" >&2; exit 1; }
[[ -z "$BRANCH" ]]     && { echo "smart-merge: --branch required" >&2; exit 1; }
[[ -z "$LABEL" ]]      && LABEL="$BRANCH"

log() { echo -e "  ${C_DIM}[merge]${C_RESET} $*" >&2; }

# ── Attempt 1: straight squash-merge ──
log "Merging $LABEL..."

if git -C "$TARGET_DIR" merge --squash "$BRANCH" 2>/dev/null; then
  log "${C_GREEN}Merge succeeded${C_RESET}"
  exit 0
fi

# Capture stderr for diagnostics
MERGE_ERR=$(git -C "$TARGET_DIR" merge --squash "$BRANCH" 2>&1 || true)

# ── Recovery: remove untracked files that block the merge ──
# Git refuses to merge when untracked files in the target would be overwritten.
# These are almost always stale copies from a previous dispatch that wrote to the
# wrong worktree. Back them up and retry.
UNTRACKED_FILES=()
IN_UNTRACKED=false
while IFS= read -r line; do
  if [[ "$line" == *"untracked working tree files would be overwritten"* ]]; then
    IN_UNTRACKED=true
    continue
  fi
  if $IN_UNTRACKED; then
    [[ "$line" == "Please"* || "$line" == "Aborting"* || -z "$line" ]] && break
    local_trimmed=$(echo "$line" | xargs)
    [[ -n "$local_trimmed" ]] && UNTRACKED_FILES+=("$local_trimmed")
  fi
done <<< "$MERGE_ERR"

if [[ ${#UNTRACKED_FILES[@]} -gt 0 ]]; then
  BACKUP_DIR="$TARGET_DIR/.merge-backup-$(date +%s)"
  log "Backing up ${#UNTRACKED_FILES[@]} untracked files blocking merge"
  mkdir -p "$BACKUP_DIR"
  for f in "${UNTRACKED_FILES[@]}"; do
    src="$TARGET_DIR/$f"
    if [[ -f "$src" ]]; then
      mkdir -p "$(dirname "$BACKUP_DIR/$f")"
      mv "$src" "$BACKUP_DIR/$f"
    fi
  done
fi

# ── Recovery: handle modified tracked files ──
if [[ "$MERGE_ERR" == *"Your local changes to the following files would be overwritten"* ]]; then
  log "Resetting modified tracked files blocking merge"
  git -C "$TARGET_DIR" checkout -- . 2>/dev/null || true
fi

# ── Attempt 2: retry after clearing blockers ──
git -C "$TARGET_DIR" reset HEAD 2>/dev/null || true

if git -C "$TARGET_DIR" merge --squash "$BRANCH" 2>/dev/null; then
  log "${C_GREEN}Merge succeeded after clearing blockers${C_RESET}"
  exit 0
fi

# ── Attempt 3: -X theirs for content conflicts ──
log "${C_YELLOW}Retrying with -X theirs...${C_RESET}"
git -C "$TARGET_DIR" reset HEAD 2>/dev/null || true

if git -C "$TARGET_DIR" merge --squash -X theirs "$BRANCH" 2>/dev/null; then
  log "${C_GREEN}Merge succeeded with -X theirs${C_RESET}"
  exit 0
fi

# ── Attempt 4: file-by-file checkout from branch ──
# When git merge mechanics fail entirely (e.g., complex rename + untracked combos),
# bypass merge and apply the branch's changes file by file.
log "${C_YELLOW}Merge mechanics failed — applying changes file-by-file${C_RESET}"
git -C "$TARGET_DIR" reset HEAD 2>/dev/null || true

# Get all files that differ between HEAD and the branch
CHANGED=$(git -C "$TARGET_DIR" diff --name-only HEAD..."$BRANCH" 2>/dev/null || true)

if [[ -z "$CHANGED" ]]; then
  log "No file differences found between HEAD and $BRANCH"
  exit 0
fi

APPLIED=0
FAILED=0
while IFS= read -r file; do
  [[ -z "$file" ]] && continue

  # Check if the file exists on the branch (it might be a deletion)
  if git -C "$TARGET_DIR" cat-file -e "$BRANCH:$file" 2>/dev/null; then
    # File exists on branch — check it out
    mkdir -p "$(dirname "$TARGET_DIR/$file")"
    if git -C "$TARGET_DIR" checkout "$BRANCH" -- "$file" 2>/dev/null; then
      ((APPLIED++))
    else
      log "  ${C_RED}failed: $file${C_RESET}"
      ((FAILED++))
    fi
  else
    # File was deleted on the branch
    rm -f "$TARGET_DIR/$file"
    git -C "$TARGET_DIR" rm --cached "$file" 2>/dev/null || true
    ((APPLIED++))
  fi
done <<< "$CHANGED"

if [[ $APPLIED -gt 0 ]]; then
  git -C "$TARGET_DIR" add -A 2>/dev/null || true
  log "${C_GREEN}Applied $APPLIED files from $LABEL${C_RESET}"
  [[ $FAILED -gt 0 ]] && log "${C_YELLOW}$FAILED files failed — check backup${C_RESET}"
  exit 0
fi

# ── All attempts exhausted ──
log "${C_RED}All merge strategies failed — deliverables remain on $BRANCH${C_RESET}"
exit 1
