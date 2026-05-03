"""TeaParty: a research platform for durable, scalable agent coordination.

Top-level package. Domain sub-packages:
  cfa        — Conversation for Action protocol engine
  proxy      — Human proxy system
  learning   — Hierarchical memory and learning
  bridge     — HTML dashboard and bridge server
  mcp        — MCP server for config and messaging
  runners    — LLM execution backends
  messaging  — Event bus, conversations, routing, IPC
  teams      — Multi-turn team coordination sessions
  workspace  — Git worktree and job lifecycle
  config     — Runtime config loading
  scheduling — Cron execution
  scripts    — LLM-powered utility scripts
  util       — Shared utilities
"""
import os


def find_poc_root() -> str:
    """Walk up from this package to find the repo root.

    The sentinel is ``pyproject.toml`` at the top of the source tree —
    a stable, language-neutral marker.  Previously this walked for
    ``cfa/statemachine/cfa-state-machine.json`` (deleted with the
    state-machine simplification).
    """
    d = os.path.dirname(os.path.abspath(__file__))
    while d != '/':
        if os.path.exists(os.path.join(d, 'pyproject.toml')):
            return d
        d = os.path.dirname(d)
    return os.path.dirname(os.path.abspath(__file__))
