"""Proxy review session — interactive calibration of the proxy model.

The human talks directly to the proxy that models their decision-making,
inspecting what it has learned, correcting wrong patterns, reinforcing
important ones, and exploring areas of low confidence.

The proxy operates in self-review mode (full transparency into its ACT-R
memory) rather than gate-prediction mode.  Corrections are recorded as
high-activation memory chunks that immediately influence future gate
predictions.

Design: docs/proposals/proxy-review/proposal.md
Chat pattern: docs/proposals/chat-experience/proposal.md (Pattern 3)
Issue #259.
"""
from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import uuid
from dataclasses import dataclass
from typing import Any

from orchestrator.messaging import (
    ConversationType,
    SqliteMessageBus,
)
from orchestrator.proxy_memory import (
    MemoryChunk,
    add_trace,
    base_level_activation,
    get_interaction_counter,
    increment_interaction_counter,
    query_chunks,
    store_chunk,
)

_log = logging.getLogger('orchestrator.proxy_review')

# How many extra traces a correction gets on creation.  Each trace is
# placed at the current interaction counter, giving the correction a
# high initial activation so it surfaces in near-future retrievals.
# Moderate default — see proposal open question #1 on correction strength.
CORRECTION_ACTIVATION_BOOST = 5


# ── Data ────────────────────────────────────────────────────────────────────

@dataclass
class ReviewSession:
    """An active proxy review session."""
    conversation_id: str
    human_name: str
    memory_db_path: str


# ── Session lifecycle ───────────────────────────────────────────────────────

def open_review_session(
    bus: SqliteMessageBus,
    *,
    human_name: str,
    memory_db_path: str = '',
) -> ReviewSession:
    """Open (or resume) a proxy review session for a human.

    Creates a PROXY_REVIEW conversation on the message bus if one does
    not already exist.  Returns a ReviewSession handle for the caller.
    """
    conv = bus.create_conversation(ConversationType.PROXY_REVIEW, human_name)
    return ReviewSession(
        conversation_id=conv.id,
        human_name=human_name,
        memory_db_path=memory_db_path,
    )


# ── Memory introspection ───────────────────────────────────────────────────

def introspect_chunks(
    conn,
    *,
    current_interaction: int = 0,
    state: str = '',
    task_type: str = '',
) -> list[dict[str, Any]]:
    """Retrieve all memory chunks with computed activation levels.

    Returns a list of dicts, each containing:
      - chunk: the MemoryChunk
      - activation: float, base-level activation at current_interaction
      - age: int, interactions since most recent trace

    Sorted by activation descending (most active first).
    """
    chunks = query_chunks(conn, state=state, task_type=task_type)

    entries = []
    for chunk in chunks:
        activation = base_level_activation(chunk.traces, current_interaction)
        most_recent = max(chunk.traces) if chunk.traces else 0
        age = current_interaction - most_recent
        entries.append({
            'chunk': chunk,
            'activation': activation,
            'age': age,
        })

    entries.sort(key=lambda e: e['activation'], reverse=True)
    return entries


def format_introspection(entries: list[dict[str, Any]]) -> str:
    """Format introspection results as human-readable markdown.

    Shows each chunk's context, predictions, confidence, percepts,
    and activation level.
    """
    if not entries:
        return 'No memories to review.'

    lines = ['## Memory Introspection', '']
    for entry in entries:
        chunk = entry['chunk']
        activation = entry['activation']
        age = entry['age']

        lines.append(f'### Memory {chunk.id[:8]}')
        lines.append(f'**Type:** {chunk.type} | **State:** {chunk.state or "(global)"}'
                      f' | **Project:** {chunk.task_type or "(any)"}')
        lines.append(f'**Outcome:** {chunk.outcome}')
        lines.append(f'**Activation:** {activation:.3f} (age: {age} interactions)')

        if chunk.prior_prediction:
            lines.append(f'**Prior prediction:** {chunk.prior_prediction}'
                         f' (confidence {chunk.prior_confidence:.2f})')
        if chunk.posterior_prediction:
            lines.append(f'**Posterior prediction:** {chunk.posterior_prediction}'
                         f' (confidence {chunk.posterior_confidence:.2f})')
        if chunk.prediction_delta:
            lines.append(f'**Delta:** {chunk.prediction_delta}')
        if chunk.salient_percepts:
            lines.append(f'**Salient percepts:** {", ".join(chunk.salient_percepts)}')
        if chunk.human_response:
            lines.append(f'**Human said:** {chunk.human_response}')
        if chunk.content:
            lines.append(f'**Content:** {chunk.content}')
        lines.append('')

    return '\n'.join(lines)


# ── Corrections ─────────────────────────────────────────────────────────────

def record_correction(
    conn,
    *,
    correction: str,
    source: str,
) -> str:
    """Record a correction from a review session as a high-activation chunk.

    The correction is stored with:
      - type='review_correction' (state-agnostic, like steering chunks)
      - empty state (surfaces in all CfA gate contexts)
      - task_type=source for attribution
      - multiple initial traces for elevated activation

    Returns the chunk ID.
    """
    chunk_id = uuid.uuid4().hex
    current = increment_interaction_counter(conn)

    # Build traces: current interaction repeated CORRECTION_ACTIVATION_BOOST
    # times to give the correction high initial activation.
    traces = [current] * CORRECTION_ACTIVATION_BOOST

    chunk = MemoryChunk(
        id=chunk_id,
        type='review_correction',
        state='',
        task_type=source,
        outcome='correction',
        content=correction,
        traces=traces,
    )
    store_chunk(conn, chunk)
    _log.info('Recorded review correction %s from %s', chunk_id[:8], source)
    return chunk_id


# ── Reinforcement ───────────────────────────────────────────────────────────

def reinforce_chunk(conn, *, chunk_id: str) -> None:
    """Reinforce an existing chunk by adding a trace at the current interaction.

    Used when the human confirms a pattern during review ("yes, that's
    important").  Raises ValueError if the chunk does not exist.
    """
    from orchestrator.proxy_memory import get_chunk

    chunk = get_chunk(conn, chunk_id)
    if chunk is None:
        raise ValueError(f'Chunk {chunk_id} not found')

    current = increment_interaction_counter(conn)
    add_trace(conn, chunk_id, current)
    _log.info('Reinforced chunk %s at interaction %d', chunk_id[:8], current)


# ── Accuracy summary ────────────────────────────────────────────────────────

def summarize_accuracy(conn) -> str:
    """Summarize proxy prediction accuracy across all contexts.

    Returns a markdown-formatted summary of prior and posterior accuracy
    per (state, task_type) pair.
    """
    rows = conn.execute(
        'SELECT state, task_type, prior_correct, prior_total, '
        'posterior_correct, posterior_total, last_updated '
        'FROM proxy_accuracy ORDER BY state, task_type'
    ).fetchall()

    if not rows:
        return 'No prediction accuracy data yet.'

    lines = ['## Prediction Accuracy', '',
             '| State | Project | Prior | Posterior | Last Updated |',
             '|-------|---------|-------|-----------|--------------|']
    for row in rows:
        state, task_type = row[0], row[1]
        prior_pct = f'{row[2]}/{row[3]} ({100 * row[2] / row[3]:.0f}%)' if row[3] else 'n/a'
        post_pct = f'{row[4]}/{row[5]} ({100 * row[4] / row[5]:.0f}%)' if row[5] else 'n/a'
        lines.append(f'| {state} | {task_type} | {prior_pct} | {post_pct} | {row[6] or "n/a"} |')

    return '\n'.join(lines)


# ── Dialog history ─────────────────────────────────────────────────────────

def build_dialog_history(
    bus: SqliteMessageBus,
    conversation_id: str,
) -> str:
    """Build a dialog history string from prior messages on the bus.

    Returns a formatted string of prior turns for inclusion in the
    review prompt, giving the proxy context across the session.
    """
    messages = bus.receive(conversation_id)
    if not messages:
        return ''

    lines = []
    for msg in messages:
        label = 'Human' if msg.sender != 'proxy' else 'Proxy'
        lines.append(f'{label}: {msg.content}')

    return '\n'.join(lines) + '\n'


# ── Response signal parsing ────────────────────────────────────────────────

_CORRECTION_RE = re.compile(r'\[CORRECTION:\s*(.+?)\]')
_REINFORCE_RE = re.compile(r'\[REINFORCE:\s*(.+?)\]')


def _process_response_signals(response: str, *, conn, session: 'ReviewSession') -> None:
    """Parse structured signals from the proxy's response and act on them.

    Corrections are recorded as high-activation memory chunks.
    Reinforcements boost the trace count on existing chunks.
    """
    for match in _CORRECTION_RE.finditer(response):
        correction_text = match.group(1).strip()
        record_correction(conn, correction=correction_text, source=f'review:{session.human_name}')

    for match in _REINFORCE_RE.finditer(response):
        chunk_id = match.group(1).strip()
        try:
            reinforce_chunk(conn, chunk_id=chunk_id)
        except ValueError:
            _log.warning('Reinforce target %s not found', chunk_id)


# ── Review conversation turn ───────────────────────────────────────────────

def build_review_prompt(
    human_message: str,
    *,
    memory_context: str,
    accuracy_context: str,
    dialog_history: str = '',
) -> str:
    """Build the self-review prompt for the proxy agent.

    Unlike gate-prediction mode, the proxy is transparent about its memory:
    it explains activation levels, confidence scores, and prediction patterns.
    It accepts corrections and reinforcements conversationally.
    """
    return (
        'You are a human proxy agent in self-review mode. The human who you '
        'model is talking directly to you to inspect and calibrate your model '
        'of their decision-making.\n\n'
        'In this mode you are fully transparent. You:\n'
        '- Explain what patterns you have picked up from past gates\n'
        '- Show your confidence levels and where you are uncertain\n'
        '- Accept corrections ("stop flagging X", "care more about Y")\n'
        '- Accept reinforcements ("yes, that pattern is important")\n'
        '- Respond from your actual memory, citing activation levels and '
        'prediction history when relevant\n\n'
        'When the human corrects you, acknowledge the correction, explain '
        'how it will change your future behavior, and emit a structured tag:\n'
        '  [CORRECTION: <concise description of the correction>]\n'
        'When the human reinforces a pattern ("yes, that\'s important"), '
        'emit:\n'
        '  [REINFORCE: <chunk_id>]\n'
        'When the human asks what you have learned, summarize from the '
        'memories below.\n\n'
        f'{memory_context}\n\n'
        f'{accuracy_context}\n\n'
        f'{dialog_history}'
        f'Human: {human_message}\n'
    )


async def run_review_turn(
    human_message: str,
    *,
    conn,
    session: ReviewSession,
    bus: SqliteMessageBus,
    dialog_history: str = '',
) -> str:
    """Execute one turn of a proxy review conversation.

    1. Gathers introspection context from the proxy's ACT-R memory
    2. Invokes the proxy agent in self-review mode via claude -p
    3. Records both messages on the message bus
    4. Returns the proxy's response text

    The caller (bridge or CLI) is responsible for the conversation loop.
    """
    # Build dialog history from prior bus messages if not provided
    if not dialog_history:
        dialog_history = build_dialog_history(bus, session.conversation_id)

    # Record the human's message
    bus.send(session.conversation_id, session.human_name, human_message)

    # Gather memory context for the prompt
    current = get_interaction_counter(conn)
    entries = introspect_chunks(conn, current_interaction=current)
    memory_context = format_introspection(entries)
    accuracy_context = summarize_accuracy(conn)

    prompt = build_review_prompt(
        human_message,
        memory_context=memory_context,
        accuracy_context=accuracy_context,
        dialog_history=dialog_history,
    )

    # Invoke the proxy agent in review mode
    response = await _invoke_review_agent(prompt)

    # Process correction and reinforcement signals
    _process_response_signals(response, conn=conn, session=session)

    # Record the proxy's response
    bus.send(session.conversation_id, 'proxy', response)

    return response


class ReviewAgentError(RuntimeError):
    """Raised when the review agent invocation fails."""


async def _invoke_review_agent(prompt: str) -> str:
    """Invoke claude -p in review mode. Returns the response text.

    Raises ReviewAgentError on failure so callers can distinguish
    a failed invocation from a genuine proxy response.
    """
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                ['claude', '-p', '--output-format', 'text',
                 '--permission-mode', 'bypassPermissions'],
                input=prompt, capture_output=True, text=True, timeout=60,
            ),
        )
    except FileNotFoundError as exc:
        raise ReviewAgentError('claude CLI not found') from exc
    except subprocess.TimeoutExpired as exc:
        raise ReviewAgentError('review agent timed out') from exc

    if result.returncode != 0:
        raise ReviewAgentError(
            f'review agent exited with code {result.returncode}: '
            f'{result.stderr.strip()}'
        )
    if not result.stdout.strip():
        raise ReviewAgentError('review agent returned empty output')

    return result.stdout.strip()
