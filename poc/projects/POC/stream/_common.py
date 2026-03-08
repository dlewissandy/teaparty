"""Shared utilities for stream-json processors.

All processors in this package parse Claude's --output-format stream-json
(JSONL) and share agent labeling, event parsing, and ANSI color constants.
"""
import json
import re
import sys

# ── ANSI Colors ──
C_RESET = "\033[0m"
C_DIM = "\033[2m"
C_CYAN = "\033[36m"
C_RED = "\033[31m"

# ── Shared state ──
# Map parent_tool_use_id -> agent name (populated by Task tool_use events)
task_agents = {}
# session_id of the lead agent (from init event)
lead_session_id = None


def agent_label(ev):
    """Extract a readable agent label from a stream event.

    Uses task_agents mapping first, then falls back to session_id matching.
    """
    global lead_session_id
    parent = ev.get("parent_tool_use_id")
    if parent and parent in task_agents:
        return task_agents[parent]
    sid = ev.get("session_id", "")
    if sid and sid == lead_session_id:
        return "lead"
    return sid[:8] if sid else "agent"


def register_lead_session(ev):
    """Capture the lead's session_id from a system/init event."""
    global lead_session_id
    if lead_session_id is None:
        lead_session_id = ev.get("session_id", "")


def register_task_agent(tool_id, tool_input):
    """Register a Task dispatch so future events can be labeled by agent name."""
    if tool_id:
        name = (tool_input.get("name", "")
                or tool_input.get("subagent_type", "")
                or tool_input.get("description", ""))
        task_agents[tool_id] = name


def parse_events(stream=None):
    """Yield parsed JSON events from a JSONL stream (defaults to stdin)."""
    source = stream or sys.stdin
    for line in source:
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue


def shorten_worktree_path(path):
    """Shorten .worktrees/session-*/... paths for readability."""
    return re.sub(r".*/\.worktrees/[^/]+/", ".../", path)


def parse_dispatch_command(cmd):
    """Extract --team and --task from a dispatch.sh command."""
    team_match = re.search(r"--team\s+(\S+)", cmd)
    task_match = re.search(r'--task\s+"([^"]*)"', cmd)
    if not task_match:
        task_match = re.search(r"--task\s+'([^']*)'", cmd)
    team = team_match.group(1) if team_match else "?"
    task = task_match.group(1) if task_match else cmd[:200]
    return team, task
