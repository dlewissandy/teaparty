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
import random
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger('teaparty.proxy.agent')


@dataclass
class ProxyResult:
    """The proxy agent's output."""
    text: str                   # Full text response (what the human would say)
    confidence: float           # 0.0–1.0: how confident the agent is this matches the human
    from_agent: bool = True     # True if agent generated this, False if stats escalated
    # Two-pass prediction data (populated when ACT-R memory is active).
    # Action classification was removed in the 583cccd8 conversational-prompts
    # migration — prompts now emit natural-voice text, which _classify_review
    # categorizes downstream from the final human/proxy response.
    prior_confidence: float = 0.0
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

    from teaparty.proxy.approval_gate import (
        resolve_team_model_path,
        retrieve_similar_interactions,
    )

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
            artifact_path=artifact_path,
        )
    except Exception:
        _log.debug('Failed to load learning context', exc_info=True)

    # Build accuracy context string for the proxy prompt
    accuracy_context = _format_accuracy_context(actr_retrieval.accuracy, state, project_slug)

    # Retrieve task learnings from the learning system for the proxy's context.
    # This bridges the gap: organizational task knowledge (e.g., "database
    # migrations need rollback strategies") reaches the proxy at gate time.
    task_learnings = ''
    try:
        task_learnings = _retrieve_task_learnings(
            proxy_model_path=proxy_model_path,
            question=question,
            infra_dir=infra_dir,
        )
    except Exception:
        _log.debug('Task learning retrieval failed', exc_info=True)

    # Always invoke the proxy agent (two-pass prediction).
    # Issue #228: append conflict context to ACT-R memories so the proxy
    # can reason about detected contradictions in its retrieved evidence.
    actr_text = actr_retrieval.serialized
    if actr_retrieval.conflict_context:
        actr_text = f'{actr_text}\n\n{actr_retrieval.conflict_context}' if actr_text else actr_retrieval.conflict_context
    try:
        two_pass = await run_proxy_agent(
            question=question,
            state=state,
            artifact_path=artifact_path,
            session_worktree=session_worktree,
            infra_dir=infra_dir,
            learned_patterns=learned_patterns,
            similar_interactions=similar,
            actr_memories=actr_text,
            accuracy_context=accuracy_context,
            dialog_history=dialog_history,
            task_learnings=task_learnings,
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

    # Calibrate confidence using memory depth, prediction accuracy,
    # and contradiction signal (#228).
    confidence = _calibrate_confidence(
        two_pass.confidence, state, project_slug, proxy_model_path, team,
        accuracy=actr_retrieval.accuracy,
        genuine_tension=actr_retrieval.has_genuine_tension,
    )

    return ProxyResult(
        text=two_pass.text,
        confidence=confidence,
        from_agent=True,
        prior_confidence=two_pass.prior_confidence,
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
    genuine_tension: bool = False,
    _random: float | None = None,
) -> float:
    """Calibrate confidence using memory depth, prediction accuracy,
    contradiction signal, staleness, and exploration.

    Six gates, applied in order:

    1. Cold-start guard: if the ACT-R memory store has fewer than
       MEMORY_DEPTH_THRESHOLD distinct (state, task_type) pairs, cap
       confidence at 0.5.

    2. Genuine tension (#228): if retrieved memories contain a genuine
       unresolved tension (recent, same domain, high confidence both),
       cap confidence at 0.5 to force escalation. The proxy cannot
       resolve this without human input.

    3. Staleness guard (#237): if the proxy hasn't received human
       feedback for this (state, task_type) in > STALENESS_DAYS days,
       cap confidence at 0.5. Preferences drift; the model must not
       converge to an outdated snapshot.

    4. Exploration rate (#237): even when confidence is high, cap at
       0.5 with probability EXPLORATION_RATE. This prevents convergence
       to "always auto-approve" and ensures the model continues to see
       human decisions for ongoing calibration.

    5. Accuracy-based autonomy: if per-context posterior accuracy is
       available and meets the threshold (>= ACCURACY_AUTONOMY_THRESHOLD
       over >= ACCURACY_MIN_INTERACTIONS), the proxy has earned autonomy
       in this context — trust the agent's self-assessed confidence.
       If accuracy is below the threshold with sufficient data, cap
       confidence to force escalation.

    6. Otherwise, return the agent's self-assessed confidence unchanged.

    EMA is tracked separately as a system health monitor and does not
    influence the returned confidence.
    """
    from datetime import date

    depth = _get_memory_depth(proxy_model_path, team)
    if depth < MEMORY_DEPTH_THRESHOLD:
        return min(agent_confidence, 0.5)

    if genuine_tension:
        return min(agent_confidence, 0.5)

    # Staleness guard: force escalation if no human feedback recently.
    if accuracy:
        last_updated = accuracy.get('last_updated')
        if last_updated:
            try:
                last = date.fromisoformat(last_updated)
                days_stale = (date.today() - last).days
                if days_stale > STALENESS_DAYS:
                    _log.info(
                        'Staleness guard: %s|%s last updated %s (%d days ago, '
                        'threshold %d). Capping confidence.',
                        state, project_slug, last_updated,
                        days_stale, STALENESS_DAYS,
                    )
                    return min(agent_confidence, 0.5)
            except (ValueError, TypeError):
                pass

    # Exploration rate: randomly force escalation to maintain calibration.
    roll = _random if _random is not None else random.random()
    if roll < EXPLORATION_RATE:
        _log.info(
            'Exploration rate: randomly capping confidence for %s|%s '
            '(roll=%.3f < %.2f).',
            state, project_slug, roll, EXPLORATION_RATE,
        )
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
# Temporarily relaxed to 0 so the proxy can drive gates on fresh projects
# without the cold-start cap forcing every gate to escalate (which leads
# to rubber-stamping).  Other safeguards still run: genuine-tension,
# staleness, exploration-rate, and posterior-accuracy.  The rewrite in
# the next milestone will revisit the whole calibration stack.
MEMORY_DEPTH_THRESHOLD = 0

# Posterior accuracy threshold for earned autonomy: the proxy must correctly
# predict the human's action at least this fraction of the time.
ACCURACY_AUTONOMY_THRESHOLD = 0.85

# Minimum number of interactions before accuracy-based gating applies.
# Below this, accuracy data is too sparse to be meaningful.
ACCURACY_MIN_INTERACTIONS = 10

# Exploration rate: even when confidence is high, force escalation this
# fraction of the time to ensure the model continues to see human decisions.
EXPLORATION_RATE = 0.15

# Staleness guard: if the proxy hasn't received human feedback for a
# (state, task_type) pair in more than this many days, force escalation.
STALENESS_DAYS = 7


def _get_memory_depth(proxy_model_path: str, team: str) -> int:
    """Query the ACT-R memory store for experience diversity."""
    try:
        from teaparty.proxy.memory import (
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
    conflict_context: str = ''       # formatted conflict classifications for prompt injection (#228)
    has_genuine_tension: bool = False  # True if any conflict is genuine_tension (#228)
    llm_classifier_fallback_count: int = 0  # number of pairs that fell back to heuristic (#238)


_EMPTY_RETRIEVAL = _ActrRetrievalResult(serialized='', chunk_ids=[], db_path='', interaction_counter=0)


def _retrieve_actr_memories(
    *,
    proxy_model_path: str,
    team: str,
    state: str,
    task_type: str,
    question: str,
    artifact_path: str = '',
    scoring: str = 'multi_dim',
) -> _ActrRetrievalResult:
    """Retrieve ACT-R memory chunks for the current gate context.

    scoring='multi_dim' (default): Two queries (#227):
      - Experience retrieval: 4-dimension composite scoring
      - Salience retrieval: independent attention path
    scoring='single': Single blended embedding query (issue #222 ablation
      Config B). Salience retrieval is skipped — the blended embedding
      already incorporates salience information.

    Returns chunk IDs alongside the serialized text so the caller can
    reinforce after the proxy agent has consumed the memories.
    """
    try:
        from teaparty.proxy.memory import (
            open_proxy_db,
            resolve_memory_db_path,
            retrieve_chunks,
            retrieve_salience,
            serialize_chunks_for_prompt,
            get_interaction_counter,
            get_accuracy,
            blended_text_from_fields,
            find_conflicting_pairs,
            classify_conflict,
            format_conflict_context,
            has_genuine_tension as _has_genuine_tension,
        )
        from teaparty.learning.episodic.indexer import try_embed, detect_provider

        db_path = resolve_memory_db_path(proxy_model_path, team)
        if not os.path.isfile(db_path):
            return _EMPTY_RETRIEVAL

        conn = open_proxy_db(db_path)
        try:
            current = get_interaction_counter(conn)
            if current == 0:
                return _EMPTY_RETRIEVAL

            provider, model = detect_provider()
            salience_chunks: list = []

            if scoring == 'single':
                # Config B: single blended context embedding (issue #222)
                blended_str = blended_text_from_fields(
                    state=state, task_type=task_type,
                )
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
                # Config A: per-dimension experience retrieval (#227)
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

                # Salience retrieval (independent attention path, #227)
                artifact_text = ''
                if artifact_path and os.path.isfile(artifact_path):
                    try:
                        with open(artifact_path) as f:
                            artifact_text = f.read()[:2000]
                    except OSError:
                        pass
                salience_context = f'{state} {task_type}'
                if artifact_text:
                    salience_context = f'{artifact_text}\n\n{salience_context}'
                salience_query = try_embed(salience_context, conn=conn, provider=provider, model=model)
                if salience_query:
                    salience_chunks = retrieve_salience(
                        conn,
                        context_embedding=salience_query,
                        current_interaction=current,
                    )

            accuracy = get_accuracy(conn, state=state, task_type=task_type)
            all_chunk_ids = [c.id for c in chunks] + [c.id for c in salience_chunks]

            # Issue #228: Two-tier retrieval-time conflict detection.
            # Tier 1: heuristic pre-filter (cheap, no LLM call).
            # Tier 2: LLM classification on flagged pairs only.
            # Read-only on chunk list — annotates, never modifies.
            conflict_ctx = ''
            genuine_tension = False
            llm_fallback_count = 0
            all_chunks = chunks + salience_chunks
            pairs = find_conflicting_pairs(all_chunks)
            if pairs:
                # Tier 1 heuristic classification
                classifications = [
                    classify_conflict(a, b, current_interaction=current)
                    for a, b in pairs
                ]
                # Tier 2: LLM reclassification for ambiguous cases.
                # Only invoke LLM when heuristic returns context_sensitivity
                # (the ambiguous default) and chunks have content to analyze.
                for i, (cls, (a, b)) in enumerate(zip(classifications, pairs)):
                    if cls.cause == 'context_sensitivity' and a.content and b.content:
                        try:
                            llm_cause = _classify_conflict_llm(a, b)
                        except Exception:
                            _log.warning('LLM conflict classification failed for pair %s/%s',
                                         a.id[:8], b.id[:8], exc_info=True)
                            llm_cause = None
                        if llm_cause is None:
                            llm_fallback_count += 1
                        elif llm_cause != 'context_sensitivity':
                            from teaparty.proxy.memory import ConflictClassification
                            _ACTIONS = {
                                'preference_drift': f'Prefer newer memory; schedule older for demotion.',
                                'genuine_tension': 'Escalate to human — unresolved tension in preferences.',
                                'retrieval_noise': 'Discard the weaker match.',
                            }
                            classifications[i] = ConflictClassification(
                                chunk_a_id=a.id, chunk_b_id=b.id,
                                cause=llm_cause,
                                action=_ACTIONS.get(llm_cause, cls.action),
                            )

                conflict_ctx = format_conflict_context(
                    classifications, llm_fallback_count=llm_fallback_count,
                )
                genuine_tension = _has_genuine_tension(classifications)

            return _ActrRetrievalResult(
                serialized=serialize_chunks_for_prompt(
                    chunks,
                    salience_chunks=salience_chunks or None,
                ),
                chunk_ids=all_chunk_ids,
                db_path=db_path,
                interaction_counter=current,
                accuracy=accuracy,
                conflict_context=conflict_ctx,
                has_genuine_tension=genuine_tension,
                llm_classifier_fallback_count=llm_fallback_count,
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


# Per-type budget cap for task learnings retrieved for the proxy.
_PROXY_TASK_LEARNING_BUDGET = 2000


def _retrieve_task_learnings(
    *,
    proxy_model_path: str,
    question: str,
    infra_dir: str,
) -> str:
    """Retrieve relevant task learnings from the learning system.

    Calls memory_indexer.retrieve() with learning_type='task' to get
    organizational task knowledge, and learning_type='proxy' to get
    proxy-specific task learnings from proxy-tasks/.
    """
    from teaparty.learning.episodic.indexer import retrieve

    model_dir = os.path.dirname(proxy_model_path)
    project_dir = model_dir  # model lives in the project dir

    # Gather source paths for retrieval
    source_paths = []
    tasks_dir = os.path.join(project_dir, 'tasks')
    if os.path.isdir(tasks_dir):
        source_paths.append(tasks_dir)
    proxy_tasks_dir = os.path.join(project_dir, 'proxy-tasks')
    if os.path.isdir(proxy_tasks_dir):
        source_paths.append(proxy_tasks_dir)

    if not source_paths:
        return ''

    db_path = os.path.join(project_dir, '.memory.db')

    # Retrieve task learnings with a budget cap
    result = retrieve(
        task=question,
        db_path=db_path,
        source_paths=source_paths,
        top_k=5,
        scope_base_dir=project_dir,
        learning_type=None,  # retrieve both task and proxy types
        max_chars=_PROXY_TASK_LEARNING_BUDGET,
    )
    return result


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
        from teaparty.proxy.memory import (
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
    prior_confidence: float = 0.0
    prior_text: str = ''
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
    task_learnings: str = '',
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

    task_learning_block = ''
    if task_learnings:
        task_learning_block = (
            f'\n--- ORGANIZATIONAL TASK LEARNINGS ---\n'
            f'These are learnings from the broader organization that may be '
            f'relevant to your evaluation:\n'
            f'{task_learnings}\n'
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

    # Gate-specific instruction — varies by CfA state.
    # INTENT_ASSERT: the proxy must probe before approving; rubber-stamping is wrong.
    # The instruction is dialog-aware: probe required only if no prior probe in
    # this review, otherwise evaluate whether the answer resolves the concern.
    gate_instruction = ''
    if state == 'INTENT_ASSERT':
        if dialog_history.strip():
            gate_instruction = (
                f'\nYou have already been in dialog about this intent (see '
                f'DIALOG SO FAR). Evaluate whether the agent\'s reply resolves '
                f'your concern. If it does, approve. If it raises a new '
                f'concrete concern, ask one more focused question. Do not '
                f'probe indefinitely — once your questions are answered, '
                f'approve.\n'
            )
        else:
            gate_instruction = (
                f'\nYou are being asked whether the stated intent accurately '
                f'and completely reflects what was requested. Before indicating '
                f'approval, probe with one specific question that targets a '
                f'concrete claim or framing choice in the proposal — scope, '
                f'assumptions, or anything that seems underspecified. '
                f'Do not rubber-stamp.\n'
            )

    # ── Pass 1: Prior (without artifact) ─────────────────────────────────
    prior_prompt = (
        f"You are standing in for a human at a CfA workflow approval gate. "
        f"Your job is to respond as that human would — in their voice, "
        f"directly and without jargon. You have NOT yet seen the artifact.\n\n"
        f"{memory_block}"
        f"{accuracy_block}"
        f"{learning_block}"
        f"{task_learning_block}"
        f"{dialog_block}\n"
        f"State: {state}\n"
        f"Question: {question}\n\n"
        f"{gate_instruction}\n"
        f"Based on what you know about how this human works, write 2-4 sentences "
        f"responding to this question the way the human would. Be direct and "
        f"specific. Do not return a structured verdict — write natural text "
        f"as the human would say it.\n\n"
        f"On the final line, write only:\n"
        f"CONFIDENCE: <float 0.0–1.0>"
    )

    prior_text, prior_confidence = await _invoke_claude_proxy(
        prior_prompt, session_worktree,
    )

    # Fast-fail: if Pass 1 returned nothing, the CLI is degraded.
    # Skip Pass 2 and surprise extraction to bound worst-case latency.
    if not prior_text:
        return _TwoPassResult()

    # ── Pass 2: Posterior (with artifact + prior) ────────────────────────
    prior_block = (
        f'\nYour initial reaction (before reading the artifact):\n'
        f'{prior_text[:500]}\n'
    )

    posterior_prompt = (
        f"You are standing in for a human at a CfA workflow approval gate. "
        f"Your job is to respond as that human would — in their voice, "
        f"directly and without jargon. You have now read the artifact.\n\n"
        f"{memory_block}"
        f"{accuracy_block}"
        f"{learning_block}"
        f"{task_learning_block}"
        f"{dialog_block}\n"
        f"State: {state}\n"
        f"Question: {question}\n\n"
        f"{prior_block}\n"
        f"Now read the artifact and any upstream context files. Revise your "
        f"response based on what you find.\n\n"
        f"{context_block}\n\n"
        f"{gate_instruction}\n"
        f"Respond as the human would. If your reaction has changed after reading "
        f"the artifact, say what changed and why. Write natural text — not a "
        f"structured verdict.\n\n"
        f"On the final line, write only:\n"
        f"CONFIDENCE: <float 0.0–1.0>"
    )

    post_text, post_confidence = await _invoke_claude_proxy(
        posterior_prompt, session_worktree,
    )

    # Fast-fail: if Pass 2 returned nothing, fall back to the prior result.
    # Skip surprise extraction to avoid a third CLI call on a degraded CLI.
    if not post_text:
        return _TwoPassResult(
            text=prior_text,
            confidence=prior_confidence,
            prior_confidence=prior_confidence,
            prior_text=prior_text,
        )

    # ── Surprise detection ───────────────────────────────────────────────
    # Sole trigger: confidence shifted substantially between passes.  The
    # pre-583cccd8 design also triggered on categorical action change, but
    # the conversational-prompts migration replaced structured verdicts
    # with natural text — action classification now happens downstream via
    # _classify_review on the final response, not per-pass here.
    prediction_delta = ''
    salient_percepts: list[str] = []
    confidence_shifted = abs(post_confidence - prior_confidence) > 0.3

    if confidence_shifted:
        prediction_delta, salient_percepts = await _extract_surprise(
            prior_confidence, prior_text,
            post_confidence, post_text,
            artifact_path, session_worktree,
        )

    return _TwoPassResult(
        text=post_text or prior_text,
        confidence=post_confidence if post_text else prior_confidence,
        prior_confidence=prior_confidence,
        prior_text=prior_text,
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

    # PROMPT.txt is the initial seed — the user's first-turn wording.
    # INTENT.md may have been refined since, and IS the authoritative spec
    # at PLAN_ASSERT / WORK_ASSERT.  Label accordingly so the proxy doesn't
    # treat a stale PROMPT as ground truth and flag approved refinements as
    # "over-scoped" contradictions.
    if infra_dir:
        prompt_path = os.path.join(infra_dir, 'PROMPT.txt')
        if os.path.isfile(prompt_path):
            if state in ('INTENT_ASSERT', 'INTENT_ESCALATE'):
                # Intent is being built from PROMPT — it's authoritative here.
                context_parts.append(
                    f'Original request (the user\'s exact words — INTENT.md '
                    f'must accurately capture this): {prompt_path}'
                )
            else:
                # Post-intent phases: INTENT.md supersedes PROMPT.txt.
                context_parts.append(
                    f'Initial seed (the user\'s first-turn wording; may have '
                    f'been refined since — see INTENT.md for the current '
                    f'authoritative spec): {prompt_path}'
                )

    if artifact_path and os.path.isfile(artifact_path):
        context_parts.append(f'Artifact under review: {artifact_path}')

    if state in ('PLAN_ASSERT', 'WORK_ASSERT'):
        for name in ('INTENT.md',):
            for search_dir in (session_worktree, infra_dir):
                if not search_dir:
                    continue
                path = os.path.join(search_dir, name)
                if os.path.isfile(path):
                    context_parts.append(
                        f'Authoritative spec (approved intent — this is '
                        f'what the artifact must fulfill): {path}'
                    )
                    break
    if state == 'WORK_ASSERT':
        for name in ('PLAN.md', 'WORK_SUMMARY.md'):
            for search_dir in (session_worktree, infra_dir):
                if not search_dir:
                    continue
                path = os.path.join(search_dir, name)
                if os.path.isfile(path):
                    context_parts.append(f'Upstream context: {path}')
                    break

    return context_parts


async def _invoke_claude_proxy(
    prompt: str, session_worktree: str,
) -> tuple[str, float]:
    """Invoke claude -p and parse output. Returns (text, confidence)."""
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
        return ('', 0.0)

    if result.returncode != 0 or not result.stdout.strip():
        _log.warning('Proxy agent returned non-zero or empty output')
        return ('', 0.0)

    output = result.stdout.strip()
    return parse_proxy_agent_output(output)


async def _extract_surprise(
    prior_confidence: float, prior_text: str,
    post_confidence: float, post_text: str,
    artifact_path: str, session_worktree: str,
) -> tuple[str, list[str]]:
    """Extract surprise description and salient percepts when confidence shifts."""
    prompt = (
        f"The proxy's confidence shifted substantially after reading the artifact.\n\n"
        f"Prior confidence: {prior_confidence:.2f}\n"
        f"Posterior confidence: {post_confidence:.2f}\n\n"
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


# ── LLM-based conflict classification (issue #228) ──────────────────────────

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


