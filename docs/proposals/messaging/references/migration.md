# FIFO IPC Migration

## Current State

The current IPC (`ipc.py`) uses:
- `.input-request.json` — orchestrator writes what it needs
- `.input-response.fifo` — TUI writes the human's answer, orchestrator blocks reading

## Migration Path

1. Orchestrator writes a message to the conversation instead of `.input-request.json`
2. TUI shows it in the chat instead of as a modal input widget
3. Human responds in the chat instead of the input widget
4. Orchestrator reads from the conversation instead of the FIFO

The semantics are identical. The mechanism changes from blocking FIFO to polled message bus. The FIFO IPC can be removed once the migration is complete.
