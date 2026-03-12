"""CLI entry point for the orchestrator.

Usage:
    python -m projects.POC.orchestrator "Your task description"
    python -m projects.POC.orchestrator --project MyProject "Your task"
    python -m projects.POC.orchestrator --skip-intent "Your task"

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
            print(f'\n── DONE: {terminal} (backtracks: {bt}) ──', file=sys.stderr)
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


async def main() -> int:
    parser = argparse.ArgumentParser(
        description='Run a TeaParty POC session',
    )
    parser.add_argument('task', help='Task description')
    parser.add_argument('--project', '-p', help='Project slug override')
    parser.add_argument('--skip-intent', action='store_true',
                        help='Skip intent alignment phase')
    parser.add_argument('--projects-dir', help='Projects directory override')
    args = parser.parse_args()

    poc_root = _find_poc_root()

    event_bus = EventBus()
    input_provider = CLIInputProvider()
    printer = CLIEventPrinter()
    event_bus.subscribe(printer)

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
