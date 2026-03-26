"""Proxy agent — a Claude agent that stands in for the human.

Every time the system needs the human's input — whether it's an approval gate,
an agent escalation, or a clarifying question — it goes through the same path:

  1. Gather context: ACT-R memory retrieval + learned patterns
  2. Two-pass prediction:
     Pass 1 (prior): predict without seeing the artifact
     Pass 2 (posterior): predict after reading the artifact
  3. The agent's self-assessed confidence is the decision signal.
     ACT-R memory depth determines cold-start gating.
     EMA is tracked separately as a system health monitor.
  4. If confident → agent's text IS the answer
  5. If not confident → same question goes to the human
  6. Both predicted text and actual text feed into learning (memory chunks)

The proxy agent always runs.  Statistics never gate whether the agent is
consulted — they are tracked for monitoring only.

The proxy agent has file-read tools, receives ACT-R memory chunks and
learned behavioral patterns, and can engage in multi-turn dialog with
the requester before deciding.

This module is the single proxy invocation path used by both ApprovalGate
(for approval gates) and EscalationListener (for agent questions via MCP).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger('orchestrator.proxy_agent')


@dataclass
class ProxyResult:
    """The proxy agent's output."""
    text: str                   # Full text response (what the human would say)
    confidence: float           # 0.0–1.0: how confident the agent is this matches the human
    from_agent: bool = True     # True if agent generated this, False if stats escalated
    # Two-pass prediction data (populated when ACT-R memory is active)
    prior_action: str = ''
    prior_confidence: float = 0.0
    posterior_action: str = ''
    posterior_confidence: float = 0.0
    prediction_delta: str = ''
    salient_percepts: list[str] = field(default_factory=list)


# Confidence threshold for the proxy agent's text response.
PROXY_AGENT_CONFIDENCE_THRESHOLD = 0.8


async def consult_proxy(
    question: str,
    *,
    state: str = '',
    project_slug: str = 'default',
    artifact_path: str = '',
    session_worktree: str = '',
    infra_dir: str = '',
    proxy_model_path: str = '',
    team: str = '',
    phase_start_time: float = 0.0,
    proxy_enabled: bool = True,
    dialog_history: str = '',
) -> ProxyResult:
    """Consult the proxy agent.  The ONE entry point for all proxy decisions.

    Always invokes the proxy agent.  After the agent responds, uses
    statistical history to calibrate the agent's self-assessed confidence.
    Returns a ProxyResult with the agent's text and calibrated confidence.

    The caller decides what to do based on confidence:
    - confidence >= threshold → use the text
    - confidence < threshold → ask the human
    """
    # Proxy disabled — skip agent, go straight to human.
    if not proxy_enabled:
        return ProxyResult(text='', confidence=0.0, from_agent=False)

    from projects.POC.scripts.approval_gate import (
        resolve_team_model_path,
        retrieve_similar_interactions,
    )
    from projects.POC.orchestrator.actors import MIN_EXECUTION_SECONDS

    # Elapsed-time guard for execution states
    if state in ('TASK_ASSERT', 'WORK_ASSERT') and phase_start_time > 0:
        import time
        elapsed = time.monotonic() - phase_start_time
        if elapsed < MIN_EXECUTION_SECONDS:
            _log.info(
                'Elapsed-time guard: %s after %.0fs (min %ds) — escalating',
                state, elapsed, MIN_EXECUTION_SECONDS,
            )
            return ProxyResult(text='', confidence=0.0, from_agent=False)

    # Gather learning context (patterns, similar interactions) for the agent.
    learned_patterns = ''
    similar: list = []
    actr_retrieval = _EMPTY_RETRIEVAL
    try:
        model_path = resolve_team_model_path(proxy_model_path, team)
        project_dir = os.path.dirname(model_path)

        # Tier 1: read flat behavioral patterns
        patterns_path = os.path.join(project_dir, 'proxy-patterns.md')
        if os.path.isfile(patterns_path):
            try:
                with open(patterns_path) as f:
                    learned_patterns = f.read()
            except OSError:
                pass

        # Tier 2: retrieve similar past interactions (legacy)
        log_path = os.path.join(project_dir, '.proxy-interactions.jsonl')
        similar = retrieve_similar_interactions(
            log_path=log_path, state=state, project=project_slug, top_k=5,
        )

        # Tier 3: ACT-R memory retrieval
        actr_retrieval = _retrieve_actr_memories(
            proxy_model_path=proxy_model_path,
            team=team,
            state=state,
            task_type=project_slug,
            question=question,
        )
    except Exception:
        _log.debug('Failed to load learning context', exc_info=True)

    # Build accuracy context string for the proxy prompt
    accuracy_context = _format_accuracy_context(actr_retrieval.accuracy, state, project_slug)

    # Always invoke the proxy agent (two-pass prediction).
    try:
        two_pass = await run_proxy_agent(
            question=question,
            state=state,
            artifact_path=artifact_path,
            session_worktree=session_worktree,
            infra_dir=infra_dir,
            learned_patterns=learned_patterns,
            similar_interactions=similar,
            actr_memories=actr_retrieval.serialized,
            accuracy_context=accuracy_context,
            dialog_history=dialog_history,
        )
    except Exception:
        _log.debug('Exception invoking proxy agent', exc_info=True)
        return ProxyResult(text='', confidence=0.0, from_agent=False)

    if not two_pass.text:
        return ProxyResult(text='', confidence=0.0, from_agent=True)

    # ACT-R Rule 2: reinforce retrieved chunks now that the agent has
    # consumed them and produced a response. The retrieval itself is the
    # signal — correctness feedback flows through the chunk's outcome field.
    _reinforce_actr_memories(actr_retrieval)

    # Calibrate confidence using memory depth and prediction accuracy.
    confidence = _calibrate_confidence(
        two_pass.confidence, state, project_slug, proxy_model_path, team,
        accuracy=actr_retrieval.accuracy,
    )

    return ProxyResult(
        text=two_pass.text,
        confidence=confidence,
        from_agent=True,
        prior_action=two_pass.prior_action,
        prior_confidence=two_pass.prior_confidence,
        posterior_action=two_pass.posterior_action,
        posterior_confidence=two_pass.posterior_confidence,
        prediction_delta=two_pass.prediction_delta,
        salient_percepts=two_pass.salient_percepts,
    )


def _calibrate_confidence(
    agent_confidence: float,
    state: str,
    project_slug: str,
    proxy_model_path: str,
    team: str,
    accuracy: dict | None = None,
) -> float:
    """Calibrate confidence using memory depth and prediction accuracy.

    Three gates, applied in order:

    1. Cold-start guard: if the ACT-R memory store has fewer than
       MEMORY_DEPTH_THRESHOLD distinct (state, task_type) pairs, cap
       confidence at 0.5.

    2. Accuracy-based autonomy: if per-context posterior accuracy is
       available and meets the threshold (>= ACCURACY_AUTONOMY_THRESHOLD
       over >= ACCURACY_MIN_INTERACTIONS), the proxy has earned autonomy
       in this context — trust the agent's self-assessed confidence.
       If accuracy is below the threshold with sufficient data, cap
       confidence to force escalation.

    3. Otherwise, return the agent's self-assessed confidence unchanged.

    EMA is tracked separately as a system health monitor and does not
    influence the returned confidence.
    """
    depth = _get_memory_depth(proxy_model_path, team)
    if depth < MEMORY_DEPTH_THRESHOLD:
        return min(agent_confidence, 0.5)

    if accuracy:
        posterior_total = accuracy.get('posterior_total', 0)
        if posterior_total >= ACCURACY_MIN_INTERACTIONS:
            posterior_correct = accuracy.get('posterior_correct', 0)
            posterior_rate = posterior_correct / posterior_total
            if posterior_rate < ACCURACY_AUTONOMY_THRESHOLD:
                return min(agent_confidence, 0.5)

    return agent_confidence


# Minimum number of distinct (state, task_type) pairs in the ACT-R memory
# store before the proxy is trusted to use its own confidence assessment.
MEMORY_DEPTH_THRESHOLD = 3

# Posterior accuracy threshold for earned autonomy: the proxy must correctly
# predict the human's action at least this fraction of the time.
ACCURACY_AUTONOMY_THRESHOLD = 0.85

# Minimum number of interactions before accuracy-based gating applies.
# Below this, accuracy data is too sparse to be meaningful.
ACCURACY_MIN_INTERACTIONS = 10


def _get_memory_depth(proxy_model_path: str, team: str) -> int:
    """Query the ACT-R memory store for experience diversity."""
    try:
        from projects.POC.orchestrator.proxy_memory import (
            memory_depth,
            open_proxy_db,
            resolve_memory_db_path,
        )
        db_path = resolve_memory_db_path(proxy_model_path, team)
        if not os.path.isfile(db_path):
            return 0
        conn = open_proxy_db(db_path)
        try:
            return memory_depth(conn)
        finally:
            conn.close()
    except Exception:
        _log.debug('Failed to query memory depth', exc_info=True)
        return 0


@dataclass
class _ActrRetrievalResult:
    """Result of ACT-R memory retrieval, carrying data needed for reinforcement."""
    serialized: str                  # chunk text for the proxy prompt
    chunk_ids: list[str]             # IDs of retrieved chunks (for post-consumption reinforcement)
    db_path: str                     # path to the memory DB
    interaction_counter: int         # counter at retrieval time
    accuracy: dict | None = None     # per-context accuracy record (if available)


_EMPTY_RETRIEVAL = _ActrRetrievalResult(serialized='', chunk_ids=[], db_path='', interaction_counter=0)


def _retrieve_actr_memories(
    *,
    proxy_model_path: str,
    team: str,
    state: str,
    task_type: str,
    question: str,
    scoring: str = 'multi_dim',
) -> _ActrRetrievalResult:
    """Retrieve ACT-R memory chunks for the current gate context.

    Returns chunk IDs alongside the serialized text so the caller can
    reinforce after the proxy agent has consumed the memories.

    scoring='multi_dim' (default): 5 independent embeddings per dimension.
    scoring='single': 1 blended embedding (issue #222 ablation Config B).
    """
    try:
        from projects.POC.orchestrator.proxy_memory import (
            open_proxy_db,
            resolve_memory_db_path,
            retrieve_chunks,
            serialize_chunks_for_prompt,
            get_interaction_counter,
            get_accuracy,
            blended_text_from_fields,
        )
        from projects.POC.scripts.memory_indexer import try_embed, detect_provider

        db_path = resolve_memory_db_path(proxy_model_path, team)
        if not os.path.isfile(db_path):
            return _EMPTY_RETRIEVAL

        conn = open_proxy_db(db_path)
        try:
            current = get_interaction_counter(conn)
            if current == 0:
                return _EMPTY_RETRIEVAL

            provider, model = detect_provider()

            if scoring == 'single':
                # Config B: single blended context embedding
                blended_str = blended_text_from_fields(
                    state=state, task_type=task_type,
                )
                # Include the question in the blended context
                if question:
                    blended_str = f'{blended_str} {question}' if blended_str else question
                context_blended = try_embed(blended_str, conn=conn, provider=provider, model=model)
                chunks = retrieve_chunks(
                    conn, state=state, task_type=task_type,
                    context_blended=context_blended,
                    scoring='single',
                    current_interaction=current,
                )
            else:
                # Config A: per-dimension context embeddings
                context_embeddings: dict[str, list[float]] = {}
                sit_vec = try_embed(f'{state} {task_type}', conn=conn, provider=provider, model=model)
                if sit_vec:
                    context_embeddings['situation'] = sit_vec
                stim_vec = try_embed(question, conn=conn, provider=provider, model=model)
                if stim_vec:
                    context_embeddings['stimulus'] = stim_vec
                chunks = retrieve_chunks(
                    conn, state=state, task_type=task_type,
                    context_embeddings=context_embeddings,
                    current_interaction=current,
                )

            accuracy = get_accuracy(conn, state=state, task_type=task_type)
            return _ActrRetrievalResult(
                serialized=serialize_chunks_for_prompt(chunks),
                chunk_ids=[c.id for c in chunks],
                db_path=db_path,
                interaction_counter=current,
                accuracy=accuracy,
            )
        finally:
            conn.close()
    except Exception:
        _log.debug('ACT-R memory retrieval failed', exc_info=True)
        return _EMPTY_RETRIEVAL


def _format_accuracy_context(
    accuracy: dict | None, state: str, task_type: str,
) -> str:
    """Format prediction accuracy data for the proxy prompt."""
    if not accuracy:
        return ''
    parts = [f'--- PREDICTION ACCURACY for {state} × {task_type} ---']
    pt = accuracy.get('prior_total', 0)
    if pt > 0:
        pc = accuracy.get('prior_correct', 0)
        pct = pc / pt * 100
        parts.append(f'Prior accuracy: {pc}/{pt} ({pct:.0f}%)')
    post_t = accuracy.get('posterior_total', 0)
    if post_t > 0:
        post_c = accuracy.get('posterior_correct', 0)
        post_pct = post_c / post_t * 100
        parts.append(f'Posterior accuracy: {post_c}/{post_t} ({post_pct:.0f}%)')
    if not pt and not post_t:
        return ''
    return '\n'.join(parts)


def _reinforce_actr_memories(retrieval: _ActrRetrievalResult) -> None:
    """ACT-R Rule 2: reinforce chunks after the proxy agent has consumed them.

    Opens a fresh DB connection, adds a trace to each retrieved chunk at the
    interaction counter value from retrieval time, then closes the connection.
    The interaction counter is NOT incremented — that is reserved for
    record_interaction() (Rule 1: chunk creation).
    """
    if not retrieval.chunk_ids or not retrieval.db_path:
        return
    try:
        from projects.POC.orchestrator.proxy_memory import (
            open_proxy_db,
            reinforce_retrieved,
            get_chunk,
            MemoryChunk,
        )
        conn = open_proxy_db(retrieval.db_path)
        try:
            # Reconstruct minimal chunk objects with just the IDs
            chunks = [MemoryChunk(
                id=cid, type='', state='', task_type='', outcome='', content='',
            ) for cid in retrieval.chunk_ids]
            reinforce_retrieved(conn, chunks, retrieval.interaction_counter)
        finally:
            conn.close()
    except Exception:
        _log.debug('ACT-R reinforcement failed', exc_info=True)


@dataclass
class _TwoPassResult:
    """Internal result from two-pass prediction."""
    text: str = ''
    confidence: float = 0.0
    prior_action: str = ''
    prior_confidence: float = 0.0
    prior_text: str = ''
    posterior_action: str = ''
    posterior_confidence: float = 0.0
    prediction_delta: str = ''
    salient_percepts: list[str] = field(default_factory=list)


async def run_proxy_agent(
    question: str,
    *,
    state: str = '',
    artifact_path: str = '',
    session_worktree: str = '',
    infra_dir: str = '',
    learned_patterns: str = '',
    similar_interactions: list | None = None,
    actr_memories: str = '',
    accuracy_context: str = '',
    dialog_history: str = '',
) -> _TwoPassResult:
    """Invoke the proxy agent with two-pass prediction.

    Pass 1 (prior): predict without seeing the artifact.
    Pass 2 (posterior): predict after reading the artifact + prior.

    Returns a _TwoPassResult with both predictions and surprise data.
    """
    # Build shared context blocks
    memory_block = ''
    if actr_memories:
        memory_block = f'\n{actr_memories}\n'

    accuracy_block = ''
    if accuracy_context:
        accuracy_block = f'\n{accuracy_context}\n'

    learning_block = ''
    if learned_patterns:
        learning_block += (
            f'\n--- LEARNED BEHAVIORAL PATTERNS ---\n'
            f'These are patterns the human has established through past reviews:\n'
            f'{learned_patterns}\n'
        )
    if similar_interactions:
        interaction_lines = []
        for entry in similar_interactions[-5:]:
            outcome = entry.get('outcome', '?')
            delta = entry.get('delta', '')
            ts = entry.get('timestamp', '')
            line = f'  {ts}: outcome={outcome}'
            if delta:
                line += f' — {delta[:200]}'
            interaction_lines.append(line)
        if interaction_lines:
            learning_block += (
                f'\n--- PAST INTERACTIONS AT THIS GATE ---\n'
                + '\n'.join(interaction_lines) + '\n'
            )

    dialog_block = ''
    if dialog_history:
        dialog_block = (
            f'\n--- DIALOG SO FAR ---\n'
            f'{dialog_history}\n'
            f'Continue the dialog based on what was said above.\n'
        )

    # Build artifact/upstream context block
    context_parts = _build_artifact_context(
        artifact_path, session_worktree, infra_dir, state,
    )
    context_block = '\n'.join(context_parts) if context_parts else ''

    # ── Pass 1: Prior (without artifact) ─────────────────────────────────
    prior_prompt = (
        f"You are a human proxy agent. You predict what the human would say "
        f"at a CfA approval gate. You have NOT seen the artifact yet.\n\n"
        f"{memory_block}"
        f"{accuracy_block}"
        f"{learning_block}"
        f"{dialog_block}\n"
        f"State: {state}\n"
        f"Question: {question}\n\n"
        f"Based on your memories of working with this human and the context "
        f"above, predict what the human would do.\n\n"
        f"On the FINAL lines, write:\n"
        f"ACTION: approve\n"
        f"CONFIDENCE: 0.85\n\n"
        f"ACTION must be one of: approve, correct, escalate, withdraw.\n"
        f"CONFIDENCE is a decimal 0.0 to 1.0."
    )

    prior_text, prior_confidence, prior_action = await _invoke_claude_proxy(
        prior_prompt, session_worktree,
    )

    # Fast-fail: if Pass 1 returned nothing, the CLI is degraded.
    # Skip Pass 2 and surprise extraction to bound worst-case latency.
    if not prior_text and not prior_action:
        return _TwoPassResult()

    # ── Pass 2: Posterior (with artifact + prior) ────────────────────────
    prior_block = ''
    if prior_action:
        prior_block = (
            f'\nYour prior prediction (before seeing the artifact):\n'
            f'ACTION: {prior_action}\n'
            f'Reasoning: {prior_text[:500]}\n'
        )

    posterior_prompt = (
        f"You are a human proxy agent. You predict what the human would say "
        f"at a CfA approval gate. You have now seen the artifact.\n\n"
        f"{memory_block}"
        f"{accuracy_block}"
        f"{learning_block}"
        f"{dialog_block}\n"
        f"State: {state}\n"
        f"Question: {question}\n\n"
        f"{prior_block}\n"
        f"Now read the artifact and any upstream context files. Revise your "
        f"prediction based on what you find.\n\n"
        f"{context_block}\n\n"
        f"Respond as the human would. If the artifact changed your prediction, "
        f"explain what changed and why.\n\n"
        f"On the FINAL lines, write:\n"
        f"ACTION: approve\n"
        f"CONFIDENCE: 0.85\n\n"
        f"ACTION must be one of: approve, correct, escalate, withdraw.\n"
        f"CONFIDENCE is a decimal 0.0 to 1.0."
    )

    post_text, post_confidence, post_action = await _invoke_claude_proxy(
        posterior_prompt, session_worktree,
    )

    # Fast-fail: if Pass 2 returned nothing, fall back to the prior result.
    # Skip surprise extraction to avoid a third CLI call on a degraded CLI.
    if not post_text and not post_action:
        return _TwoPassResult(
            text=prior_text,
            confidence=prior_confidence,
            prior_action=prior_action,
            prior_confidence=prior_confidence,
            prior_text=prior_text,
        )

    # ── Surprise detection ───────────────────────────────────────────────
    prediction_delta = ''
    salient_percepts: list[str] = []
    action_changed = prior_action and post_action and prior_action != post_action
    confidence_shifted = abs(post_confidence - prior_confidence) > 0.3

    if action_changed or confidence_shifted:
        prediction_delta, salient_percepts = await _extract_surprise(
            prior_action, prior_confidence, prior_text,
            post_action, post_confidence, post_text,
            artifact_path, session_worktree,
        )

    return _TwoPassResult(
        text=post_text or prior_text,
        confidence=post_confidence if post_text else prior_confidence,
        prior_action=prior_action,
        prior_confidence=prior_confidence,
        prior_text=prior_text,
        posterior_action=post_action,
        posterior_confidence=post_confidence,
        prediction_delta=prediction_delta,
        salient_percepts=salient_percepts,
    )


def _build_artifact_context(
    artifact_path: str, session_worktree: str,
    infra_dir: str, state: str,
) -> list[str]:
    """Build context parts for artifact and upstream documents."""
    context_parts = []

    if artifact_path and os.path.isfile(artifact_path):
        context_parts.append(f'Artifact under review: {artifact_path}')
    elif not artifact_path and session_worktree and state in ('TASK_ASSERT', 'TASK_ESCALATE'):
        context_parts.append(
            f'No specific artifact to review. The task deliverables are in '
            f'the session worktree at {session_worktree}. Use your Read, '
            f'Glob, and Grep tools to find and review the deliverables.'
        )

    if state in ('PLAN_ASSERT', 'WORK_ASSERT', 'TASK_ASSERT', 'TASK_ESCALATE'):
        for name in ('INTENT.md',):
            for search_dir in (infra_dir, session_worktree):
                if not search_dir:
                    continue
                path = os.path.join(search_dir, name)
                if os.path.isfile(path):
                    context_parts.append(f'Upstream context: {path}')
                    break
    if state in ('WORK_ASSERT', 'TASK_ASSERT', 'TASK_ESCALATE'):
        for name in ('PLAN.md', '.work-summary.md'):
            for search_dir in (infra_dir, session_worktree):
                if not search_dir:
                    continue
                path = os.path.join(search_dir, name)
                if os.path.isfile(path):
                    context_parts.append(f'Upstream context: {path}')
                    break

    return context_parts


async def _invoke_claude_proxy(
    prompt: str, session_worktree: str,
) -> tuple[str, float, str]:
    """Invoke claude -p and parse output. Returns (text, confidence, action)."""
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                ['claude', '-p', '--output-format', 'text',
                 '--allowedTools', 'Read,Glob,Grep',
                 '--permission-mode', 'bypassPermissions'],
                input=prompt, capture_output=True, text=True, timeout=60,
                cwd=session_worktree or None,
            ),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        _log.warning('Proxy agent invocation failed')
        return ('', 0.0, '')

    if result.returncode != 0 or not result.stdout.strip():
        _log.warning('Proxy agent returned non-zero or empty output')
        return ('', 0.0, '')

    output = result.stdout.strip()
    text, confidence = parse_proxy_agent_output(output)
    action = parse_action_from_output(output)
    return (text, confidence, action)


async def _extract_surprise(
    prior_action: str, prior_confidence: float, prior_text: str,
    post_action: str, post_confidence: float, post_text: str,
    artifact_path: str, session_worktree: str,
) -> tuple[str, list[str]]:
    """Extract surprise description and salient percepts when prediction changed."""
    prompt = (
        f"The proxy's prediction changed after seeing the artifact.\n\n"
        f"Prior: {prior_action} ({prior_confidence:.2f})\n"
        f"Posterior: {post_action} ({post_confidence:.2f})\n\n"
        f"Prior reasoning: {prior_text[:300]}\n"
        f"Posterior reasoning: {post_text[:300]}\n"
    )
    if artifact_path:
        prompt += f"\nArtifact: {artifact_path}\n"
    prompt += (
        f"\nIn one sentence, describe what in the artifact caused the "
        f"prediction to change.\n"
        f"Then list 2-5 specific artifact features (phrases) that drove "
        f"the change, one per line prefixed with \"- \"."
    )

    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                ['claude', '-p', '--output-format', 'text',
                 '--permission-mode', 'bypassPermissions'],
                input=prompt, capture_output=True, text=True, timeout=30,
                cwd=session_worktree or None,
            ),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ('', [])

    if result.returncode != 0 or not result.stdout.strip():
        return ('', [])

    lines = result.stdout.strip().split('\n')
    description = ''
    percepts: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('- '):
            percepts.append(stripped[2:])
        elif not description and stripped:
            description = stripped

    return (description, percepts)


def parse_proxy_agent_output(output: str) -> tuple[str, float]:
    """Parse proxy agent output into (text, confidence).

    The agent appends a line like 'CONFIDENCE: 0.85' at the end.
    Everything before that line is the response text.

    Searches from the end of the output to handle cases where the
    agent writes the marker on its final line.  Falls back to 0.0
    confidence if no marker is found — this ensures the human is
    always asked when parsing fails.
    """
    lines = output.rstrip().split('\n')
    for i in range(len(lines) - 1, max(len(lines) - 5, -1), -1):
        match = re.search(r'CONFIDENCE:\s*([\d.]+)', lines[i], re.IGNORECASE)
        if match:
            try:
                confidence = min(1.0, max(0.0, float(match.group(1))))
            except ValueError:
                continue
            text = '\n'.join(lines[:i]).strip()
            return (text, confidence)
    # No confidence marker — treat as low confidence so human is asked
    return (output, 0.0)


_VALID_ACTIONS = frozenset(['approve', 'correct', 'escalate', 'withdraw'])


def parse_action_from_output(output: str) -> str:
    """Extract ACTION: <action> from proxy agent output.

    Searches from the end of the output. Returns the action string
    (approve, correct, escalate, withdraw) or empty string if not found.
    """
    lines = output.rstrip().split('\n')
    for i in range(len(lines) - 1, max(len(lines) - 5, -1), -1):
        match = re.search(r'ACTION:\s*(\w+)', lines[i], re.IGNORECASE)
        if match:
            action = match.group(1).lower()
            if action in _VALID_ACTIONS:
                return action
    return ''
