#!/usr/bin/env python3
"""Run dispatch.sh with task from coding_task_tui_fix.txt"""
import subprocess
import sys
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
task_file = os.path.join(script_dir, 'coding_task_tui_fix.txt')
dispatch_sh = '/Users/darrell/git/teaparty/projects/POC/dispatch.sh'

with open(task_file) as f:
    task = f.read().strip()

result = subprocess.run(
    [dispatch_sh, '--team', 'coding', '--auto-approve-plan', '--task', task],
    capture_output=False,
    text=True,
)
sys.exit(result.returncode)
