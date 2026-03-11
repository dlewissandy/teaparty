#!/usr/bin/env python3
import subprocess, sys

task = open('/Users/darrell/git/teaparty/projects/POC/.worktrees/session-2054f34a--there-is-a-bug-in-the-poc-code-sessions/projects/POC/.dispatch-task.txt').read()
result = subprocess.run(
    ['/Users/darrell/git/teaparty/projects/POC/dispatch.sh', '--team', 'coding', '--auto-approve-plan', '--task', task],
    capture_output=False, text=True, timeout=280
)
sys.exit(result.returncode)
