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
Issue #259, #331.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from typing import Any

from orchestrator.messaging import (
    ConversationType,
    SqliteMessageBus,
    make_conversation_id,
)
from orchestrator.office_manager import (
    NON_CONVERSATIONAL_SENDERS,
    _iter_stream_events,
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
        if msg.sender in NON_CONVERSATIONAL_SENDERS or msg.sender.startswith('unknown:'):
            continue
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


# ── Path helpers (bridge-facing) ─────────────────────────────────────────────

def proxy_bus_path(teaparty_home: str) -> str:
    """Return the canonical path to the proxy review message database."""
    from orchestrator.messaging import agent_bus_path
    return agent_bus_path(teaparty_home, 'proxy-review')


def proxy_memory_path(teaparty_home: str) -> str:
    """Return the canonical path to the global proxy ACT-R memory database.

    Used by the bridge-invoked proxy review chat to read and write the same
    ACT-R memory that consult_proxy reads at approval gates.  Issue #331.
    """
    return os.path.join(teaparty_home, 'management', 'agents', 'proxy-review', '.proxy-memory.db')



def _extract_slug_from_stream(stream_path: str, session_id: str, cwd: str) -> str:
    """Extract the conversation slug from a stream JSONL or Claude history file."""
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


# ── ProxyReviewSession ────────────────────────────────────────────────────────

class ProxyReviewSession:
    """Multi-turn proxy review conversation session.

    Each invocation runs the proxy-review agent via ClaudeRunner.  ACT-R
    memory context is built fresh on each turn so that corrections from the
    previous turn are reflected immediately.  Session ID is persisted via
    save_state/load_state for --resume support.

    Issue #331.
    """

    def __init__(self, teaparty_home: str, decider: str, llm_backend: str = 'claude'):
        self.teaparty_home = os.path.expanduser(teaparty_home)
        self._infra_dir = os.path.join(self.teaparty_home, 'management', 'agents', 'proxy-review')
        self.decider = decider
        self._llm_backend = llm_backend
        self.conversation_id = make_conversation_id(
            ConversationType.PROXY_REVIEW, decider,
        )
        self.claude_session_id: str | None = None
        self.conversation_title: str | None = None

        bus_path = proxy_bus_path(self.teaparty_home)
        os.makedirs(os.path.dirname(bus_path), exist_ok=True)
        self._bus = SqliteMessageBus(bus_path)

    def send_human_message(self, content: str) -> str:
        """Record a human message in the conversation. Returns message ID."""
        return self._bus.send(self.conversation_id, 'human', content)

    def send_agent_message(self, content: str) -> str:
        """Record a proxy message in the conversation. Returns message ID."""
        return self._bus.send(self.conversation_id, 'proxy', content)

    def get_messages(self, since_timestamp: float = 0.0):
        """Retrieve conversation messages, optionally since a timestamp."""
        return self._bus.receive(self.conversation_id, since_timestamp=since_timestamp)

    def build_context(self) -> str:
        """Build ACT-R memory context for the proxy agent prompt.

        Returns a string combining the conversation history, current ACT-R
        memory introspection, and prediction accuracy summary.
        """
        import sqlite3
        from orchestrator.proxy_memory import (
            open_proxy_db,
            get_interaction_counter,
        )

        mem_path = proxy_memory_path(self.teaparty_home)
        if os.path.exists(mem_path):
            conn = open_proxy_db(mem_path)
            try:
                current = get_interaction_counter(conn)
                entries = introspect_chunks(conn, current_interaction=current)
                memory_context = format_introspection(entries)
                accuracy_context = summarize_accuracy(conn)
            finally:
                conn.close()
        else:
            memory_context = 'No memories yet.'
            accuracy_context = 'No prediction accuracy data yet.'

        messages = self.get_messages()
        dialog_history = ''
        if messages:
            lines = []
            for msg in messages:
                if msg.sender in NON_CONVERSATIONAL_SENDERS or msg.sender.startswith('unknown:'):
                    continue
                label = 'Human' if msg.sender != 'proxy' else 'Proxy'
                lines.append(f'{label}: {msg.content}')
            dialog_history = '\n'.join(lines) + '\n'

        return build_review_prompt(
            '',
            memory_context=memory_context,
            accuracy_context=accuracy_context,
            dialog_history=dialog_history,
        )

    def _state_path(self) -> str:
        safe_id = self.decider.replace('/', '-').replace(':', '-').replace(' ', '-')
        return os.path.join(self._infra_dir, f'.proxy-session-{safe_id}.json')

    def save_state(self) -> None:
        """Persist session state to disk."""
        state = {
            'claude_session_id': self.claude_session_id,
            'decider': self.decider,
            'conversation_id': self.conversation_id,
            'conversation_title': self.conversation_title,
        }
        state_path = self._state_path()
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        tmp = state_path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(state, f)
        os.replace(tmp, state_path)

    def load_state(self) -> None:
        """Load session state from disk."""
        state_path = self._state_path()
        try:
            with open(state_path) as f:
                state = json.load(f)
            self.claude_session_id = state.get('claude_session_id')
            self.conversation_title = state.get('conversation_title') or None
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _latest_human_message(self) -> str:
        messages = self.get_messages()
        for msg in reversed(messages):
            if msg.sender == 'human':
                return msg.content
        return ''

    def _build_memory_context_prompt(self) -> str:
        """Build just the memory + accuracy context (no history, no human message)."""
        from orchestrator.proxy_memory import (
            open_proxy_db,
            get_interaction_counter,
        )

        mem_path = proxy_memory_path(self.teaparty_home)
        if os.path.exists(mem_path):
            conn = open_proxy_db(mem_path)
            try:
                current = get_interaction_counter(conn)
                entries = introspect_chunks(conn, current_interaction=current)
                memory_context = format_introspection(entries)
                accuracy_context = summarize_accuracy(conn)
            finally:
                conn.close()
        else:
            memory_context = 'No memories yet.'
            accuracy_context = 'No prediction accuracy data yet.'

        return f'{memory_context}\n\n{accuracy_context}'

    async def invoke(self, *, cwd: str) -> str:
        """Invoke the proxy-review agent to respond to the current conversation.

        Fresh session: sends full review prompt with history and memory context.
        Resumed session: sends fresh memory context + latest human message,
        so corrections from the previous turn are reflected immediately.

        Parses [CORRECTION:...] and [REINFORCE:...] signals from the response
        and stores them in the ACT-R memory DB before writing to the bus.

        Returns the agent's response text, or '' if invocation fails.
        """
        import tempfile
        from orchestrator.claude_runner import create_runner

        self.load_state()
        is_fresh_session = self.claude_session_id is None

        latest_human = self._latest_human_message()
        if not latest_human:
            return ''

        if self.claude_session_id:
            # Resumed: provide fresh memory context so corrections surface immediately.
            mem_ctx = self._build_memory_context_prompt()
            prompt = f'{mem_ctx}\n\nHuman: {latest_human}'
        else:
            # Fresh: full review prompt including all conversation history.
            messages = self.get_messages()
            dialog_history = ''
            if messages:
                lines = [
                    f'{"Human" if m.sender != "proxy" else "Proxy"}: {m.content}'
                    for m in messages
                    if m.sender not in NON_CONVERSATIONAL_SENDERS and not m.sender.startswith('unknown:')
                ]
                dialog_history = '\n'.join(lines) + '\n'
            from orchestrator.proxy_memory import (
                open_proxy_db,
                get_interaction_counter,
            )
            mem_path = proxy_memory_path(self.teaparty_home)
            if os.path.exists(mem_path):
                conn = open_proxy_db(mem_path)
                try:
                    current = get_interaction_counter(conn)
                    entries = introspect_chunks(conn, current_interaction=current)
                    memory_context = format_introspection(entries)
                    accuracy_context = summarize_accuracy(conn)
                finally:
                    conn.close()
            else:
                memory_context = 'No memories yet.'
                accuracy_context = 'No prediction accuracy data yet.'
            prompt = build_review_prompt(
                latest_human,
                memory_context=memory_context,
                accuracy_context=accuracy_context,
                dialog_history=dialog_history,
            )

        stream_fd, stream_path = tempfile.mkstemp(suffix='.jsonl', prefix='proxy-stream-')
        os.close(stream_fd)

        try:
            runner = create_runner(
                prompt,
                cwd=cwd,
                stream_file=stream_path,
                backend=self._llm_backend,
                lead='proxy-review',
                permission_mode='default',
                resume_session=self.claude_session_id,
            )
            result = await runner.run()

            events = list(_iter_stream_events(stream_path, 'proxy'))
            response_text = '\n'.join(c for s, c in events if s == 'proxy')

            if response_text:
                # Process correction/reinforce signals before writing to bus
                mem_path = proxy_memory_path(self.teaparty_home)
                os.makedirs(os.path.dirname(mem_path), exist_ok=True)
                from orchestrator.proxy_memory import open_proxy_db
                conn = open_proxy_db(mem_path)
                try:
                    _process_response_signals(response_text, conn=conn, session=ReviewSession(
                        conversation_id=self.conversation_id,
                        human_name=self.decider,
                        memory_db_path=mem_path,
                    ))
                finally:
                    conn.close()
                for sender, content in events:
                    self._bus.send(self.conversation_id, sender, content)
            else:
                self.claude_session_id = None
                self.save_state()
                self.send_agent_message(
                    'I was unable to produce a response (the session may have '
                    'expired). Please send your message again to start a fresh '
                    'session.'
                )

            if response_text and result.session_id:
                self.claude_session_id = result.session_id
                if is_fresh_session and not self.conversation_title:
                    slug = _extract_slug_from_stream(stream_path, result.session_id, cwd)
                    if slug:
                        self.conversation_title = slug
                self.save_state()

            return response_text
        finally:
            try:
                os.unlink(stream_path)
            except OSError:
                pass


def read_proxy_session_title(teaparty_home: str, decider: str) -> str | None:
    """Read the conversation title from a saved proxy session state file.

    Returns None if no title is stored or the file doesn't exist.
    """
    safe_id = decider.replace('/', '-').replace(':', '-').replace(' ', '-')
    state_path = os.path.join(teaparty_home, 'management', 'agents', 'proxy-review', f'.proxy-session-{safe_id}.json')
    try:
        with open(state_path) as f:
            state = json.load(f)
        return state.get('conversation_title') or None
    except (FileNotFoundError, json.JSONDecodeError):
        return None
