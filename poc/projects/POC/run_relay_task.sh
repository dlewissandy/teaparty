#!/usr/bin/env bash
# Relay the proxy wiring task to the coding team.
# This script is a wrapper to avoid shell interpretation issues with the task text.
set -euo pipefail

TASK_FILE="/tmp/proxy_wire_task.txt"
POC_DIR="/Users/darrell/git/teaparty/poc/projects/POC"

if [[ ! -f "$TASK_FILE" ]]; then
  echo "ERROR: Task file not found: $TASK_FILE" >&2
  exit 1
fi

TASK=$(cat "$TASK_FILE")
exec "$POC_DIR/relay.sh" --team coding --task "$TASK"
