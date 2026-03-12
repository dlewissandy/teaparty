#!/usr/bin/env bash
# TeaParty TUI
# Usage: ./teaparty.sh [--project-dir DIR]
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
exec uv run python3 -m projects.POC.tui "$@"
