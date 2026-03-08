#!/usr/bin/env python3
"""Dispatch a phase task to the coding team via relay.sh."""
import subprocess
import sys
import os

RELAY = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "poc/projects/POC/relay.sh"
)

def dispatch(task_file: str) -> int:
    with open(task_file) as f:
        task = f.read()
    result = subprocess.run(
        [RELAY, "--team", "coding", "--task", task],
        env={**os.environ},
    )
    return result.returncode

if __name__ == "__main__":
    sys.exit(dispatch(sys.argv[1]))
