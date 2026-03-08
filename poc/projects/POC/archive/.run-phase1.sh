#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASK=$(cat "$SCRIPT_DIR/.phase1-task.txt")
exec "$SCRIPT_DIR/relay.sh" --team coding --task "$TASK"
