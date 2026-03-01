#!/usr/bin/env python3
"""Stream filter for the intent-gathering conversation.

Hybrid filter: shows agent text output (the conversation) AND inter-agent
communication (SendMessage, relay.sh dispatches). Designed for direct human
interaction during intent gathering.

Unlike stream_filter.py (which suppresses text blocks and shows only
inter-agent communication), this filter shows both — because the agent's
text IS the conversation the human is having.
"""
import argparse
import json
import re
import sys

# ── ANSI Colors (match chrome.sh) ──
C_RESET = "\033[0m"
C_DIM = "\033[2m"
C_CYAN = "\033[36m"
C_RED = "\033[31m"

# ── CLI args ──
parser = argparse.ArgumentParser()
parser.add_argument("--agent-name", default="intent-lead")
args = parser.parse_args()
AGENT_NAME = args.agent_name

# Track the lead's session_id for labeling
lead_session_id = None


def agent_label(ev):
    """Extract readable agent label from an event."""
    global lead_session_id
    sid = ev.get("session_id", "")
    if sid and sid == lead_session_id:
        return AGENT_NAME
    parent = ev.get("parent_tool_use_id")
    if parent:
        return "research-liaison"
    return sid[:8] if sid else "agent"


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        ev = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        continue

    t = ev.get("type", "")
    sub = ev.get("subtype", "")

    # Capture lead session_id from init
    if t == "system":
        if sub == "init" and lead_session_id is None:
            lead_session_id = ev.get("session_id", "")
        continue

    # Assistant messages — show text blocks AND team communication
    if t == "assistant":
        content = ev.get("message", {}).get("content", [])
        for block in content:
            if not isinstance(block, dict):
                continue
            bt = block.get("type", "")

            # Show text blocks (the conversation) with agent name prefix
            if bt == "text":
                text = block.get("text", "").strip()
                if text:
                    print(f"{C_CYAN}[{AGENT_NAME}]:{C_RESET} {text}", flush=True)
                    print("", flush=True)

            # Show tool use — team communication and key actions
            elif bt == "tool_use":
                name = block.get("name", "")
                inp = block.get("input", {})
                label = agent_label(ev)

                if name == "SendMessage":
                    msg_type = inp.get("type", "message")
                    recipient = inp.get("recipient", "")
                    content_text = inp.get("content", "")
                    summary = inp.get("summary", "")
                    display = summary or content_text[:120]
                    if msg_type == "broadcast":
                        print(
                            f"  {C_DIM}[{label} -> all: {display}]{C_RESET}",
                            flush=True,
                        )
                    elif msg_type in ("shutdown_request", "shutdown_response"):
                        print(
                            f"  {C_DIM}[{label}: shutdown {msg_type.split('_')[1]}]{C_RESET}",
                            flush=True,
                        )
                    else:
                        print(
                            f"  {C_DIM}[{label} -> {recipient}: {display}]{C_RESET}",
                            flush=True,
                        )

                elif name == "Bash":
                    cmd = inp.get("command", "")
                    if "relay.sh" in cmd:
                        team_match = re.search(r"--team\s+(\S+)", cmd)
                        task_match = re.search(r'--task\s+"([^"]*)"', cmd)
                        if not task_match:
                            task_match = re.search(r"--task\s+'([^']*)'", cmd)
                        team = team_match.group(1) if team_match else "?"
                        task = task_match.group(1) if task_match else cmd[:120]
                        print(
                            f"  {C_DIM}[{label} -> {team}-team: {task}]{C_RESET}",
                            flush=True,
                        )

                elif name == "Write":
                    fp = inp.get("file_path", "?")
                    print(f"  {C_DIM}[writing {fp}]{C_RESET}", flush=True)

                elif name == "WebSearch":
                    query = inp.get("query", "")
                    print(f"  {C_DIM}[searching: {query}]{C_RESET}", flush=True)

                elif name == "WebFetch":
                    url = inp.get("url", "")
                    print(f"  {C_DIM}[reading: {url}]{C_RESET}", flush=True)

                # Suppress Glob, Grep, Read, Edit, TodoWrite — noise
        continue

    # Tool results — only show errors
    if t == "tool_result":
        if ev.get("is_error", False):
            tool = ev.get("tool", "")
            output = ev.get("output", "")[:200]
            print(f"  {C_RED}[error]{C_RESET} {tool}: {output}", flush=True)
        continue

    # Final result — suppress (the loop in intent.sh handles turn boundaries)
    if t == "result":
        continue
