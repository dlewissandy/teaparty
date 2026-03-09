#!/usr/bin/env bash
set -euo pipefail
TASK="$(cat /Users/darrell/git/teaparty/projects/POC/.worktrees/session-20260308-203749-amg0/projects/POC/coding_task.txt)"
/Users/darrell/git/teaparty/projects/POC/dispatch.sh --team coding --task "$TASK"
