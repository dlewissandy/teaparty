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

# Run the bridge and every spawned agent against a teaparty-managed
# Claude Code config directory instead of the user's personal ~/.claude.
# This jails what slash commands and skills agents see — only entries we
# stage are visible; the user's personal commands/skills under ~/.claude
# are not consulted. The OAuth token lives in this dir too (created by
# `claude /login` against the same CLAUDE_CONFIG_DIR), so auth and
# isolation share the same location.
export CLAUDE_CONFIG_DIR="$REPO_ROOT/.teaparty/claude-home"

if [ ! -f "$CLAUDE_CONFIG_DIR/.claude.json" ]; then
    mkdir -p "$CLAUDE_CONFIG_DIR"
    cat <<EOF >&2
TeaParty's Claude Code config directory is empty:
  $CLAUDE_CONFIG_DIR

Log in to Claude Code against this directory once, then re-run ./teaparty.sh:

  CLAUDE_CONFIG_DIR="$CLAUDE_CONFIG_DIR" claude /login

The OAuth token is stored at that path. Subsequent agent subprocesses
spawned by the bridge inherit CLAUDE_CONFIG_DIR and use the same token.
EOF
    exit 1
fi

exec uv run python3 -m teaparty.bridge --teaparty-home "$REPO_ROOT/.teaparty" "$@"
