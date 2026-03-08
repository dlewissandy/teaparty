#!/usr/bin/env bash
# Helper: run relay.sh with task text read from a file
# Usage: run-relay.sh <team> <task-file>
set -euo pipefail
TEAM="$1"
TASK_FILE="$2"
TASK=$(cat "$TASK_FILE")
/Users/darrell/git/teaparty/poc/projects/POC/relay.sh --team "$TEAM" --task "$TASK"
