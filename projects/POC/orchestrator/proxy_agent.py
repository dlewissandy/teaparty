"""Proxy agent — a Claude agent that stands in for the human.

Every time the system needs the human's input — whether it's an approval gate,
an agent escalation, or a clarifying question — it goes through the same path:

  1. Gather context: learned patterns, similar past interactions
  2. Invoke the proxy agent (Claude CLI with tools)
  3. Agent generates text + self-assessed confidence
  4. Statistical calibration adjusts confidence based on historical accuracy
  5. If confident → agent's text IS the answer
  6. If not confident → same question goes to the human
  7. Both predicted text and actual text feed into learning

The proxy agent always runs.  Statistics never gate whether the agent is
consulted — they calibrate confidence after the agent has spoken.

The proxy agent has file-read tools, receives learned behavioral patterns and
past interaction history, and can engage in multi-turn dialog with the requester
before deciding.

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
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger('orchestrator.proxy_agent')


@dataclass
class ProxyResult:
    """The proxy agent's output."""
    text: str                   # Full text response (what the human would say)
    confidence: float           # 0.0–1.0: how confident the agent is this matches the human
    from_agent: bool = True     # True if agent generated this, False if stats escalated


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
        COLD_START_THRESHOLD,
        load_model,
        resolve_team_model_path,
        retrieve_similar_interactions,
        compute_confidence_components,
        _entry_key,
        _make_entry,
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

        # Tier 2: retrieve similar past interactions
        log_path = os.path.join(project_dir, '.proxy-interactions.jsonl')
        similar = retrieve_similar_interactions(
            log_path=log_path, state=state, project=project_slug, top_k=5,
        )
    except Exception:
        _log.debug('Failed to load learning context', exc_info=True)

    # Always invoke the proxy agent.
    try:
        text, agent_confidence = await run_proxy_agent(
            question=question,
            state=state,
            artifact_path=artifact_path,
            session_worktree=session_worktree,
            infra_dir=infra_dir,
            learned_patterns=learned_patterns,
            similar_interactions=similar,
            dialog_history=dialog_history,
        )
    except Exception:
        _log.debug('Exception invoking proxy agent', exc_info=True)
        return ProxyResult(text='', confidence=0.0, from_agent=False)

    if not text:
        return ProxyResult(text='', confidence=0.0, from_agent=True)

    # Statistical calibration: adjust the agent's self-assessed confidence
    # based on historical accuracy at this gate.  The agent always speaks;
    # statistics only modulate how much the caller trusts the response.
    confidence = _calibrate_confidence(
        agent_confidence, state, project_slug, proxy_model_path, team,
    )

    return ProxyResult(text=text, confidence=confidence, from_agent=True)


def _calibrate_confidence(
    agent_confidence: float,
    state: str,
    project_slug: str,
    proxy_model_path: str,
    team: str,
) -> float:
    """Adjust agent confidence using statistical history.

    The agent's self-assessed confidence is the starting point.  Historical
    data can only reduce it — never inflate it above what the agent claimed.

    - Cold start (< COLD_START_THRESHOLD samples): cap at 0.5 so the caller
      knows there's no track record yet.
    - With history: take the minimum of the agent's confidence and the
      statistical confidence (Laplace/EMA).  If the model has been wrong
      before at this gate, the calibrated score reflects that.
    """
    from projects.POC.scripts.approval_gate import (
        COLD_START_THRESHOLD,
        ConfidenceEntry,
        compute_confidence_components,
        load_model,
        resolve_team_model_path,
        _entry_key,
        _make_entry,
    )

    try:
        model_path = resolve_team_model_path(proxy_model_path, team)
        model = load_model(model_path)
    except Exception:
        # No model at all — cap at cold-start level.
        return min(agent_confidence, 0.5)

    key = _entry_key(state, project_slug)
    raw = model.entries.get(key)

    if raw is None:
        entry = _make_entry(state, project_slug)
    elif isinstance(raw, dict):
        # Backward compat
        for field, default in [
            ('differentials', []), ('ema_approval_rate', 0.5),
            ('artifact_lengths', []), ('question_patterns', []),
            ('prediction_correct_count', 0), ('prediction_total_count', 0),
        ]:
            if field not in raw:
                raw[field] = default
        entry = ConfidenceEntry(**raw)
    else:
        entry = raw

    # Cold start — not enough history to trust the agent's self-assessment.
    if entry.total_count < COLD_START_THRESHOLD:
        return min(agent_confidence, 0.5)

    # Enough history — use statistical confidence as a ceiling.
    laplace, ema = compute_confidence_components(entry)
    stats_confidence = min(laplace, ema)
    return min(agent_confidence, stats_confidence)


async def run_proxy_agent(
    question: str,
    *,
    state: str = '',
    artifact_path: str = '',
    session_worktree: str = '',
    infra_dir: str = '',
    learned_patterns: str = '',
    similar_interactions: list | None = None,
    dialog_history: str = '',
) -> tuple[str, float]:
    """Invoke a Claude agent as the human proxy.

    The agent reads the artifact under review and generates a full text
    response — what it predicts the human would say.  Returns (text,
    confidence) where confidence is the agent's self-assessed certainty.

    The agent has file-read tools, receives learned patterns and past
    interactions, and can be called in a dialog loop (with dialog_history
    from prior turns).
    """
    # Build context: artifact and upstream context paths
    context_parts = []

    if artifact_path and os.path.isfile(artifact_path):
        context_parts.append(f'Artifact under review: {artifact_path}')

    # Upstream context — INTENT.md for PLAN_ASSERT and TASK_ASSERT,
    # INTENT.md + PLAN.md for WORK_ASSERT and TASK_ASSERT.
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

    context_block = '\n'.join(context_parts) if context_parts else ''

    # Build learning context
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

    prompt = (
        f"You are a human proxy agent. You stand in for the human at a CfA "
        f"approval gate. Your job is to predict what the human would say.\n\n"
        f"Question: {question}\n\n"
        f"{context_block}\n"
        f"{learning_block}"
        f"{dialog_block}\n"
        f"Read the artifact and any upstream context files, then respond "
        f"exactly as the human would. Your response should be natural text "
        f"— it may be approval, a question, a correction, or a concern. "
        f"You may ask clarifying questions before deciding. "
        f"Use the learned patterns and past interactions to inform your "
        f"prediction of what the human would say.\n\n"
        f"After your response, on a FINAL line by itself, write your "
        f"confidence that the human would say essentially the same thing, "
        f"as a decimal between 0.0 and 1.0.\n"
        f"Format exactly: CONFIDENCE: 0.85"
    )

    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                ['claude', '-p', '--output-format', 'text',
                 '--allowedTools', 'Read,Glob,Grep,Bash',
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
