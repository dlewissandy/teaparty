#!/usr/bin/env python3
"""Stream filter for claude -p --output-format stream-json.

Reads stream-json lines from stdin and prints human-readable progress.
Handles extended thinking, tool_use content blocks, task dispatch,
and plan-phase markers.
"""
import json
import sys

# Track which agents we've seen (map session_id -> agent label)
agents = {}
task_agents = {}  # tool_use_id -> agent_type/description


def agent_label(ev):
    """Extract a readable agent label from an event."""
    # Check for agent_name first (some events have it)
    name = ev.get("agent_name", "")
    if name:
        return name
    # Fall back to parent_tool_use_id to identify subagents
    parent = ev.get("parent_tool_use_id")
    if parent and parent in task_agents:
        return task_agents[parent]
    # Fall back to session_id (truncated)
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

    # System events
    if t == "system":
        if sub == "init":
            agent_list = ev.get("agents", [])
            if agent_list:
                print(f"[init] agents: {', '.join(agent_list)}", flush=True)
        elif sub == "task_started":
            tid = ev.get("task_id", "")
            desc = ev.get("description", "")
            tool_id = ev.get("tool_use_id", "")
            if tool_id:
                task_agents[tool_id] = desc
            print(f"[{label}] >> task started: {desc}", flush=True)
        elif sub == "task_completed":
            desc = ev.get("description", "")
            print(f"[{label}] << task done: {desc}", flush=True)
        continue

    # Assistant messages — content blocks can be thinking, text, or tool_use
    if t == "assistant":
        content = ev.get("message", {}).get("content", [])
        for block in content:
            if not isinstance(block, dict):
                continue
            bt = block.get("type", "")
            if bt == "text":
                text = block.get("text", "")[:200]
                if text:
                    print(f"[{label}] {text}", flush=True)
            elif bt == "tool_use":
                tool_name = block.get("name", "")
                tool_input = block.get("input", {})
                if tool_name == "Task":
                    desc = tool_input.get("description", "")
                    agent_type = tool_input.get("subagent_type", "")
                    prompt = tool_input.get("prompt", "")
                    # Detect plan-only dispatch
                    phase_tag = ""
                    if "[PLAN ONLY]" in prompt or "[PLAN ONLY]" in desc:
                        phase_tag = " [PLAN]"
                    print(
                        f"[{label}] -> Task({agent_type}){phase_tag}: {desc}",
                        flush=True,
                    )
                    # Map tool_use_id -> description for subagent tracking
                    tool_id = block.get("id", "")
                    if tool_id:
                        task_agents[tool_id] = agent_type
                elif tool_name == "Bash":
                    cmd = tool_input.get("command", "")[:120]
                    # Detect plan-only relay calls
                    if "--plan-only" in cmd:
                        print(
                            f"[{label}] -> Bash [PLAN]: {cmd}", flush=True
                        )
                    else:
                        print(f"[{label}] -> Bash: {cmd}", flush=True)
                elif tool_name == "Write":
                    path = tool_input.get("file_path", "")
                    # Highlight plan file writes
                    if "plan.md" in path:
                        print(
                            f"[{label}] -> Write [PLAN]: {path}", flush=True
                        )
                    else:
                        print(f"[{label}] -> Write: {path}", flush=True)
                else:
                    print(f"[{label}] -> {tool_name}", flush=True)
            # Skip thinking blocks silently
        continue

    # Tool results
    if t == "tool_result":
        tool = ev.get("tool", "")
        # Only show errors
        is_error = ev.get("is_error", False)
        if is_error:
            output = ev.get("output", "")[:200]
            print(f"[{label}] !! {tool} error: {output}", flush=True)
        continue

    # Final result
    if t == "result":
        result = ev.get("result", "")[:500]
        print(f"\n=== PHASE RESULT ===\n{result}", flush=True)
        continue
