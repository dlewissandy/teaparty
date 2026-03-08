#!/usr/bin/env python3
"""Display filter for stream-json output.

Default mode -- shows inter-agent communication only:
  - Task dispatch (lead delegates to subagent)
  - SendMessage (direct messages between teammates)
  - Bash dispatch.sh calls (cross-process dispatch to subteams)
  - Errors

With --show-progress -- also shows agent activity:
  - Thinking excerpts (abbreviated)
  - Tool use events (Write, Edit, Bash, WebSearch, WebFetch, Read)

Format: [sender] @recipient: message body
Indentation for subteams is handled externally via --filter-prefix.
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stream._common import (
    C_RESET, C_DIM, C_CYAN, C_RED,
    agent_label, register_lead_session, register_task_agent,
    parse_events, shorten_worktree_path, parse_dispatch_command,
)

# ── CLI args ──
parser = argparse.ArgumentParser()
parser.add_argument("--show-progress", action="store_true",
                    help="Show thinking excerpts and tool use events")
args = parser.parse_args()
show_progress = args.show_progress

THINK_MAX = 120

# Previous todo state for differential display: {content: status}
prev_todos = {}


for ev in parse_events():
    t = ev.get("type", "")
    sub = ev.get("subtype", "")
    label = agent_label(ev)

    # System events -- capture lead session_id from init
    if t == "system":
        if sub == "init":
            register_lead_session(ev)
            agent_list = ev.get("agents", [])
            if agent_list:
                print(
                    f"{C_DIM}[init] agents: {', '.join(agent_list)}{C_RESET}",
                    flush=True,
                )
        continue

    # Assistant messages
    if t == "assistant":
        content = ev.get("message", {}).get("content", [])
        for block in content:
            if not isinstance(block, dict):
                continue
            bt = block.get("type", "")

            # ── Thinking blocks (--show-progress only) ──
            if bt == "thinking" and show_progress:
                thinking = block.get("thinking", "").strip()
                if thinking:
                    excerpt = thinking[:THINK_MAX].replace("\n", " ")
                    if len(thinking) > THINK_MAX:
                        excerpt += "..."
                    print(
                        f"  {C_DIM}\u2BF7 {excerpt}{C_RESET}",
                        flush=True,
                    )

            # ── Tool use ──
            elif bt == "tool_use":
                tool_name = block.get("name", "")
                tool_input = block.get("input", {})
                tool_id = block.get("id", "")

                # Always shown: Task dispatch
                if tool_name == "Task":
                    register_task_agent(tool_id, tool_input)
                    agent_type = tool_input.get("subagent_type", "")
                    name = tool_input.get("name", "")
                    desc = tool_input.get("description", "")
                    prompt = tool_input.get("prompt", "")
                    recipient = name or agent_type or "subagent"
                    body = desc or ""
                    if prompt:
                        first_line = prompt.strip().split("\n")[0][:200]
                        body = f"{body} \u2014 {first_line}" if body else first_line
                    print(
                        f"{C_CYAN}[{label}]{C_RESET} @{recipient}: {body}",
                        flush=True,
                    )

                # Always shown: SendMessage
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

                # Always shown: Bash dispatch.sh calls
                elif tool_name == "Bash":
                    cmd = tool_input.get("command", "")
                    if "dispatch.sh" in cmd or "relay.sh" in cmd:
                        team, task = parse_dispatch_command(cmd)
                        print(
                            f"{C_CYAN}[{label}]{C_RESET} @{team}-team: {task}",
                            flush=True,
                        )
                    elif show_progress:
                        desc = tool_input.get("description", "")
                        short = desc or cmd.split("\n")[0][:120]
                        print(
                            f"  {C_DIM}\u2192 Bash: {short}{C_RESET}",
                            flush=True,
                        )

                # --show-progress: TodoWrite checklist
                elif tool_name == "TodoWrite" and show_progress:
                    todos = tool_input.get("todos", [])
                    for item in todos:
                        item_content = item.get("content", "")
                        item_status = item.get("status", "")
                        active = item.get("activeForm", "")
                        old_status = prev_todos.get(item_content)

                        if item_status == "in_progress" and old_status != "in_progress":
                            display = active or item_content
                            print(
                                f"  {C_CYAN}\u25b6{C_RESET} {display}",
                                flush=True,
                            )
                        elif item_status == "completed" and old_status != "completed":
                            print(
                                f"  {C_DIM}\u2713 {item_content}{C_RESET}",
                                flush=True,
                            )

                    prev_todos.clear()
                    for item in todos:
                        prev_todos[item.get("content", "")] = item.get("status", "")

                # --show-progress: tool use events
                elif show_progress:
                    if tool_name == "Write":
                        path = tool_input.get("file_path", "")
                        short = shorten_worktree_path(path)
                        print(f"  {C_DIM}\u2192 Write {short}{C_RESET}", flush=True)
                    elif tool_name == "Edit":
                        path = tool_input.get("file_path", "")
                        short = shorten_worktree_path(path)
                        print(f"  {C_DIM}\u2192 Edit {short}{C_RESET}", flush=True)
                    elif tool_name == "WebSearch":
                        query = tool_input.get("query", "")[:120]
                        print(f'  {C_DIM}\u2192 WebSearch "{query}"{C_RESET}', flush=True)
                    elif tool_name == "WebFetch":
                        url = tool_input.get("url", "")[:120]
                        print(f"  {C_DIM}\u2192 WebFetch {url}{C_RESET}", flush=True)
                    elif tool_name == "Read":
                        path = tool_input.get("file_path", "")
                        short = shorten_worktree_path(path)
                        print(f"  {C_DIM}\u2192 Read {short}{C_RESET}", flush=True)

        continue

    # Tool results -- only show errors
    if t == "tool_result":
        if ev.get("is_error", False):
            tool = ev.get("tool", "")
            output = ev.get("output", "")[:200]
            print(f"  {C_RED}[error]{C_RESET} {tool}: {output}", flush=True)
        continue

    # Final result
    if t == "result":
        result = ev.get("result", "")[:500]
        print(f"\n{C_DIM}\u2500\u2500 done \u2500\u2500{C_RESET}\n{result}", flush=True)
        continue
