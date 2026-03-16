"""Python orchestrator for TeaParty POC sessions.

CfA state, human input, and stream events are in-process concepts —
no filesystem IPC, no races.  All LLM calls go through the Claude CLI.
"""
