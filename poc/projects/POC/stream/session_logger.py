#!/usr/bin/env python3
"""Session audit logger -- writes categorized entries to session.log.

Reads JSONL from stdin (same stream-json as display_filter.py) and writes
formatted log entries. Captures what agents say, think, dispatch, and do.

Categories:
  AGENT    -- text blocks (agent conversational output)
  THINK    -- thinking blocks (abbreviated)
  DISPATCH -- Task tool_use (agent delegates to subagent)
  MESSAGE  -- SendMessage tool_use (inter-agent messages)
  TOOL     -- notable tool use (WebSearch, Write, WebFetch, dispatch.sh)
  EXPLORE  -- read-only tools (Read, Glob, Grep)
  ERROR    -- tool_result errors
  RESULT   -- final result text
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stream._common import (
    agent_label, register_lead_session, register_task_agent,
    parse_events, shorten_worktree_path, parse_dispatch_command,
)

# ── Truncation limits ──
TEXT_MAX = 500
TEXT_MAX_LINES = 5
THINK_MAX = 120
DISPATCH_MAX = 200
MESSAGE_MAX = 300
TOOL_MAX = 200
ERROR_MAX = 200
RESULT_MAX = 300


def truncate(text, limit):
    """Truncate text, appending char count if truncated."""
    total = len(text)
    if total <= limit:
        return text
    return f"{text[:limit]}... ({total} chars)"


def format_entry(category, message, prefix=""):
    """Format a session log entry with continuation lines."""
    timestamp = time.strftime("%H:%M:%S")
    lines = message.split("\n")
    if len(lines) > TEXT_MAX_LINES:
        lines = lines[:TEXT_MAX_LINES]
    parts = [f"[{timestamp}] {category:<8s} | {prefix}{lines[0]}"]
    for continuation in lines[1:]:
        parts.append(f"           .        | {prefix}{continuation}")
    return "\n".join(parts) + "\n"


def write_entry(fd, category, message, prefix=""):
    """Write a single log entry atomically via os.write."""
    entry = format_entry(category, message, prefix)
    try:
        os.write(fd, entry.encode("utf-8", errors="replace"))
    except OSError:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-log", default=os.environ.get("SESSION_LOG", ""))
    parser.add_argument("--prefix", default="")
    args = parser.parse_args()

    log_path = args.session_log
    if not log_path:
        for _ in sys.stdin:
            pass
        return

    prefix = args.prefix

    try:
        fd = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    except OSError:
        for _ in sys.stdin:
            pass
        return

    for ev in parse_events():
        t = ev.get("type", "")
        sub = ev.get("subtype", "")
        label = agent_label(ev)

        # ── System events: capture lead session_id ──
        if t == "system":
            if sub == "init":
                register_lead_session(ev)
            continue

        # ── Assistant messages: text, thinking, tool_use ──
        if t == "assistant":
            content = ev.get("message", {}).get("content", [])
            for block in content:
                if not isinstance(block, dict):
                    continue
                bt = block.get("type", "")

                if bt == "text":
                    text = block.get("text", "").strip()
                    if not text:
                        continue
                    text = truncate(text, TEXT_MAX)
                    clean = re.sub(r"\n{3,}", "\n\n", text)
                    write_entry(fd, "AGENT", f"{label}: {clean}", prefix)

                elif bt == "thinking":
                    thinking = block.get("thinking", "").strip()
                    if not thinking:
                        continue
                    total = len(thinking)
                    excerpt = thinking[:THINK_MAX].replace("\n", " ")
                    if total > THINK_MAX:
                        excerpt = f"{excerpt}... ({total} chars)"
                    write_entry(fd, "THINK", f"{label}: {excerpt}", prefix)

                elif bt == "tool_use":
                    tool_name = block.get("name", "")
                    tool_input = block.get("input", {})
                    tool_id = block.get("id", "")

                    if tool_name == "Task":
                        register_task_agent(tool_id, tool_input)
                        agent_type = tool_input.get("subagent_type", "")
                        name = tool_input.get("name", "")
                        desc = tool_input.get("description", "")
                        prompt = tool_input.get("prompt", "")
                        recipient = name or agent_type or "subagent"
                        body = desc or ""
                        if prompt:
                            first_line = prompt.strip().split("\n")[0][:DISPATCH_MAX]
                            body = f"{body} -- {first_line}" if body else first_line
                        body = truncate(body, DISPATCH_MAX)
                        write_entry(fd, "DISPATCH", f"{label} -> {recipient}: {body}", prefix)

                    elif tool_name == "SendMessage":
                        msg_type = tool_input.get("type", "message")
                        recipient = tool_input.get("recipient", "")
                        content_text = tool_input.get("content", "")
                        content_text = truncate(content_text, MESSAGE_MAX)
                        if msg_type == "broadcast":
                            write_entry(fd, "MESSAGE", f"{label} -> all: {content_text}", prefix)
                        elif msg_type == "shutdown_request":
                            write_entry(fd, "MESSAGE", f"{label} -> {recipient}: shutdown request", prefix)
                        elif msg_type == "shutdown_response":
                            approve = tool_input.get("approve", False)
                            status = "approved" if approve else "rejected"
                            write_entry(fd, "MESSAGE", f"{label}: shutdown {status}", prefix)
                        else:
                            write_entry(fd, "MESSAGE", f"{label} -> {recipient}: {content_text}", prefix)

                    elif tool_name == "WebSearch":
                        query = tool_input.get("query", "")[:TOOL_MAX]
                        write_entry(fd, "TOOL", f'{label}: WebSearch "{query}"', prefix)

                    elif tool_name == "Write":
                        path = tool_input.get("file_path", "")[:TOOL_MAX]
                        write_entry(fd, "TOOL", f"{label}: Write {path}", prefix)

                    elif tool_name == "WebFetch":
                        url = tool_input.get("url", "")[:TOOL_MAX]
                        write_entry(fd, "TOOL", f"{label}: WebFetch {url}", prefix)

                    elif tool_name == "Bash":
                        cmd = tool_input.get("command", "")
                        if "dispatch.sh" in cmd or "relay.sh" in cmd:
                            team, task = parse_dispatch_command(cmd)
                            write_entry(fd, "TOOL", f"{label}: dispatch --team {team} -- {task[:TOOL_MAX]}", prefix)

                    elif tool_name == "Read":
                        path = tool_input.get("file_path", "")
                        short = shorten_worktree_path(path)
                        write_entry(fd, "EXPLORE", f"{label}: Read {short[:TOOL_MAX]}", prefix)

                    elif tool_name == "Glob":
                        pattern = tool_input.get("pattern", "")
                        path = tool_input.get("path", "")
                        loc = f" in {path}" if path else ""
                        write_entry(fd, "EXPLORE", f"{label}: Glob {pattern}{loc}"[:TOOL_MAX + 30], prefix)

                    elif tool_name == "Grep":
                        pattern = tool_input.get("pattern", "")[:80]
                        path = tool_input.get("path", "")
                        short = shorten_worktree_path(path) if path else ""
                        write_entry(fd, "EXPLORE", f'{label}: Grep "{pattern}" {short}'[:TOOL_MAX + 30], prefix)

                    elif tool_name == "ExitPlanMode":
                        write_entry(fd, "AGENT", f"{label}: ExitPlanMode -- plan ready for review", prefix)

                    elif tool_name == "Edit":
                        path = tool_input.get("file_path", "")
                        short = shorten_worktree_path(path)
                        write_entry(fd, "TOOL", f"{label}: Edit {short[:TOOL_MAX]}", prefix)

            continue

        # ── Tool result errors ──
        if t == "tool_result":
            if ev.get("is_error", False):
                tool = ev.get("tool", "")
                output = ev.get("output", "")[:ERROR_MAX]
                write_entry(fd, "ERROR", f"{tool}: {output}", prefix)
            continue

        # ── Final result ──
        if t == "result":
            result = ev.get("result", "") or ev.get("subResult", "")
            result = truncate(result, RESULT_MAX)
            result_clean = result.replace("\n", " ")
            write_entry(fd, "RESULT", result_clean, prefix)
            continue

    os.close(fd)


if __name__ == "__main__":
    main()
