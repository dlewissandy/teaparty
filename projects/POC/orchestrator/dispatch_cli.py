"""CLI dispatch entry point for liaison agents.

Usage (from within a Claude agent session):
    python3 -m projects.POC.orchestrator.dispatch_cli --team art --task "..."

Runs a child orchestrator in a dispatch worktree, merges results back,
and outputs a JSON status summary.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from projects.POC.orchestrator.engine import Orchestrator
from projects.POC.orchestrator.events import EventBus, EventType, InputRequest
from projects.POC.orchestrator.merge import git_output, squash_merge
from projects.POC.scripts.generate_commit_message import generate_async, build_fallback
from projects.POC.orchestrator.phase_config import PhaseConfig
from projects.POC.orchestrator.worktree import (
    create_dispatch_worktree,
    cleanup_worktree,
)
from projects.POC.scripts.cfa_state import (
    make_child_state,
    load_state,
    save_state,
)


class _NoInputProvider:
    """Auto-approves everything — dispatch subteams don't interact with humans."""

    async def __call__(self, request: InputRequest) -> str:
        return 'approve'


def _find_poc_root() -> str:
    d = os.path.dirname(os.path.abspath(__file__))
    while d != '/':
        if os.path.exists(os.path.join(d, 'cfa-state-machine.json')):
            return d
        d = os.path.dirname(d)
    return os.path.dirname(os.path.abspath(__file__))


async def dispatch(team: str, task: str, auto_approve_plan: bool = False, cfa_parent_state: str = '') -> dict:
    """Run a dispatch and return a status dict."""
    poc_root = _find_poc_root()
    config = PhaseConfig(poc_root)

    # Read parent session context from environment
    session_worktree = os.environ.get('POC_SESSION_WORKTREE', os.getcwd())
    infra_dir = os.environ.get('POC_SESSION_DIR', '')
    project_slug = os.environ.get('POC_PROJECT', 'default')

    if not infra_dir:
        return {'status': 'failed', 'reason': 'POC_SESSION_DIR not set'}

    # Load parent CfA state for child linkage
    parent_state_path = (
        cfa_parent_state
        or os.environ.get('POC_CFA_STATE', '')
        or os.path.join(infra_dir, '.cfa-state.json')
    )
    if not os.path.exists(parent_state_path):
        return {'status': 'failed', 'reason': f'parent CfA state not found: {parent_state_path}'}
    parent_cfa = load_state(parent_state_path)

    # Create dispatch worktree
    try:
        dispatch_info = await create_dispatch_worktree(
            team=team,
            task=task,
            session_worktree=session_worktree,
            infra_dir=infra_dir,
        )
    except Exception as e:
        return {'status': 'failed', 'reason': f'worktree creation failed: {e}'}

    worktree_path = dispatch_info['worktree_path']
    dispatch_infra = dispatch_info['infra_dir']

    # Initialize CfA state for the child — use make_child_state for correct parent linkage
    cfa = make_child_state(
        parent_cfa, team,
        task_id=f'dispatch-{team}-{dispatch_info["dispatch_id"]}',
    )
    save_state(cfa, os.path.join(dispatch_infra, '.cfa-state.json'))

    # Run child orchestrator
    event_bus = EventBus()
    input_provider = _NoInputProvider()

    orchestrator = Orchestrator(
        cfa_state=cfa,
        phase_config=config,
        event_bus=event_bus,
        input_provider=input_provider,
        infra_dir=dispatch_infra,
        project_workdir=worktree_path,
        session_worktree=worktree_path,
        proxy_model_path=os.path.join(
            os.path.dirname(infra_dir), f'.proxy-confidence-{team}.json'
        ),
        project_slug=project_slug,
        poc_root=poc_root,
        task=task,
        session_id=dispatch_info['dispatch_id'],
        skip_intent=True,
        team_override=team,
    )

    retries = 0
    max_retries = config.max_dispatch_retries
    result = None

    while retries <= max_retries:
        result = await orchestrator.run()
        if result.terminal_state in ('COMPLETED_WORK', 'WITHDRAWN'):
            break
        if result.escalation_type:  # escalation — don't retry, surface it
            break
        retries += 1

    # Merge back into parent session worktree
    if result and result.terminal_state == 'COMPLETED_WORK':
        try:
            # Generate a rich commit message from the dispatch work
            dispatch_log = await git_output(worktree_path, 'log', '--oneline')
            changed_files = await git_output(
                worktree_path, 'diff', '--name-only', 'HEAD',
            )
            message = await generate_async(
                task, team, dispatch_log, changed_files,
            )
            if not message:
                message = build_fallback(team, task)

            await squash_merge(
                source=worktree_path,
                target=session_worktree,
                message=message,
            )
        except Exception:
            pass

    # Clean up
    await cleanup_worktree(worktree_path)

    # Remove .running sentinel
    running_path = os.path.join(dispatch_infra, '.running')
    try:
        os.unlink(running_path)
    except FileNotFoundError:
        pass

    # Return JSON status
    status = 'completed' if result and result.terminal_state == 'COMPLETED_WORK' else 'failed'
    escalation_type = result.escalation_type if result else ''
    exit_reason = 'completed' if status == 'completed' else (
        f'{escalation_type}_escalation' if escalation_type else 'failed'
    )
    return {
        'status': status,
        'exit_reason': exit_reason,
        'team': team,
        'task': task,
        'terminal_state': result.terminal_state if result else 'unknown',
        'backtrack_count': result.backtrack_count if result else 0,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description='Dispatch work to a subteam')
    parser.add_argument('--team', required=True, help='Team name (art, writing, etc.)')
    parser.add_argument('--task', required=True, help='Task description')
    parser.add_argument('--auto-approve-plan', action='store_true',
                        help='Skip proxy check for plan approval')
    parser.add_argument('--cfa-parent-state', default='',
                        help='Path to parent CfA state JSON (falls back to POC_CFA_STATE env)')
    args = parser.parse_args()

    result = await dispatch(args.team, args.task, args.auto_approve_plan, args.cfa_parent_state)
    print(json.dumps(result, indent=2))
    exit_codes = {'completed': 0, 'plan_escalation': 10, 'work_escalation': 11}
    return exit_codes.get(result.get('exit_reason', 'failed'), 1)


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
