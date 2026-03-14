"""Python orchestrator for TeaParty POC sessions.

Replaces shell-based orchestration (run.sh, intent.sh, plan-execute.sh,
dispatch_cli.py, ui.sh) with native async Python.  CfA state, human input,
and stream events are in-process concepts — no filesystem IPC, no races.

All LLM calls go through the Claude CLI (flat-rate license key).
"""
