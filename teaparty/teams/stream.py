"""Stream parsing utilities for agent session events.

Shared by AgentSession and test code. Extracted from office_manager.py
as part of the unified agent launch (Issue #394).
"""
from __future__ import annotations

import json
import os


# Senders that carry internal stream trace — not conversational history.
NON_CONVERSATIONAL_SENDERS: frozenset[str] = frozenset({
    'thinking', 'tool_use', 'tool_result', 'system', 'orchestrator',
    'state', 'cost', 'log',
})


def _extract_slug(stream_path: str, session_id: str, cwd: str) -> str:
    """Extract the conversation slug Claude auto-generates for this session.

    Tries the stream JSONL first (any event with a 'slug' field), then falls
    back to Claude's history file (~/.claude/projects/{hash}/{session_id}.jsonl).
    Returns '' if not found.
    """
    try:
        with open(stream_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except (ValueError, json.JSONDecodeError):
                    continue
                slug = ev.get('slug', '')
                if slug:
                    return slug
    except OSError:
        pass

    if session_id and cwd:
        project_hash = cwd.replace('/', '-')
        history_path = os.path.join(
            os.path.expanduser('~'), '.claude', 'projects',
            project_hash, f'{session_id}.jsonl',
        )
        try:
            with open(history_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except (ValueError, json.JSONDecodeError):
                        continue
                    slug = ev.get('slug', '')
                    if slug:
                        return slug
        except OSError:
            pass

    return ''


def _classify_event(ev: dict, agent_role: str,
                    seen_tool_use: set[str],
                    seen_tool_result: set[str]):
    """Yield (sender, content) pairs for a single stream-json event dict.

    Maps stream event types to bus sender labels:
    - thinking block   -> ('thinking', text)
    - text block       -> (agent_role, text)
    - tool_use block   -> ('tool_use', JSON of name+input)
    - tool_result event -> ('tool_result', content text or JSON)
    - system event     -> ('system', JSON of event)
    - unknown block    -> ('unknown:<type>', JSON of block)

    Deduplicates tool_use and tool_result by their IDs.
    """
    ev_type = ev.get('type', '')

    if ev_type == 'assistant':
        for block in ev.get('message', {}).get('content', []):
            if not isinstance(block, dict):
                continue
            block_type = block.get('type', '')
            if block_type == 'thinking':
                text = block.get('thinking', '').strip()
                if text:
                    yield 'thinking', text
            elif block_type == 'text':
                text = block.get('text', '').strip()
                if text:
                    yield agent_role, text
            elif block_type == 'tool_use':
                tid = block.get('id', '')
                if tid and tid not in seen_tool_use:
                    seen_tool_use.add(tid)
                    yield 'tool_use', json.dumps({
                        'name': block.get('name', ''),
                        'input': block.get('input', {}),
                    })
            else:
                yield f'unknown:{block_type}', json.dumps(block)

    elif ev_type == 'tool_use':
        tid = ev.get('tool_use_id', '')
        if not tid or tid not in seen_tool_use:
            if tid:
                seen_tool_use.add(tid)
            yield 'tool_use', json.dumps({
                'name': ev.get('name', ''),
                'input': ev.get('input', {}),
            })

    elif ev_type == 'tool_result':
        tid = ev.get('tool_use_id', '')
        if not tid or tid not in seen_tool_result:
            if tid:
                seen_tool_result.add(tid)
            raw = ev.get('content', '')
            yield 'tool_result', raw if isinstance(raw, str) else json.dumps(raw)

    elif ev_type == 'user':
        content = ev.get('message', {}).get('content', [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'tool_result':
                    tid = block.get('tool_use_id', '')
                    if not tid or tid not in seen_tool_result:
                        if tid:
                            seen_tool_result.add(tid)
                        raw = block.get('content', '')
                        yield 'tool_result', raw if isinstance(raw, str) else json.dumps(raw)

    elif ev_type == 'system':
        yield 'system', json.dumps(ev)

    elif ev_type == 'result':
        stats = {k: ev[k] for k in (
            'total_cost_usd', 'duration_ms', 'input_tokens', 'output_tokens'
        ) if k in ev}
        if stats:
            yield 'cost', json.dumps(stats)


def _make_live_stream_relay(bus, conv_id: str, agent_role: str):
    """Return (callback, events) for real-time streaming to the message bus.

    The callback processes a single stream-json event dict: writes each
    (sender, content) pair to the bus immediately and appends it to the
    events list for post-processing.

    Returns:
        callback: Synchronous callable(event_dict) -- pass as on_stream_event.
        events:   List of (sender, content) tuples accumulated during the run.
    """
    seen_tool_use: set[str] = set()
    seen_tool_result: set[str] = set()
    events: list[tuple[str, str]] = []

    def callback(event: dict) -> None:
        for sender, content in _classify_event(
            event, agent_role, seen_tool_use, seen_tool_result,
        ):
            bus.send(conv_id, sender, content)
            events.append((sender, content))

    return callback, events
