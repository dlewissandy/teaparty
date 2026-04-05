#!/bin/sh
# Extract Claude Max OAuth token for --bare mode dispatched agents.
# Max accounts only — no pay-per-token API keys.
# Must print the token to stdout and exit 0.

# 1. macOS keychain
if command -v security >/dev/null 2>&1; then
    token=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null \
        | python3 -c "import sys,json; print(json.loads(sys.stdin.read())['claudeAiOauth']['accessToken'])" 2>/dev/null)
    if [ -n "$token" ]; then
        echo "$token"
        exit 0
    fi
fi

# 2. Linux secret-tool (GNOME Keyring)
if command -v secret-tool >/dev/null 2>&1; then
    token=$(secret-tool lookup service "Claude Code-credentials" 2>/dev/null \
        | python3 -c "import sys,json; print(json.loads(sys.stdin.read())['claudeAiOauth']['accessToken'])" 2>/dev/null)
    if [ -n "$token" ]; then
        echo "$token"
        exit 0
    fi
fi

# 3. No credentials found
exit 1
