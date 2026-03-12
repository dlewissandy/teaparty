#!/usr/bin/env bash
set -euo pipefail
TASK="$(cat /Users/darrell/git/teaparty/projects/POC/.worktrees/session-c17e5596--this-is-a-continuation-of-session-202603/projects/POC/coding_task_tui_fix.txt)"
/Users/darrell/git/teaparty/projects/POC/dispatch.sh --team coding --task "$TASK"
