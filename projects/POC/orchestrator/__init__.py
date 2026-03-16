"""Python orchestrator for TeaParty POC sessions.

CfA state, human input, and stream events are in-process concepts —
no filesystem IPC, no races.  All LLM calls go through the Claude CLI.
"""
import os


def find_poc_root() -> str:
    """Walk up from this package to find the POC root (contains cfa-state-machine.json)."""
    d = os.path.dirname(os.path.abspath(__file__))
    while d != '/':
        if os.path.exists(os.path.join(d, 'cfa-state-machine.json')):
            return d
        d = os.path.dirname(d)
    return os.path.dirname(os.path.abspath(__file__))
