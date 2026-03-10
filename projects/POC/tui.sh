#!/usr/bin/env bash
# TeaParty POC TUI Dashboard
# Usage: ./projects/POC/tui.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$REPO_ROOT"
exec uv run python3 -m projects.POC.tui "$@"
