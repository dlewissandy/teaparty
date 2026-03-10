"""FIFO-based input request/response protocol for TUI ↔ session IPC.

When POC_TUI_MODE=1, the orchestration scripts (ui.sh) write an input
request to .input-request.json and block reading from .input-response.fifo.
The TUI polls for request files, shows the input widget, and writes the
user's response to the FIFO to unblock the session.
"""
from __future__ import annotations

import json
import os


REQUEST_FILE = '.input-request.json'
RESPONSE_FIFO = '.input-response.fifo'


def check_input_request(infra_dir: str) -> dict | None:
    """Check if a session is waiting for user input.

    Returns the parsed request dict, or None if no request is pending.
    """
    path = os.path.join(infra_dir, REQUEST_FILE)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return None


def send_response(infra_dir: str, response: str) -> bool:
    """Write user response to the FIFO, unblocking the waiting session.

    Returns True on success, False if the FIFO doesn't exist or write fails.
    """
    fifo_path = os.path.join(infra_dir, RESPONSE_FIFO)

    # Ensure the FIFO exists
    if not os.path.exists(fifo_path):
        try:
            os.mkfifo(fifo_path)
        except OSError:
            return False

    try:
        # Open in non-blocking write mode with a timeout
        # The session process should be blocked reading the FIFO,
        # so the write should complete immediately
        fd = os.open(fifo_path, os.O_WRONLY | os.O_NONBLOCK)
        os.write(fd, (response + '\n').encode())
        os.close(fd)
    except OSError:
        # FIFO not ready (session not reading yet) — fall back to blocking write
        try:
            with open(fifo_path, 'w') as f:
                f.write(response + '\n')
        except OSError:
            return False

    # Clean up the request file
    request_path = os.path.join(infra_dir, REQUEST_FILE)
    try:
        os.unlink(request_path)
    except FileNotFoundError:
        pass

    return True


def create_fifo(infra_dir: str) -> str:
    """Create the response FIFO if it doesn't exist. Returns the path."""
    fifo_path = os.path.join(infra_dir, RESPONSE_FIFO)
    if not os.path.exists(fifo_path):
        os.mkfifo(fifo_path)
    return fifo_path
