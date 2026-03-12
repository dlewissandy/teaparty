"""Post-session learning extraction.

Extracts observations, escalations, and intent-alignment learnings
from session streams and archives them to the project memory stores.

Replaces the learnings block in run.sh and the promote_learnings.sh calls.
"""
from __future__ import annotations

import os
import subprocess


async def extract_learnings(
    *,
    infra_dir: str,
    project_dir: str,
    session_worktree: str,
    task: str,
    poc_root: str,
) -> None:
    """Run the full learning extraction pipeline for a completed session."""
    scripts_dir = os.path.join(poc_root, 'scripts')

    # Extract observations → proxy.md
    _run_summarize(
        scripts_dir, infra_dir,
        scope='observations',
        output=os.path.join(project_dir, 'proxy.md'),
        task=task,
    )

    # Extract escalation → proxy-tasks/
    _run_summarize(
        scripts_dir, infra_dir,
        scope='escalation',
        output=os.path.join(project_dir, 'proxy-tasks'),
        task=task,
    )

    # Extract intent-alignment → tasks/
    _run_summarize(
        scripts_dir, infra_dir,
        scope='intent-alignment',
        output=os.path.join(project_dir, 'tasks'),
        task=task,
    )


def _run_summarize(
    scripts_dir: str,
    infra_dir: str,
    scope: str,
    output: str,
    task: str,
) -> None:
    """Run summarize_session.py for a specific scope."""
    script = os.path.join(scripts_dir, 'summarize_session.py')
    if not os.path.exists(script):
        return

    # Find stream files
    streams = []
    for name in ('.intent-stream.jsonl', '.plan-stream.jsonl', '.exec-stream.jsonl'):
        path = os.path.join(infra_dir, name)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            streams.append(path)

    if not streams:
        return

    args = [
        'python3', script,
        '--scope', scope,
        '--output', output,
        '--task', task,
    ]
    for s in streams:
        args.extend(['--stream', s])

    try:
        subprocess.run(
            args, capture_output=True, text=True, timeout=60,
        )
    except Exception:
        pass
