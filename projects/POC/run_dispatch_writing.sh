#!/usr/bin/env bash
set -euo pipefail
TASK="$(cat /Users/darrell/git/teaparty/projects/poc/.worktrees/session-0fe8c6f5--there-is-a-document-in-projects-poc-poc/projects/poc/writing-task.txt)"
/Users/darrell/git/teaparty/projects/POC/dispatch.sh --team writing --auto-approve-plan --task "$TASK"
