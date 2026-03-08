#!/usr/bin/env bash
TASK=$(cat /tmp/coding_task_clean.txt)
exec /Users/darrell/git/teaparty/poc/projects/POC/relay.sh --team coding --task "$TASK"
