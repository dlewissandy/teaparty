#!/usr/bin/env bash
set -euo pipefail
TASK_FILE="$(dirname "$0")/.relay_task.txt"
TASK="$(cat "$TASK_FILE")"
exec /Users/darrell/git/teaparty/poc/projects/POC/relay.sh --team coding --task "$TASK"
