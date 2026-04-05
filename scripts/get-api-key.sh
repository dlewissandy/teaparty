#!/bin/sh
# Extract the Claude OAuth access token from the macOS keychain.
# Used as apiKeyHelper for --bare mode dispatched agents.
security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null \
  | python3 -c "import sys,json; print(json.loads(sys.stdin.read())['claudeAiOauth']['accessToken'])"
