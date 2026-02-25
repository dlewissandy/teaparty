#!/usr/bin/env python3
"""Stream filter for claude -p --output-format stream-json.

Shows agent conversations and output. Suppresses internal machinery.

Visible:
  - SendMessage (the actual inter-agent conversation)
  - TeamCreate / TeamDelete (team lifecycle)
  - Write (file output)
  - Bash relay.sh calls (cross-process dispatch)
  - Agent text (reasoning shown to user)
  - Errors

Suppressed:
  - Task dispatch (internal subagent spawning)
  - Exploration tools (Bash ls/find/cd, Glob, Read, Grep, etc.)
  - System task_started/task_completed (internal bookkeeping)
  - Thinking blocks
"""
import json
import sys

# Map parent_tool_use_id -> agent label (subagent_type)
task_agents = {}


def agent_label(ev):
    """Extract a readable agent label from an event."""
    name = ev.get("agent_name", "")
    if name:
        return name
    parent = ev.get("parent_tool_use_id")
    if parent and parent in task_agents:
        return task_agents[parent]
    sid = ev.get("session_id", "")
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

    # System events — only show init
    if t == "system":
        if sub == "init":
            agent_list = ev.get("agents", [])
            if agent_list:
                print(f"[init] agents: {', '.join(agent_list)}", flush=True)
        # Track task agents silently for labeling
        elif sub == "task_started":
            tool_id = ev.get("tool_use_id", "")
            if tool_id and tool_id in task_agents:
                pass  # already tracked
        continue

    # Assistant messages
    if t == "assistant":
        content = ev.get("message", {}).get("content", [])
        for block in content:
            if not isinstance(block, dict):
                continue
            bt = block.get("type", "")

            if bt == "text":
                text = block.get("text", "")[:300]
                if text:
                    print(f"[{label}] {text}", flush=True)

            elif bt == "tool_use":
                tool_name = block.get("name", "")
                tool_input = block.get("input", {})
                tool_id = block.get("id", "")

                if tool_name == "Task":
                    # Track for labeling, but don't print
                    agent_type = tool_input.get("subagent_type", "")
                    desc = tool_input.get("description", "")
                    if tool_id:
                        task_agents[tool_id] = agent_type or desc

                elif tool_name == "TeamCreate":
                    team_name = tool_input.get("team_name", "")
                    desc = tool_input.get("description", "")
                    print(
                        f"[{label}] TeamCreate(\"{team_name}\"): {desc}",
                        flush=True,
                    )

                elif tool_name == "SendMessage":
                    msg_type = tool_input.get("type", "message")
                    recipient = tool_input.get("recipient", "")
                    summary = tool_input.get("summary", "")
                    content_text = tool_input.get("content", "")[:300]
                    if msg_type == "broadcast":
                        print(
                            f"[{label}] >> all: {summary or content_text}",
                            flush=True,
                        )
                    elif msg_type == "shutdown_request":
                        print(
                            f"[{label}] -> {recipient}: shutdown",
                            flush=True,
                        )
                    elif msg_type == "shutdown_response":
                        approve = tool_input.get("approve", False)
                        print(
                            f"[{label}] shutdown {'approved' if approve else 'rejected'}",
                            flush=True,
                        )
                    else:
                        print(
                            f"[{label}] -> {recipient}: {summary or content_text}",
                            flush=True,
                        )

                elif tool_name == "TeamDelete":
                    print(f"[{label}] TeamDelete", flush=True)

                elif tool_name == "Write":
                    path = tool_input.get("file_path", "")
                    print(f"[{label}] Write: {path}", flush=True)

                elif tool_name == "Bash":
                    cmd = tool_input.get("command", "")[:200]
                    if "relay.sh" in cmd:
                        print(f"[{label}] relay: {cmd}", flush=True)
                    # All other Bash is suppressed

                # Everything else (Glob, Read, Grep, etc.) suppressed
        continue

    # Tool results — only show errors
    if t == "tool_result":
        if ev.get("is_error", False):
            tool = ev.get("tool", "")
            output = ev.get("output", "")[:200]
            print(f"[{label}] !! {tool}: {output}", flush=True)
        continue

    # Final result
    if t == "result":
        result = ev.get("result", "")[:500]
        print(f"\n=== RESULT ===\n{result}", flush=True)
        continue
