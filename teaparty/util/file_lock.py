#!/usr/bin/env python3
"""File-level advisory locking for concurrent session safety.

Dual-purpose: importable as a Python module, callable as a CLI tool for shell
scripts (replaces `flock` which is not available on macOS).

Python usage::

    from file_lock import locked_open, locked_append, locked_read_json, locked_write_json

    # Shared (read) lock
    with locked_open(path, 'r') as f:
        data = f.read()

    # Exclusive lock for append
    locked_append(path, "new content\\n")

    # Atomic JSON read/write under lock
    data = locked_read_json(path, default={})
    locked_write_json(path, {"key": "value"})

    # Read-modify-write under single exclusive lock
    with locked_open(path, 'rw') as f:
        data = json.load(f)
        data['key'] = 'new'
        f.seek(0); f.truncate()
        json.dump(data, f)

Shell usage (macOS-compatible flock replacement)::

    python3 -m teaparty.util.file_lock --lock /path/to/file -- command args...
    python3 -m teaparty.util.file_lock --lock /path/to/file --shared -- cat /path/to/file
"""
import argparse
import contextlib
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time

LOCK_TIMEOUT = 30  # seconds
LOCK_SUFFIX = '.lock'


def _acquire_lock(lock_fd, mode, timeout):
    """Acquire flock with timeout via polling."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(lock_fd.fileno(), mode | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Could not acquire lock within {timeout}s"
                )
            time.sleep(0.05)


@contextlib.contextmanager
def locked_open(path, mode='r', timeout=LOCK_TIMEOUT):
    """Open a file with advisory flock-based locking.

    Modes:
        'r'  — shared lock (LOCK_SH), read-only
        'a'  — exclusive lock (LOCK_EX), append
        'w'  — exclusive lock (LOCK_EX), write (truncate)
        'rw' — exclusive lock (LOCK_EX), read+write (for read-modify-write)

    The lock is held on an adjacent file (path + '.lock') for the duration
    of the context manager. This avoids issues with locking files that get
    replaced via atomic rename.
    """
    lock_path = path + LOCK_SUFFIX
    lock_mode = fcntl.LOCK_SH if mode == 'r' else fcntl.LOCK_EX

    os.makedirs(os.path.dirname(os.path.abspath(lock_path)), exist_ok=True)
    lock_fd = open(lock_path, 'w')

    _acquire_lock(lock_fd, lock_mode, timeout)
    try:
        file_mode = {'r': 'r', 'a': 'a', 'w': 'w', 'rw': 'r+'}[mode]
        # For 'rw', create the file if it doesn't exist
        if mode == 'rw' and not os.path.exists(path):
            open(path, 'w').close()
        f = open(path, file_mode)
        try:
            yield f
        finally:
            f.close()
    finally:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()


def locked_append(path, text, timeout=LOCK_TIMEOUT):
    """Append text to a file under exclusive lock."""
    with locked_open(path, 'a', timeout) as f:
        f.write(text)


def locked_read_json(path, default=None, timeout=LOCK_TIMEOUT):
    """Read a JSON file under shared lock. Returns *default* if missing or unparseable."""
    if not os.path.isfile(path):
        return default
    try:
        with locked_open(path, 'r', timeout) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def locked_write_json(path, data, timeout=LOCK_TIMEOUT):
    """Write a JSON file under exclusive lock with atomic tempfile + os.replace."""
    lock_path = path + LOCK_SUFFIX
    os.makedirs(os.path.dirname(os.path.abspath(lock_path)), exist_ok=True)
    lock_fd = open(lock_path, 'w')

    _acquire_lock(lock_fd, fcntl.LOCK_EX, timeout)
    try:
        out_dir = os.path.dirname(os.path.abspath(path))
        fd, tmp = tempfile.mkstemp(dir=out_dir, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    finally:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()


# ── CLI interface (shell-compatible flock replacement) ───────────────────────

def _cli_main():
    parser = argparse.ArgumentParser(
        description="File lock wrapper (macOS-compatible flock replacement)"
    )
    parser.add_argument('--lock', required=True, help='File to lock on')
    parser.add_argument('--shared', action='store_true', help='Shared (read) lock instead of exclusive')
    parser.add_argument('--timeout', type=int, default=LOCK_TIMEOUT)
    parser.add_argument('command', nargs=argparse.REMAINDER, help='Command to run under lock')
    args = parser.parse_args()

    cmd = args.command
    if cmd and cmd[0] == '--':
        cmd = cmd[1:]
    if not cmd:
        print("No command specified", file=sys.stderr)
        sys.exit(1)

    lock_path = args.lock + LOCK_SUFFIX
    lock_mode = fcntl.LOCK_SH if args.shared else fcntl.LOCK_EX

    os.makedirs(os.path.dirname(os.path.abspath(lock_path)), exist_ok=True)
    lock_fd = open(lock_path, 'w')

    _acquire_lock(lock_fd, lock_mode, args.timeout)
    try:
        result = subprocess.run(cmd)
        sys.exit(result.returncode)
    finally:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == '__main__':
    _cli_main()
