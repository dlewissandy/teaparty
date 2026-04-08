#!/usr/bin/env bash
# TeaParty HTML dashboard (bridge server)
# Usage: ./teaparty.sh [--port PORT]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

if ! command -v uv >/dev/null 2>&1; then
    echo "uv not found — installing via astral.sh..."
    curl -LsSf https://astral.sh/uv/install.sh | sh || true
    # Source the env so uv is available in this session
    if [ -f "$HOME/.local/bin/env" ]; then
        . "$HOME/.local/bin/env"
    else
        export PATH="$HOME/.local/bin:$PATH"
    fi
    if ! command -v uv >/dev/null 2>&1; then
        echo "Error: uv install failed — uv is still not on PATH." >&2
        echo "Install manually: https://docs.astral.sh/uv/getting-started/installation/" >&2
        exit 1
    fi
    echo "uv installed successfully."
fi

exec uv run python3 -m teaparty.bridge --teaparty-home "$REPO_ROOT/.teaparty" "$@"
