"""Proxy agent — a Claude agent that stands in for the human.

Every time the system needs the human's input — whether it's an approval gate,
an agent escalation, or a clarifying question — it goes through the same path:

  1. Statistical pre-filters (cold start, staleness, low confidence, exploration)
  2. If stats say escalate → skip agent, go straight to human
  3. If stats pass → invoke the proxy agent (Claude CLI with tools)
  4. Agent generates text + confidence
  5. If confident → agent's text IS the answer
  6. If not confident → same question goes to the human
  7. Both predicted text and actual text feed into learning

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
) -> ProxyResult:
    """Consult the proxy agent.  The ONE entry point for all proxy decisions.

    Runs the statistical pre-filters first.  If they pass, invokes the proxy
    agent (Claude CLI with tools).  Returns a ProxyResult with the agent's
    text and confidence.

    The caller decides what to do based on confidence:
    - confidence >= threshold → use the text
    - confidence < threshold → ask the human
    """
    # Proxy disabled — skip agent, go straight to human.
    if not proxy_enabled:
        return ProxyResult(text='', confidence=0.0, from_agent=False)

    from projects.POC.scripts.approval_gate import (
        ProxyDecision,
        load_model,
        resolve_team_model_path,
        retrieve_similar_interactions,
        should_escalate,
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

    try:
        model_path = resolve_team_model_path(proxy_model_path, team)
        model = load_model(model_path)

        # Tier 1: read flat behavioral patterns
        project_dir = os.path.dirname(model_path)
        patterns_path = os.path.join(project_dir, 'proxy-patterns.md')
        learned_patterns = ''
        if os.path.isfile(patterns_path):
            try:
                with open(patterns_path) as _f:
                    learned_patterns = _f.read()
            except OSError:
                pass

        # Tier 2: retrieve similar past interactions
        log_path = os.path.join(project_dir, '.proxy-interactions.jsonl')
        similar = retrieve_similar_interactions(
            log_path=log_path, state=state, project=project_slug, top_k=5,
        )

        stats_decision = should_escalate(
            model, state, project_slug, artifact_path,
            similar_interactions=similar,
            tier1_patterns=learned_patterns,
        )

        # If the statistical model says escalate, respect it — no agent needed.
        if stats_decision.action != 'auto-approve':
            return ProxyResult(text='', confidence=0.0, from_agent=False)

        # Stats passed — invoke the proxy agent.
        text, confidence = await run_proxy_agent(
            question=question,
            state=state,
            artifact_path=artifact_path,
            session_worktree=session_worktree,
            infra_dir=infra_dir,
            learned_patterns=learned_patterns,
            similar_interactions=similar,
        )

        return ProxyResult(text=text, confidence=confidence, from_agent=True)

    except Exception:
        _log.debug('Exception in proxy consultation', exc_info=True)
        return ProxyResult(text='', confidence=0.0, from_agent=False)


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

    # Upstream context — INTENT.md for PLAN_ASSERT, both for WORK_ASSERT
    if state in ('PLAN_ASSERT', 'WORK_ASSERT'):
        for name in ('INTENT.md',):
            for search_dir in (infra_dir, session_worktree):
                if not search_dir:
                    continue
                path = os.path.join(search_dir, name)
                if os.path.isfile(path):
                    context_parts.append(f'Upstream context: {path}')
                    break
    if state == 'WORK_ASSERT':
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
