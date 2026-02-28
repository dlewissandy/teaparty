#!/usr/bin/env bash
# Minimal test to debug --settings permissions for Bash allowlist
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1

# Create a trivial script to test
cat > /tmp/poc-test-tool.sh << 'EOF'
#!/bin/bash
echo "Tool called successfully with args: $@"
EOF
chmod +x /tmp/poc-test-tool.sh

# Test each settings format
echo "=== Test 1: --settings with permissions.allow ==="
SETTINGS1=$(mktemp)
cat > "$SETTINGS1" << EOF
{"permissions": {"allow": ["Bash(/tmp/poc-test-tool.sh *)"]}}
EOF
echo "Settings: $(cat "$SETTINGS1")"
echo "Run the command: /tmp/poc-test-tool.sh hello" | claude -p \
  --output-format text \
  --max-turns 3 \
  --permission-mode acceptEdits \
  --settings "$SETTINGS1" \
  2>&1 | head -20
echo ""

echo "=== Test 2: --settings with just allow at top level ==="
SETTINGS2=$(mktemp)
cat > "$SETTINGS2" << EOF
{"allow": ["Bash(/tmp/poc-test-tool.sh *)"]}
EOF
echo "Settings: $(cat "$SETTINGS2")"
echo "Run the command: /tmp/poc-test-tool.sh hello" | claude -p \
  --output-format text \
  --max-turns 3 \
  --permission-mode acceptEdits \
  --settings "$SETTINGS2" \
  2>&1 | head -20
echo ""

echo "=== Test 3: --allowedTools directly ==="
echo "Run the command: /tmp/poc-test-tool.sh hello" | claude -p \
  --output-format text \
  --max-turns 3 \
  --permission-mode acceptEdits \
  --allowedTools 'Bash(/tmp/poc-test-tool.sh *)' \
  2>&1 | head -20
echo ""

echo "=== Test 4: --allowedTools with just Bash ==="
echo "Run the command: /tmp/poc-test-tool.sh hello" | claude -p \
  --output-format text \
  --max-turns 3 \
  --permission-mode acceptEdits \
  --allowedTools 'Bash' \
  2>&1 | head -20
echo ""

# Cleanup
rm -f "$SETTINGS1" "$SETTINGS2" /tmp/poc-test-tool.sh
echo "=== Done ==="
