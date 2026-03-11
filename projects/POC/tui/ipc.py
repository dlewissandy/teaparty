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

    The shell side (ui.sh _tui_prompt) creates the FIFO and blocks reading it.
    We write the response to unblock the shell, then clean up the request file.

    Returns True on success, False if the FIFO doesn't exist or write fails.
    """
    fifo_path = os.path.join(infra_dir, RESPONSE_FIFO)

    if not os.path.exists(fifo_path):
        return False

    try:
        # The session process should be blocked reading the FIFO,
        # so opening for write should succeed immediately
        with open(fifo_path, 'w') as f:
            f.write(response + '\n')
    except OSError:
        return False

    # Clean up the request file (shell also cleans up, but be safe)
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
