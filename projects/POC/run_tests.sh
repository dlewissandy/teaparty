#!/usr/bin/env bash
# Quick test runner for all POC memory lifecycle tests
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_DIR="$SCRIPT_DIR/scripts/tests"
SCRIPTS_DIR="$SCRIPT_DIR/scripts"

echo "=== Running POC memory lifecycle tests ==="
echo "Test dir: $TEST_DIR"
echo ""

# Use unittest discover
python3 -m unittest discover \
    --start-directory "$TEST_DIR" \
    --pattern "test_*.py" \
    --verbose \
    2>&1

echo ""
echo "=== Test run complete ==="
