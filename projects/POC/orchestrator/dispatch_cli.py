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
import random
import sys

from projects.POC.orchestrator import find_poc_root
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


def _attach_event_writer(event_bus: EventBus, infra_dir: str) -> None:
    """Attach a simple JSONL event writer to the child's EventBus.

    Writes all events to events.jsonl in the child's infra_dir so the
    parent's EventCollector can merge them post-hoc for experiment analysis.
    """
    import time as _time
    events_path = os.path.join(infra_dir, 'events.jsonl')

    async def _write_event(event) -> None:
        record = {
            'timestamp': getattr(event, 'timestamp', None) or _time.time(),
            'type': event.type.value if hasattr(event.type, 'value') else str(event.type),
            'session_id': getattr(event, 'session_id', ''),
            'source': os.path.basename(infra_dir),
            **getattr(event, 'data', {}),
        }
        try:
            with open(events_path, 'a') as f:
                f.write(json.dumps(record, default=str) + '\n')
        except OSError:
            pass

    event_bus.subscribe(_write_event)


def _write_dispatch_memory(dispatch_infra: str, team: str, task: str, result) -> None:
    """Write a MEMORY.md summarizing the dispatch for the rollup chain.

    promote('team') reads dispatch MEMORY.md files as context when rolling up
    learnings into team-level institutional.md and tasks/ files.
    """
    from datetime import date
    memory_path = os.path.join(dispatch_infra, 'MEMORY.md')
    today = date.today().isoformat()
    content = (
        f"## [{today}] Dispatch: {team}\n"
        f"**Task:** {task}\n"
        f"**Result:** {result.terminal_state}\n"
        f"**Backtracks:** {result.backtrack_count}\n"
    )
    try:
        with open(memory_path, 'w') as f:
            f.write(content)
    except OSError:
        pass


async def dispatch(
    team: str,
    task: str,
    auto_approve_plan: bool = False,
    cfa_parent_state: str = '',
    session_worktree: str = '',
    infra_dir: str = '',
    project_slug: str = '',
) -> dict:
    """Run a dispatch and return a status dict.

    Args:
        team: The team name to dispatch to (art, writing, etc.).
        task: The task description.
        auto_approve_plan: Skip proxy check for plan approval.
        cfa_parent_state: Path to parent CfA state JSON.
        session_worktree: Parent session worktree path.  Falls back to
            the POC_SESSION_WORKTREE env var, then os.getcwd().
        infra_dir: Parent session infra directory.  Falls back to
            the POC_SESSION_DIR env var.
        project_slug: Project identifier.  Falls back to POC_PROJECT env var.
    """
    poc_root = find_poc_root()
    config = PhaseConfig(poc_root)

    # Resolve session context — explicit parameters take precedence over env vars
    if not session_worktree:
        session_worktree = os.environ.get('POC_SESSION_WORKTREE', os.getcwd())
    if not infra_dir:
        infra_dir = os.environ.get('POC_SESSION_DIR', '')
    if not project_slug:
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

    # Run child orchestrator with event collection for experiment visibility.
    # Events are written to events.jsonl in the dispatch infra_dir so the
    # parent's EventCollector can merge them post-hoc (issue #133).
    event_bus = EventBus()
    _attach_event_writer(event_bus, dispatch_infra)

    # The input_provider is a placeholder — never_escalate=True means the
    # proxy always answers and this is never called.  But it must be truthy
    # so engine.run() starts the MCP listeners (AskQuestion for the subteam).
    async def _unreachable_input(request):
        raise RuntimeError('never_escalate=True but input_provider was called')

    orchestrator = Orchestrator(
        cfa_state=cfa,
        phase_config=config,
        event_bus=event_bus,
        input_provider=_unreachable_input,
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
        never_escalate=True,
        team_override=team,
    )

    retries = 0
    max_retries = config.max_dispatch_retries
    result = None
    api_overloaded = False

    while retries <= max_retries:
        result = await orchestrator.run()
        if result.terminal_state in ('COMPLETED_WORK', 'WITHDRAWN'):
            break
        if result.escalation_type:  # escalation — don't retry, surface it
            break

        # Detect 529 exhaustion: the child orchestrator returned non-terminal
        # after exhausting its own overload retries.  Check sentinel file.
        overload_sentinel = os.path.join(dispatch_infra, '.api-overloaded')
        if os.path.exists(overload_sentinel):
            api_overloaded = True
            # Add jitter to prevent dispatch stampede on recovery.
            # Random 30-120s prevents all subteams from retrying simultaneously.
            jitter = random.uniform(30, 120)
            await asyncio.sleep(jitter)

        retries += 1

    # Merge back into parent session worktree
    merge_failed = False
    merge_error = ''
    if result and result.terminal_state == 'COMPLETED_WORK':
        # Generate commit message — failures fall back to a static message
        # so they never prevent the merge from being attempted.
        try:
            dispatch_log = await git_output(worktree_path, 'log', '--oneline')
            changed_files = await git_output(
                worktree_path, 'diff', '--name-only', 'HEAD',
            )
            message = await generate_async(
                task, team, dispatch_log, changed_files,
            )
            if not message:
                message = build_fallback(team, task)
        except Exception:
            message = build_fallback(team, task)

        # Merge — failures must surface, never be silently swallowed.
        try:
            await squash_merge(
                source=worktree_path,
                target=session_worktree,
                message=message,
            )
        except Exception as e:
            merge_failed = True
            merge_error = str(e)

    # Write dispatch MEMORY.md for the rollup chain — only if merge succeeded.
    # A failed merge means deliverables didn't land; writing memory would give
    # the rollup chain a phantom "completed" record with no artifacts.
    if result and result.terminal_state == 'COMPLETED_WORK' and not merge_failed:
        _write_dispatch_memory(dispatch_infra, team, task, result)

    # Clean up
    await cleanup_worktree(worktree_path)

    # Finalize heartbeat with terminal status (issue #149)
    from projects.POC.orchestrator.heartbeat import finalize_heartbeat
    hb_path = os.path.join(dispatch_infra, '.heartbeat')
    hb_status = 'completed' if (result and result.terminal_state == 'COMPLETED_WORK' and not merge_failed) else 'withdrawn'
    try:
        finalize_heartbeat(hb_path, hb_status)
    except FileNotFoundError:
        pass

    # Build deliverables summary from changed files in the worktree.
    # Skip if merge failed — no commit landed, so diff would show stale data.
    deliverables = ''
    if not merge_failed:
        try:
            changed = await git_output(
                session_worktree, 'diff', '--name-only', 'HEAD~1', 'HEAD',
            )
            if changed.strip():
                deliverables = changed.strip()
        except Exception:
            pass

    # Return JSON status with deliverables summary and escalation context.
    # A successful orchestrator run that fails to merge is still a failure —
    # the parent agent must know that deliverables did not land.
    if merge_failed:
        status = 'failed'
    elif result and result.terminal_state == 'COMPLETED_WORK':
        status = 'completed'
    else:
        status = 'failed'
    escalation_type = result.escalation_type if result else ''
    if merge_failed:
        exit_reason = 'merge_failed'
    elif status == 'completed':
        exit_reason = 'completed'
    else:
        exit_reason = f'{escalation_type}_escalation' if escalation_type else 'failed'
    result_dict = {
        'status': status,
        'exit_reason': exit_reason,
        'team': team,
        'task': task,
        'terminal_state': result.terminal_state if result else 'unknown',
        'backtrack_count': result.backtrack_count if result else 0,
        'deliverables': deliverables,
        'escalation_type': escalation_type,
        'api_overloaded': api_overloaded,
    }
    if merge_failed:
        result_dict['reason'] = f'merge failed: {merge_error}'
    return result_dict


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
