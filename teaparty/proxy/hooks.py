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


def _read_prompt_text(infra_dir: str) -> str:
    """Return the contents of {infra_dir}/PROMPT.txt or '' (#432)."""
    if not infra_dir:
        return ''
    path = os.path.join(infra_dir, 'PROMPT.txt')
    if not os.path.isfile(path):
        return ''
    with open(path, encoding='utf-8') as fh:
        return fh.read().strip()


def _read_project_description(teaparty_home: str) -> str:
    """Return the project description from {teaparty_home}/project/project.yaml or '' (#432)."""
    if not teaparty_home:
        return ''
    path = os.path.join(teaparty_home, 'project', 'project.yaml')
    if not os.path.isfile(path):
        return ''
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            stripped = line.strip()
            if stripped.startswith('description:'):
                return stripped.split(':', 1)[1].strip().strip('"\'')
    return ''


def _build_conversation_text(session: AgentSession, latest_turn: str = '') -> str:
    """Compose conversation history text for an AgentSession (#432).

    Returns '' if `session` doesn't expose `get_messages` (e.g. a SessionState
    dataclass).  Callers that have only `infra_dir` should compute conversation
    text another way and pass it directly to `_embed_context`.
    """
    lines: list[str] = []
    if hasattr(session, 'get_messages'):
        for msg in session.get_messages():
            sender = getattr(msg, 'sender', '') or ''
            content = getattr(msg, 'content', '') or ''
            if content:
                lines.append(f'{sender}: {content}')
    if latest_turn:
        lines.append(f'human: {latest_turn}')
    return '\n'.join(lines)


def _embed_context(
    conn, *, conversation_text: str = '', job_text: str = '', project_text: str = '',
) -> dict[str, list[float]]:
    """Embed the three context texts into a `context_embeddings` dict (#432).

    A dimension is included only when its source text is non-empty AND the
    embedding call returns a vector.  Missing dimensions contribute nothing
    to cosine; chunks fall back to activation alone.
    """
    from teaparty.proxy.memory import _default_embed
    embed = _default_embed(conn)
    ctx: dict[str, list[float]] = {}
    for name, text in (
        ('conversation', conversation_text),
        ('job', job_text),
        ('project', project_text),
    ):
        if not text:
            continue
        vec = embed(text)
        if vec:
            ctx[name] = vec
    return ctx


def _context_embeddings_for(
    session: AgentSession, conn, latest_turn: str = '',
) -> dict[str, list[float]]:
    """Build the three-dim query embedding dict for an AgentSession (#432)."""
    return _embed_context(
        conn,
        conversation_text=_build_conversation_text(session, latest_turn=latest_turn),
        job_text=_read_prompt_text(getattr(session, 'infra_dir', '') or ''),
        project_text=_read_project_description(getattr(session, 'teaparty_home', '') or ''),
    )


def record_escalation_chunk(
    *,
    question: str,
    answer: str,
    teaparty_home: str,
    infra_dir: str = '',
    qualifier: str = '',
) -> None:
    """Record an AskQuestion → answer interaction as a memory chunk (#432).

    Fires after the proxy returns from an escalation.  The conversation text
    is the question + answer pair — the §7 [ask] / [respond] cycle the
    spec describes.  Without this, the proxy's "memory of the human" never
    grows from the routine interaction the protocol is built around.
    """
    if not question or not answer:
        return
    from teaparty.proxy.memory import (
        MemoryChunk, open_proxy_db, store_chunk, increment_interaction_counter,
    )
    import uuid as _uuid
    mem_path = proxy_memory_path(teaparty_home)
    parent = os.path.dirname(mem_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = open_proxy_db(mem_path)
    try:
        conversation_text = f'Question: {question}\nAnswer: {answer}'
        ctx = _embed_context(
            conn,
            conversation_text=conversation_text,
            job_text=_read_prompt_text(infra_dir),
            project_text=_read_project_description(teaparty_home),
        )
        current = increment_interaction_counter(conn)
        chunk = MemoryChunk(
            id=_uuid.uuid4().hex,
            type='escalation',
            state='',
            task_type=qualifier,
            outcome='answered',
            content=conversation_text,
            traces=[current],
            embedding_conversation=ctx.get('conversation'),
            embedding_job=ctx.get('job'),
            embedding_project=ctx.get('project'),
        )
        store_chunk(conn, chunk)
    finally:
        conn.close()


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
        ctx = _context_embeddings_for(session, conn, latest_turn=response_text)
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
                embedding_conversation=ctx.get('conversation'),
                embedding_job=ctx.get('job'),
                embedding_project=ctx.get('project'),
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
        retrieve_chunks,
    )
    from teaparty.teams.stream import NON_CONVERSATIONAL_SENDERS

    mem_path = proxy_memory_path(session.teaparty_home)

    # Build memory context
    if os.path.exists(mem_path):
        conn = open_proxy_db(mem_path)
        try:
            current = get_interaction_counter(conn)
            ctx = _context_embeddings_for(session, conn, latest_turn=latest_human)
            chunks = retrieve_chunks(
                conn, current_interaction=current, top_k=10,
                context_embeddings=ctx,
            )
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
        # Fresh: include conversation history.  Escalation conversations
        # may have a seed message from the requesting agent (e.g. the
        # office manager's question) that is neither human nor proxy —
        # label those with the agent name so Claude reads it as a third
        # party, not as the proxy's own prior turn.
        messages = session.get_messages()
        lines = []
        for msg in messages:
            if msg.sender in NON_CONVERSATIONAL_SENDERS or msg.sender.startswith('unknown:'):
                continue
            if msg.sender == 'human':
                role = 'Human'
            elif msg.sender == 'proxy':
                role = 'Proxy'
            else:
                role = msg.sender
            lines.append(f'{role}: {msg.content}')
        dialog = '\n'.join(lines)
        return f'{memory_context}\n\n{dialog}'
