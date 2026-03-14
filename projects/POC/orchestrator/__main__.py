"""CLI entry point for the orchestrator.

Usage:
    python -m projects.POC.orchestrator "Your task description"
    python -m projects.POC.orchestrator --project MyProject "Your task"
    python -m projects.POC.orchestrator --skip-intent "Your task"
    python -m projects.POC.orchestrator --resume SESSION_ID_OR_PATH

Phase control:
    python -m projects.POC.orchestrator --intent-only "Align on this idea"
    python -m projects.POC.orchestrator --plan-only "Plan this feature"
    python -m projects.POC.orchestrator --execute-only "Just build it"

Context injection:
    python -m projects.POC.orchestrator --intent-file INTENT.md "Build on this"
    python -m projects.POC.orchestrator --plan-file PLAN.md "Execute this plan"

Testing:
    python -m projects.POC.orchestrator --no-human --execute-only "Fully automated"
    python -m projects.POC.orchestrator --dry-run -p myproject "Show memory + proxy"
    python -m projects.POC.orchestrator --show-memory "Show memory then run"
    python -m projects.POC.orchestrator --show-proxy -p myproject "Show proxy model"
    python -m projects.POC.orchestrator --skip-learnings "Skip learning extraction"
    python -m projects.POC.orchestrator -v "Verbose proxy/artifact tracing"
    python -m projects.POC.orchestrator --flat "No hierarchical dispatch"

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


class _AutoApproveProvider:
    """Auto-approves everything — for unattended/autonomous test sessions.

    Never blocks for human input. The proxy model still makes decisions;
    any human review gates that would normally escalate are auto-approved.
    """

    async def __call__(self, request: InputRequest) -> str:
        return 'approve'


class CLIEventPrinter:
    """Prints orchestrator events to stderr for CLI feedback."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

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
        elif event.type == EventType.LOG and self.verbose:
            self._print_log(event.data)

    @staticmethod
    def _print_log(data: dict) -> None:
        """Format and print LOG events for --verbose mode."""
        category = data.get('category', '')
        if category == 'proxy_decision':
            decision = data.get('decision', '')
            confidence = data.get('confidence', 0.0)
            reasoning = data.get('reasoning', '')
            print(f'  [proxy] {decision} (confidence={confidence:.3f}): {reasoning}',
                  file=sys.stderr)
        elif category == 'artifact_detection':
            action = data.get('action', '')
            artifact = data.get('artifact_path', '')
            missing = data.get('artifact_missing', False)
            if missing:
                print(f'  [artifact] MISSING — expected {data.get("artifact_expected", "?")}',
                      file=sys.stderr)
            elif artifact:
                print(f'  [artifact] found: {artifact} → {action}', file=sys.stderr)
            else:
                print(f'  [artifact] none configured → {action}', file=sys.stderr)
        elif category == 'auto_bridge':
            state = data.get('state', '')
            action = data.get('action', '')
            print(f'  [bridge] {state} → {action}', file=sys.stderr)
        elif category == 'generative_response':
            result = data.get('result', '')
            state = data.get('state', '')
            print(f'  [generative] {state}: {result}', file=sys.stderr)
        elif category == 'elapsed_time_guard':
            elapsed = data.get('elapsed', 0)
            minimum = data.get('minimum', 0)
            print(f'  [proxy] elapsed-time guard: {elapsed:.0f}s < {minimum}s — escalating',
                  file=sys.stderr)
        elif category == 'approval_dialog':
            state = data.get('state', '')
            classification = data.get('classification', '')
            print(f'  [dialog] {state}: classified as {classification}', file=sys.stderr)
        else:
            message = data.get('message', str(data))
            print(f'  [log:{category}] {message}', file=sys.stderr)


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
    parser.add_argument('--idea', metavar='TEXT',
                        help='Brief idea name (semantic alias for task)')
    parser.add_argument('--project', '-p', help='Project slug override')
    parser.add_argument('--projects-dir', help='Projects directory override')
    parser.add_argument('--resume', metavar='SESSION',
                        help='Resume a crashed/orphaned session (session ID or infra_dir path)')

    # ── Phase control ──
    phase_group = parser.add_argument_group('phase control')
    phase_group.add_argument('--skip-intent', action='store_true',
                             help='Skip intent alignment phase')
    phase_group.add_argument('--intent-only', action='store_true',
                             help='Run intent phase only, then stop')
    phase_group.add_argument('--plan-only', action='store_true',
                             help='Run through planning, stop before execution')
    phase_group.add_argument('--execute-only', action='store_true',
                             help='Skip intent+planning, run execution only')

    # ── Context injection ──
    context_group = parser.add_argument_group('context injection')
    context_group.add_argument('--intent-file', metavar='PATH',
                               help='Pre-written INTENT.md; skip intent, start at planning')
    context_group.add_argument('--plan-file', metavar='PATH',
                               help='Pre-written PLAN.md; skip to execution')

    # ── Testing / observability ──
    test_group = parser.add_argument_group('testing')
    test_group.add_argument('--no-human', '--autonomous', action='store_true',
                            dest='no_human',
                            help='Never block for human input; auto-approve all review gates')
    test_group.add_argument('--show-memory', action='store_true',
                            help='Print memory context that will be injected (for debugging)')
    test_group.add_argument('--show-proxy', action='store_true',
                            help='Print proxy confidence model state (for debugging)')
    test_group.add_argument('--dry-run', action='store_true',
                            help='Print memory context and exit without running the session')
    test_group.add_argument('--skip-learnings', action='store_true',
                            help='Skip post-session learning extraction')
    test_group.add_argument('--verbose', '-v', action='store_true',
                            help='Trace-level output: proxy decisions, artifact detection, bridges')
    test_group.add_argument('--flat', action='store_true',
                            help='Disable hierarchical dispatch; lead recruits agents dynamically')

    args = parser.parse_args()

    # ── Validate ──
    for flag, path in [('--intent-file', args.intent_file), ('--plan-file', args.plan_file)]:
        if path and not os.path.isfile(path):
            parser.error(f'{flag}: file not found: {path}')

    poc_root = _find_poc_root()
    projects_dir = args.projects_dir or os.path.dirname(poc_root)

    event_bus = EventBus()
    if args.no_human:
        input_provider = _AutoApproveProvider()
    else:
        input_provider = CLIInputProvider()
    printer = CLIEventPrinter(verbose=args.verbose)
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
    task = args.idea or args.task
    if not task:
        parser.error('task or --idea is required (or use --resume to resume a session)')

    # Derive skip_intent from context injection and phase control flags
    skip_intent = (args.skip_intent
                   or bool(args.intent_file)
                   or bool(args.plan_file)
                   or args.execute_only)

    session = Session(
        task=task,
        poc_root=poc_root,
        projects_dir=args.projects_dir,
        project_override=args.project,
        skip_intent=skip_intent,
        intent_file=args.intent_file,
        plan_file=args.plan_file,
        intent_only=args.intent_only,
        plan_only=args.plan_only,
        execute_only=args.execute_only,
        show_memory=args.show_memory or args.dry_run,
        show_proxy=args.show_proxy or args.dry_run,
        dry_run=args.dry_run,
        skip_learnings=args.skip_learnings,
        verbose=args.verbose,
        flat=args.flat,
        event_bus=event_bus,
        input_provider=input_provider,
    )

    result = await session.run()

    if result.terminal_state in ('COMPLETED_WORK', 'DRY_RUN'):
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
