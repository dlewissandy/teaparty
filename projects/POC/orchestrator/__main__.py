"""CLI entry point for the orchestrator.

Usage:
    python -m projects.POC.orchestrator "Your task description"
    python -m projects.POC.orchestrator --project MyProject "Your task"
    python -m projects.POC.orchestrator --skip-intent "Your task"
    python -m projects.POC.orchestrator --resume SESSION_ID_OR_PATH

Replaces ./run.sh "task description".
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from projects.POC.orchestrator.events import EventBus, EventType, InputRequest
from projects.POC.orchestrator.session import Session


class CLIInputProvider:
    """Reads human input from /dev/tty for terminal sessions."""

    async def __call__(self, request: InputRequest) -> str:
        print()
        if request.bridge_text:
            print(f'  {request.bridge_text}')
            print()
        if request.options:
            print(f'  {request.options}')

        prompt = f'[{request.state}] > '

        # Use /dev/tty to read even if stdin is piped
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._read_input, prompt)

    @staticmethod
    def _read_input(prompt: str) -> str:
        try:
            tty = open('/dev/tty')
            sys.stderr.write(prompt)
            sys.stderr.flush()
            response = tty.readline().strip()
            tty.close()
            return response
        except (OSError, EOFError):
            return ''


class CLIEventPrinter:
    """Prints orchestrator events to stderr for CLI feedback."""

    async def __call__(self, event) -> None:
        if event.type == EventType.PHASE_STARTED:
            phase = event.data.get('phase', '')
            print(f'\n── {phase.upper()} ──', file=sys.stderr)
        elif event.type == EventType.STATE_CHANGED:
            state = event.data.get('state', '')
            prev = event.data.get('previous_state', '')
            action = event.data.get('action', '')
            print(f'  CfA: {prev} → {action} → {state}', file=sys.stderr)
        elif event.type == EventType.SESSION_COMPLETED:
            terminal = event.data.get('terminal_state', '')
            bt = event.data.get('backtrack_count', 0)
            resumed = ' (resumed)' if event.data.get('resumed') else ''
            print(f'\n── DONE{resumed}: {terminal} (backtracks: {bt}) ──', file=sys.stderr)
        elif event.type == EventType.SESSION_STARTED:
            if event.data.get('resumed'):
                sid = event.data.get('session_id', '')
                print(f'\n── RESUMING session {sid} ──', file=sys.stderr)
        elif event.type == EventType.DISPATCH_STARTED:
            team = event.data.get('team', '')
            task = event.data.get('task', '')[:60]
            print(f'  dispatch → {team}: {task}', file=sys.stderr)
        elif event.type == EventType.FAILURE:
            reason = event.data.get('reason', '')
            print(f'  FAILURE: {reason}', file=sys.stderr)


def _find_poc_root() -> str:
    """Walk up from this file to find the POC root."""
    d = os.path.dirname(os.path.abspath(__file__))
    while d != '/':
        if os.path.exists(os.path.join(d, 'cfa-state-machine.json')):
            return d
        d = os.path.dirname(d)
    # Fallback
    return os.path.dirname(os.path.abspath(__file__))


def resolve_infra_dir(session_ref: str, poc_root: str, projects_dir: str) -> str:
    """Resolve a session reference to an absolute infra_dir path.

    session_ref can be:
      - An absolute path to an infra_dir (e.g., /path/to/projects/POC/.sessions/20260312-101816)
      - A session ID (e.g., 20260312-101816) — searches all projects
    """
    # If it's an absolute path that exists, use it directly
    if os.path.isabs(session_ref) and os.path.isdir(session_ref):
        return session_ref

    # Search all projects for {project}/.sessions/{session_ref}
    for name in os.listdir(projects_dir):
        candidate = os.path.join(projects_dir, name, '.sessions', session_ref)
        if os.path.isdir(candidate):
            return candidate

    raise FileNotFoundError(
        f'Could not resolve session {session_ref!r}. '
        f'Provide an absolute path or a session ID found under {projects_dir}.'
    )


async def main() -> int:
    parser = argparse.ArgumentParser(
        description='Run a TeaParty POC session',
    )
    parser.add_argument('task', nargs='?', default='', help='Task description')
    parser.add_argument('--project', '-p', help='Project slug override')
    parser.add_argument('--skip-intent', action='store_true',
                        help='Skip intent alignment phase')
    parser.add_argument('--projects-dir', help='Projects directory override')
    parser.add_argument('--resume', metavar='SESSION',
                        help='Resume a crashed/orphaned session (session ID or infra_dir path)')
    args = parser.parse_args()

    poc_root = _find_poc_root()
    projects_dir = args.projects_dir or os.path.dirname(poc_root)

    event_bus = EventBus()
    input_provider = CLIInputProvider()
    printer = CLIEventPrinter()
    event_bus.subscribe(printer)

    # ── Resume mode ──
    if args.resume:
        try:
            infra_dir = resolve_infra_dir(args.resume, poc_root, projects_dir)
        except FileNotFoundError as exc:
            print(f'Error: {exc}', file=sys.stderr)
            return 1

        print(f'Resuming session from {infra_dir}', file=sys.stderr)

        try:
            result = await Session.resume_from_disk(
                infra_dir,
                poc_root=poc_root,
                projects_dir=projects_dir,
                event_bus=event_bus,
                input_provider=input_provider,
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f'Error: {exc}', file=sys.stderr)
            return 1

        return 0 if result.terminal_state == 'COMPLETED_WORK' else 1

    # ── Normal mode ──
    if not args.task:
        parser.error('task is required (or use --resume to resume a session)')

    session = Session(
        task=args.task,
        poc_root=poc_root,
        projects_dir=args.projects_dir,
        project_override=args.project,
        skip_intent=args.skip_intent,
        event_bus=event_bus,
        input_provider=input_provider,
    )

    result = await session.run()

    if result.terminal_state == 'COMPLETED_WORK':
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
