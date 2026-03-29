"""Input request/response protocol for TUI ↔ session IPC.

Two transport mechanisms:

  1. Message bus (Issue #200): SQLite-backed message bus at {infra_dir}/messages.db.
     The orchestrator sends questions via the bus and polls for human responses.
     The TUI writes responses via send_message_bus_response().

  2. FIFO (legacy): .input-request.json + .input-response.fifo for shell-launched
     sessions that predate the Python orchestrator.

The message bus is the primary path for sessions launched via the Python
orchestrator.  FIFO is retained as a fallback for legacy compatibility.
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


def check_fifo_has_reader(infra_dir: str) -> bool:
    """Test whether a live reader is blocking on the response FIFO.

    Opens the FIFO in non-blocking write mode: succeeds only if another
    process already has the read end open (i.e. the session is alive).
    Returns True if a reader is present, False if the FIFO doesn't exist
    or no reader is present (ENXIO).
    """
    import errno
    fifo_path = os.path.join(infra_dir, RESPONSE_FIFO)
    if not os.path.exists(fifo_path):
        return False
    try:
        fd = os.open(fifo_path, os.O_WRONLY | os.O_NONBLOCK)
        os.close(fd)
        return True
    except OSError as e:
        if e.errno == errno.ENXIO:
            return False
        return False


def create_fifo(infra_dir: str) -> str:
    """Create the response FIFO if it doesn't exist. Returns the path."""
    fifo_path = os.path.join(infra_dir, RESPONSE_FIFO)
    if not os.path.exists(fifo_path):
        os.mkfifo(fifo_path)
    return fifo_path


# ── Message bus transport (Issue #200) ──────────────────────────────────────


def check_message_bus_request(
    bus_path: str, conversation_id: str,
) -> dict | None:
    """Check if the orchestrator is waiting for input via the message bus.

    Uses the structural awaiting_input flag set by MessageBusInputProvider
    (issue #288).  Returns a dict with 'bridge_text' (the most recent
    orchestrator message), or None if no input is pending.
    """
    if not os.path.exists(bus_path):
        return None
    try:
        from projects.POC.orchestrator.messaging import SqliteMessageBus
        bus = SqliteMessageBus(bus_path)
        try:
            conv = bus.get_conversation(conversation_id)
            if conv is None or not conv.awaiting_input:
                return None
            # Return the most recent orchestrator message as the pending question
            messages = bus.receive(conversation_id)
            for msg in reversed(messages):
                if msg.sender == 'orchestrator':
                    return {'bridge_text': msg.content}
            return None
        finally:
            bus.close()
    except Exception:
        return None


def send_message_bus_response(
    bus_path: str, conversation_id: str, response: str,
) -> bool:
    """Send a human response to the message bus.

    The orchestrator's MessageBusInputProvider polls for 'human' messages
    and will pick this up.

    Returns True on success, False on failure.
    """
    try:
        from projects.POC.orchestrator.messaging import SqliteMessageBus
        bus = SqliteMessageBus(bus_path)
        try:
            bus.send(conversation_id, 'human', response)
            return True
        finally:
            bus.close()
    except Exception:
        return False
