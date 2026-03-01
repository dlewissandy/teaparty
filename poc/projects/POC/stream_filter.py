#!/usr/bin/env python3
"""Stream filter for claude -p --output-format stream-json.

Shows inter-agent communication only:
  - Task dispatch (lead delegates to subagent)
  - SendMessage (direct messages between teammates)
  - Bash relay.sh calls (cross-process dispatch to subteams)
  - Errors

Format: [sender] @recipient: message body
Indentation for subteams is handled externally via --filter-prefix.
"""
import json
import re
import sys

# ── ANSI Colors (match chrome.sh) ──
C_RESET = "\033[0m"
C_DIM = "\033[2m"
C_CYAN = "\033[36m"
C_RED = "\033[31m"

# Map parent_tool_use_id -> agent name
task_agents = {}
# session_id of the lead agent (from init event)
lead_session_id = None


def agent_label(ev):
    """Extract a readable agent label from an event."""
    global lead_session_id
    parent = ev.get("parent_tool_use_id")
    if parent and parent in task_agents:
        return task_agents[parent]
    sid = ev.get("session_id", "")
    if sid and sid == lead_session_id:
        return "lead"
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
    label = agent_label(ev)

    # System events — capture lead session_id from init
    if t == "system":
        if sub == "init":
            if lead_session_id is None:
                lead_session_id = ev.get("session_id", "")
            agent_list = ev.get("agents", [])
            if agent_list:
                print(
                    f"{C_DIM}[init] agents: {', '.join(agent_list)}{C_RESET}",
                    flush=True,
                )
        continue

    # Assistant messages — only SendMessage and relay calls
    if t == "assistant":
        content = ev.get("message", {}).get("content", [])
        for block in content:
            if not isinstance(block, dict):
                continue
            bt = block.get("type", "")

            if bt == "tool_use":
                tool_name = block.get("name", "")
                tool_input = block.get("input", {})
                tool_id = block.get("id", "")

                if tool_name == "Task":
                    agent_type = tool_input.get("subagent_type", "")
                    name = tool_input.get("name", "")
                    desc = tool_input.get("description", "")
                    prompt = tool_input.get("prompt", "")
                    if tool_id:
                        task_agents[tool_id] = name or agent_type or desc
                    recipient = name or agent_type or "subagent"
                    # Show description (short) then first line of prompt
                    body = desc or ""
                    if prompt:
                        first_line = prompt.strip().split("\n")[0][:200]
                        body = f"{body} — {first_line}" if body else first_line
                    print(
                        f"{C_CYAN}[{label}]{C_RESET} @{recipient}: {body}",
                        flush=True,
                    )

                elif tool_name == "SendMessage":
                    msg_type = tool_input.get("type", "message")
                    recipient = tool_input.get("recipient", "")
                    content_text = tool_input.get("content", "")
                    if msg_type == "broadcast":
                        print(
                            f"{C_CYAN}[{label}]{C_RESET} @all: {content_text}",
                            flush=True,
                        )
                    elif msg_type == "shutdown_request":
                        print(
                            f"{C_CYAN}[{label}]{C_RESET} @{recipient}: shutdown",
                            flush=True,
                        )
                    elif msg_type == "shutdown_response":
                        approve = tool_input.get("approve", False)
                        status = "approved" if approve else "rejected"
                        print(
                            f"{C_CYAN}[{label}]{C_RESET} shutdown {status}",
                            flush=True,
                        )
                    else:
                        print(
                            f"{C_CYAN}[{label}]{C_RESET} @{recipient}: {content_text}",
                            flush=True,
                        )

                elif tool_name == "Bash":
                    cmd = tool_input.get("command", "")
                    if "relay.sh" in cmd:
                        # Extract --team and --task from the command
                        team_match = re.search(r"--team\s+(\S+)", cmd)
                        task_match = re.search(r'--task\s+"([^"]*)"', cmd)
                        if not task_match:
                            task_match = re.search(
                                r"--task\s+'([^']*)'", cmd
                            )
                        team = team_match.group(1) if team_match else "?"
                        task = task_match.group(1) if task_match else cmd[:200]
                        print(
                            f"{C_CYAN}[{label}]{C_RESET} @{team}-team: {task}",
                            flush=True,
                        )

        continue

    # Tool results — only show errors
    if t == "tool_result":
        if ev.get("is_error", False):
            tool = ev.get("tool", "")
            output = ev.get("output", "")[:200]
            print(
                f"  {C_RED}[error]{C_RESET} {tool}: {output}",
                flush=True,
            )
        continue

    # Final result
    if t == "result":
        result = ev.get("result", "")[:500]
        print(f"\n{C_DIM}── done ──{C_RESET}\n{result}", flush=True)
        continue
