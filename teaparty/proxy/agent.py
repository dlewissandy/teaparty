"""Proxy memory-conflict classifiers (issue #228, #238).

The bulk of this module — ``consult_proxy``, two-pass prediction,
ACT-R retrieval, confidence calibration, ``ProxyResult`` — was the
proxy invocation pipeline used by the legacy multi-turn approval-gate
model.  All of that retired when escalations became a skill (#420);
the bridge invokes the proxy through the unified agent loop now,
not via this module.

What's left is the LLM-backed classifier helpers used by the proxy's
memory consolidation pipeline:

* ``_classify_conflict_llm`` — given two ``MemoryChunk``s that
  overlap in retrieval context, classify the conflict as
  preference_drift / context_sensitivity / genuine_tension /
  retrieval_noise.  Drives reinforcement-window decisions.
* ``_classify_conflict_llm_for_entries`` — given two
  ``MemoryEntry``s whose content collides, classify the merge as
  ADD / UPDATE / DELETE / SKIP.  Drives ``proxy.md`` consolidation
  via ``consolidate_proxy_file``.

Both call ``claude -p`` synchronously; both fall back to the
preserve-both decision on any failure so consolidation never loses
data.
"""
from __future__ import annotations

import logging
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teaparty.learning.episodic.entry import MemoryEntry
    from teaparty.proxy.memory import MemoryChunk

_log = logging.getLogger('teaparty.proxy.agent')


_CONFLICT_CLASSIFY_PROMPT = """\
Two retrieved memories from the same decision context appear to conflict.

Memory A ({chunk_a_id}):
  State: {state_a}  Task: {task_a}  Outcome: {outcome_a}
  Content: {content_a}

Memory B ({chunk_b_id}):
  State: {state_b}  Task: {task_b}  Outcome: {outcome_b}
  Content: {content_b}

Classify this conflict. Reply with EXACTLY one line in this format:
CAUSE: <preference_drift|context_sensitivity|genuine_tension|retrieval_noise>

Rules:
- preference_drift: the human changed their mind; the newer memory supersedes the older.
- context_sensitivity: both are correct in different contexts (domain, stakes, urgency).
- genuine_tension: recent, same domain, unresolved — the human has not resolved this tension.
- retrieval_noise: these are not actually about the same thing; apparent conflict is an artifact.

When uncertain, default to context_sensitivity (preserve both).
"""


def _classify_conflict_llm(
    chunk_a: 'MemoryChunk',
    chunk_b: 'MemoryChunk',
    session_worktree: str = '',
) -> str | None:
    """Classify a conflicting pair via claude -p.

    Returns one of: preference_drift, context_sensitivity, genuine_tension,
    retrieval_noise.  Returns None on failure so the caller can track
    degradation (#238).
    """
    prompt = _CONFLICT_CLASSIFY_PROMPT.format(
        chunk_a_id=chunk_a.id[:8], state_a=chunk_a.state,
        task_a=chunk_a.task_type, outcome_a=chunk_a.outcome,
        content_a=chunk_a.content[:500],
        chunk_b_id=chunk_b.id[:8], state_b=chunk_b.state,
        task_b=chunk_b.task_type, outcome_b=chunk_b.outcome,
        content_b=chunk_b.content[:500],
    )
    try:
        result = subprocess.run(
            ['claude', '-p', '--output-format', 'text',
             '--permission-mode', 'bypassPermissions'],
            input=prompt, capture_output=True, text=True, timeout=30,
            cwd=session_worktree or None,
        )
    except FileNotFoundError:
        _log.warning('LLM conflict classification failed: claude CLI not found')
        return None
    except subprocess.TimeoutExpired:
        _log.warning('LLM conflict classification failed: timed out after 30s')
        return None

    if result.returncode != 0 or not result.stdout.strip():
        _log.warning('LLM conflict classification failed: returncode=%s, output=%s',
                      result.returncode, bool(result.stdout.strip()))
        return None

    output = result.stdout.strip()
    valid_causes = {'preference_drift', 'context_sensitivity', 'genuine_tension', 'retrieval_noise'}
    for line in output.split('\n'):
        line = line.strip()
        if line.upper().startswith('CAUSE:'):
            cause = line.split(':', 1)[1].strip().lower()
            if cause in valid_causes:
                return cause
    _log.warning('LLM conflict classification failed: no valid CAUSE line in output')
    return None


def _classify_conflict_llm_for_entries(
    entry_a: 'MemoryEntry',
    entry_b: 'MemoryEntry',
    session_worktree: str = '',
) -> str:
    """Classify a conflicting MemoryEntry pair via claude -p.

    Used by consolidate_proxy_file() as the classifier parameter for
    proxy.md consolidation (Stage 2).

    Returns one of: ADD, UPDATE, DELETE, SKIP.
    """
    prompt = f"""\
Two entries in the proxy's preference store appear to be about the same topic.

Entry A (created {entry_a.created_at}):
{entry_a.content[:500]}

Entry B (created {entry_b.created_at}):
{entry_b.content[:500]}

Classify the relationship. Reply with EXACTLY one line in this format:
DECISION: <ADD|UPDATE|DELETE|SKIP>

Rules:
- ADD: these entries do not conflict; both should be kept.
- UPDATE: entry B complements entry A; merge them.
- DELETE: entry B supersedes entry A; remove entry A.
- SKIP: entry B is already represented by entry A; discard entry B.

When uncertain, reply ADD (preserve both).
"""
    try:
        result = subprocess.run(
            ['claude', '-p', '--output-format', 'text',
             '--permission-mode', 'bypassPermissions'],
            input=prompt, capture_output=True, text=True, timeout=30,
            cwd=session_worktree or None,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 'ADD'

    if result.returncode != 0 or not result.stdout.strip():
        return 'ADD'

    from teaparty.proxy.memory import (
        CONSOLIDATION_ADD, CONSOLIDATION_UPDATE,
        CONSOLIDATION_DELETE, CONSOLIDATION_SKIP,
    )
    valid = {CONSOLIDATION_ADD, CONSOLIDATION_UPDATE, CONSOLIDATION_DELETE, CONSOLIDATION_SKIP}
    output = result.stdout.strip()
    for line in output.split('\n'):
        line = line.strip()
        if line.upper().startswith('DECISION:'):
            decision = line.split(':', 1)[1].strip().upper()
            if decision in valid:
                return decision
    return CONSOLIDATION_ADD
