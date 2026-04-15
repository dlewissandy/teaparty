"""Proxy agent hooks for AgentSession — ACT-R memory processing.

These hooks plug into AgentSession's post_invoke_hook and build_prompt_hook
to give the proxy agent its distinguishing behavior: correction processing
and memory-context prompt building.

Issue #394.
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teaparty.teams.session import AgentSession

_log = logging.getLogger('teaparty.proxy.hooks')

CORRECTION_ACTIVATION_BOOST = 5


def proxy_home(teaparty_home: str) -> str:
    """Return the canonical proxy runtime directory.

    All proxy runtime state lives here: memory DB, confidence models,
    message bus, learnings.  The agent definition stays in
    management/agents/proxy/agent.md (config, not runtime).
    """
    return os.path.join(teaparty_home, 'proxy')


def proxy_memory_path(teaparty_home: str) -> str:
    """Return the canonical path to the proxy memory database."""
    return os.path.join(proxy_home(teaparty_home), '.proxy-memory.db')


def proxy_bus_path(teaparty_home: str) -> str:
    """Return the canonical path to the proxy message bus database."""
    return os.path.join(proxy_home(teaparty_home), 'proxy-messages.db')


def proxy_post_invoke(response_text: str, session: AgentSession) -> None:
    """Process [CORRECTION:...] and [REINFORCE:...] signals from proxy response.

    [CORRECTION: text] — stores a new high-activation chunk for new knowledge
    or corrections. Used when the human teaches the proxy something new.

    [REINFORCE: chunk_id] — adds a trace to an existing chunk, raising its
    ACT-R activation. Used when the human confirms a pattern the proxy already
    holds. chunk_id must be a real ID from the proxy's memory context.
    """
    from teaparty.proxy.memory import (
        MemoryChunk,
        add_trace,
        get_chunk,
        increment_interaction_counter,
        open_proxy_db,
        store_chunk,
    )

    corrections = re.findall(r'\[CORRECTION:\s*(.*?)\]', response_text, re.DOTALL)
    reinforcements = re.findall(r'\[REINFORCE:\s*(.*?)\]', response_text, re.DOTALL)
    if not corrections and not reinforcements:
        return

    mem_path = proxy_memory_path(session.teaparty_home)
    os.makedirs(os.path.dirname(mem_path), exist_ok=True)

    conn = open_proxy_db(mem_path)
    try:
        for correction_text in corrections:
            correction_text = correction_text.strip()
            if not correction_text:
                continue
            chunk_id = uuid.uuid4().hex
            current = increment_interaction_counter(conn)
            traces = [current] * CORRECTION_ACTIVATION_BOOST
            chunk = MemoryChunk(
                id=chunk_id,
                type='review_correction',
                state='',
                task_type=f'review:{session.qualifier}',
                outcome='correction',
                content=correction_text,
                traces=traces,
            )
            store_chunk(conn, chunk)
            _log.info('Recorded review correction %s', chunk_id[:8])

        for chunk_id in reinforcements:
            chunk_id = chunk_id.strip()
            if not chunk_id:
                continue
            if get_chunk(conn, chunk_id) is None:
                _log.warning('REINFORCE: chunk %s not found — skipping', chunk_id[:8])
                continue
            current = increment_interaction_counter(conn)
            add_trace(conn, chunk_id, current)
            _log.info('Reinforced chunk %s', chunk_id[:8])
    finally:
        conn.close()


def proxy_build_prompt(session: AgentSession, latest_human: str) -> str:
    """Build the proxy prompt with ACT-R memory context.

    Fresh session: full conversation history + memory + accuracy.
    Resumed session: fresh memory context + latest human message.
    """
    from teaparty.proxy.memory import (
        base_level_activation,
        get_interaction_counter,
        open_proxy_db,
        query_chunks,
    )
    from teaparty.teams.stream import NON_CONVERSATIONAL_SENDERS

    mem_path = proxy_memory_path(session.teaparty_home)

    # Build memory context
    if os.path.exists(mem_path):
        conn = open_proxy_db(mem_path)
        try:
            current = get_interaction_counter(conn)
            chunks = query_chunks(conn)
            entries = []
            for chunk in chunks:
                activation = base_level_activation(chunk.traces, current)
                entries.append(f'- [id:{chunk.id}] [{chunk.type}] {chunk.content} (activation={activation:.3f})')
            memory_context = '\n'.join(entries) if entries else 'No memories yet.'
        finally:
            conn.close()
    else:
        memory_context = 'No memories yet.'

    if session.claude_session_id:
        # Resumed: provide fresh memory context
        return f'{memory_context}\n\nHuman: {latest_human}'
    else:
        # Fresh: include conversation history
        messages = session.get_messages()
        lines = []
        for msg in messages:
            if msg.sender in NON_CONVERSATIONAL_SENDERS or msg.sender.startswith('unknown:'):
                continue
            role = 'Human' if msg.sender == 'human' else 'Proxy'
            lines.append(f'{role}: {msg.content}')
        dialog = '\n'.join(lines)
        return f'{memory_context}\n\n{dialog}'
