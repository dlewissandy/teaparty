"""Stall detection for agent processes.

The watchdog monitors stream file modification times and kills
agent processes that produce no output for too long.  Integrated
into ClaudeRunner rather than running as a separate background
process (as the shell scripts did).
"""
from __future__ import annotations

import os
import time


def stream_is_stale(stream_file: str, timeout_seconds: int) -> bool:
    """Check if a stream file's last modification exceeds the timeout."""
    try:
        mtime = os.path.getmtime(stream_file)
        return (time.time() - mtime) >= timeout_seconds
    except OSError:
        return False


def write_failure_reason(infra_dir: str, reason: str) -> None:
    """Write a .failure-reason sentinel for diagnostics."""
    path = os.path.join(infra_dir, '.failure-reason')
    with open(path, 'w') as f:
        f.write(reason)
