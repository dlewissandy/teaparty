#!/usr/bin/env bash
# Dispatch a phase task to the coding team via relay.sh
# Usage: dispatch.sh <phase-number> <task-file>
set -euo pipefail

RELAY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/poc/projects/POC/relay.sh"
TASK_FILE="$1"
TASK=$(cat "$TASK_FILE")
"$RELAY" --team coding --task "$TASK"
