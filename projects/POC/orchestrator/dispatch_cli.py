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
    resume_worktree: str = '',
    resume_infra: str = '',
    liaison_task_id: str = '',
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
        resume_worktree: Existing worktree to resume (issue #149).  Skips
            worktree creation and loads CfA state from existing .cfa-state.json.
        resume_infra: Existing infra dir for resumed dispatch (issue #149).
    """
    poc_root = find_poc_root()

    # Resolve session context — explicit parameters take precedence over env vars
    if not session_worktree:
        session_worktree = os.environ.get('POC_SESSION_WORKTREE', os.getcwd())
    if not infra_dir:
        infra_dir = os.environ.get('POC_SESSION_DIR', '')
    if not project_slug:
        project_slug = os.environ.get('POC_PROJECT', 'default')

    # Resolve project_dir for project-scoped team config (issue #10)
    project_dir = os.environ.get('POC_PROJECT_DIR', '')
    config = PhaseConfig(poc_root, project_dir=project_dir or None)

    if not infra_dir and not resume_infra:
        return {'status': 'failed', 'reason': 'POC_SESSION_DIR not set'}

    # Resolve execution model from team config (issue #240).
    # "direct" teams run in the session worktree without child worktree isolation.
    team_spec = config.teams.get(team)
    direct_model = team_spec and team_spec.execution_model == 'direct'

    # Load parent CfA state for child linkage (skip on resume — we use existing child state)
    parent_cfa = None
    if not resume_worktree:
        parent_state_path = (
            cfa_parent_state
            or os.environ.get('POC_CFA_STATE', '')
            or os.path.join(infra_dir, '.cfa-state.json')
        )
        if not os.path.exists(parent_state_path):
            return {'status': 'failed', 'reason': f'parent CfA state not found: {parent_state_path}'}
        parent_cfa = load_state(parent_state_path)

    # Resume path (issue #149): reuse existing worktree and CfA state
    if resume_worktree and resume_infra:
        worktree_path = resume_worktree
        dispatch_infra = resume_infra

        # Retry budget (issue #149): 3 per phase, 9 total per child.
        # Per-phase count resets when CfA state advances to a new phase.
        retry_path = os.path.join(dispatch_infra, '.retry-count')
        retry_data = {'total': 0, 'phase': '', 'phase_count': 0}
        try:
            with open(retry_path) as f:
                retry_data = json.loads(f.read())
                if isinstance(retry_data, int):  # Legacy flat count
                    retry_data = {'total': retry_data, 'phase': '', 'phase_count': 0}
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            pass

        # Load CfA to check phase advancement
        cfa_for_budget = load_state(os.path.join(dispatch_infra, '.cfa-state.json'))
        current_phase = getattr(cfa_for_budget, 'phase', '') if hasattr(cfa_for_budget, 'phase') else ''

        retry_data['total'] += 1
        if current_phase and current_phase != retry_data.get('phase', ''):
            # Phase advanced — reset per-phase counter
            retry_data['phase'] = current_phase
            retry_data['phase_count'] = 1
        else:
            retry_data['phase_count'] = retry_data.get('phase_count', 0) + 1

        with open(retry_path, 'w') as f:
            json.dump(retry_data, f)

        # Budget checks: 3 per phase, 9 total
        if retry_data['total'] > 9:
            return {'status': 'failed', 'reason': f'total retry budget exhausted ({retry_data["total"]} attempts)'}
        if retry_data['phase_count'] > 3:
            return {'status': 'failed', 'reason': f'phase retry budget exhausted ({retry_data["phase_count"]} attempts in {current_phase})'}

        # Load existing CfA state
        cfa = load_state(os.path.join(dispatch_infra, '.cfa-state.json'))

        # Re-create heartbeat for the resumed dispatch
        from projects.POC.orchestrator.heartbeat import create_heartbeat
        create_heartbeat(
            os.path.join(dispatch_infra, '.heartbeat'),
            role=team,
        )
    elif direct_model:
        # Direct execution model (issue #240): run in session worktree,
        # no child worktree. Used by teams whose output is runtime config
        # (.claude/, .teaparty/) that must take effect immediately.
        from datetime import datetime
        dispatch_id = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        worktree_path = session_worktree
        dispatch_infra = os.path.join(infra_dir, team, dispatch_id)
        os.makedirs(dispatch_infra, exist_ok=True)

        from projects.POC.orchestrator.heartbeat import register_child, create_heartbeat
        create_heartbeat(os.path.join(dispatch_infra, '.heartbeat'), role=team)
        children_path = os.path.join(infra_dir, '.children')
        register_child(
            children_path,
            heartbeat=os.path.join(dispatch_infra, '.heartbeat'),
            team=team,
            task_id=liaison_task_id or None,
        )

        cfa = make_child_state(
            parent_cfa, team,
            task_id=f'dispatch-{team}-{dispatch_id}',
        )
        save_state(cfa, os.path.join(dispatch_infra, '.cfa-state.json'))
    else:
        # Worktree-isolated execution model: create a child worktree,
        # run orchestrator there, squash-merge results back.
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

        # Register child in parent's .children registry (issue #149).
        # Optimistic registration: the watchdog can find this child's heartbeat
        # on disk even if the dispatch is still mid-flight.
        from projects.POC.orchestrator.heartbeat import register_child
        children_path = os.path.join(infra_dir, '.children')
        child_heartbeat_path = os.path.join(dispatch_infra, '.heartbeat')
        register_child(
            children_path,
            heartbeat=child_heartbeat_path,
            team=team,
            task_id=liaison_task_id or None,
        )

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

    # Derive dispatch_id for session_id and stream file naming.
    # On fresh dispatch, comes from dispatch_info.  On resume, derive from infra dir name.
    # Direct model sets dispatch_id earlier (issue #240).
    if resume_worktree and resume_infra:
        dispatch_id = os.path.basename(dispatch_infra)
        # Extract prior Claude session ID from stream files for --resume continuity
        resume_session_id = _extract_session_id_from_streams(dispatch_infra)
    elif not direct_model:
        dispatch_id = dispatch_info['dispatch_id']
        resume_session_id = ''
    else:
        # dispatch_id already set in direct model branch above
        resume_session_id = ''

    # Build phase_session_ids for --resume support
    phase_session_ids = {}
    if resume_session_id:
        # The prior session was running execution phase
        phase_session_ids = {'execution': resume_session_id, 'planning': resume_session_id}

    orchestrator = Orchestrator(
        cfa_state=cfa,
        phase_config=config,
        event_bus=event_bus,
        input_provider=_unreachable_input,
        infra_dir=dispatch_infra,
        project_workdir=worktree_path,
        session_worktree=worktree_path,
        proxy_model_path=os.path.join(
            os.path.dirname(infra_dir) if infra_dir else dispatch_infra,
            f'.proxy-confidence-{team}.json',
        ),
        project_slug=project_slug,
        poc_root=poc_root,
        task=task,
        session_id=dispatch_id,
        skip_intent=True,
        never_escalate=True,
        team_override=team,
        phase_session_ids=phase_session_ids if phase_session_ids else None,
        parent_heartbeat=os.path.join(infra_dir, '.heartbeat') if infra_dir else '',
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

    # Merge back into parent session worktree.
    # Direct-model teams (issue #240) already wrote to session_worktree — no merge needed.
    merge_failed = False
    merge_error = ''
    if not direct_model and result and result.terminal_state == 'COMPLETED_WORK':
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

    # Write dispatch MEMORY.md for the rollup chain — only if merge succeeded
    # (or direct model, where there's no merge step).
    if result and result.terminal_state == 'COMPLETED_WORK' and not merge_failed:
        _write_dispatch_memory(dispatch_infra, team, task, result)

    # Clean up worktree — skip for direct model (no child worktree to remove)
    if not direct_model:
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


def _extract_session_id_from_streams(infra_dir: str) -> str:
    """Extract the Claude session ID from stream JSONL files in infra_dir.

    Scans for system/init events which contain the session_id field.
    Returns the first found, or empty string.
    """
    import glob
    for stream_path in glob.glob(os.path.join(infra_dir, '*.jsonl')):
        try:
            with open(stream_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        if (event.get('type') == 'system'
                                and event.get('subtype') == 'init'
                                and event.get('session_id')):
                            return event['session_id']
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue
    return ''


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
