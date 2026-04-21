#!/usr/bin/env python3
"""Conversation for Action (CfA) state machine for multi-agent coordination.

Implements the Agentic CfA framework — a recursive state machine with 3 phases:
  Phase 1: Intent Alignment  (IDEA → INTENT)
  Phase 2: Planning          (INTENT → PLAN)
  Phase 3: Execution         (PLAN → COMPLETED_WORK)

Cross-phase backtracking is supported via special actions (refine-intent,
backtrack, revise-plan) that re-enter earlier phases at RESPONSE or QUESTION
states (the synthesis funnel), never at decision states.

State machine structure is defined in cfa-state-machine.json (the single source
of truth). This module loads from that file and provides the runtime API.

No external dependencies — uses stdlib only (json, datetime, dataclasses, os).
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ── Load state machine from JSON ───────────────────────────────────────────────

_MACHINE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'cfa-state-machine.json',
)


def _load_machine(path: str = _MACHINE_FILE) -> dict:
    with open(path) as f:
        return json.load(f)


def _build_from_machine(machine: dict) -> tuple[
    frozenset, frozenset, frozenset, frozenset,
    dict[str, list[tuple[str, str, str]]],
]:
    """Derive phase sets and transition table from the JSON machine definition."""
    phases = machine['phases']
    intent_states = frozenset(phases['intent']['states'])
    planning_states = frozenset(phases['planning']['states'])
    execution_states = frozenset(phases['execution']['states'])
    all_states = intent_states | planning_states | execution_states

    transitions: dict[str, list[tuple[str, str, str]]] = {}
    for state, edges in machine['transitions'].items():
        transitions[state] = [
            (e['action'], e['to'], e['actor']) for e in edges
        ]

    return intent_states, planning_states, execution_states, all_states, transitions


_machine = _load_machine()
INTENT_STATES, PLANNING_STATES, EXECUTION_STATES, ALL_STATES, TRANSITIONS = (
    _build_from_machine(_machine)
)


# ── Exception ───────────────────────────────────────────────────────────────────

class InvalidTransition(Exception):
    """Raised when an action is not valid from the current state."""
    pass


# ── Data model ──────────────────────────────────────────────────────────────────

@dataclass
class CfaState:
    """Full state of a Conversation for Action instance."""
    phase: str           # 'intent' | 'planning' | 'execution'
    state: str           # e.g. 'IDEA', 'PLANNING', 'WORK_IN_PROGRESS'
    actor: str           # who should act next (from transition table)
    history: list = field(default_factory=list)  # list of dicts: {state, action, actor, timestamp}
    backtrack_count: int = 0  # how many cross-phase backtracks have occurred
    task_id: str = ''    # optional: for execution phase, identifies which task
    # Hierarchy fields — support recursive CfA through team delegation
    parent_id: str = ''  # task_id of parent CfA instance ('' = root)
    team_id: str = ''    # team slug ('coding', 'art', '' for uber)
    depth: int = 0       # nesting depth: 0 = uber, 1 = subteam


# ── Factory ─────────────────────────────────────────────────────────────────────

def make_initial_state(task_id: str = '', team_id: str = '') -> CfaState:
    """Create the initial CfaState at IDEA, ready for the intent team."""
    return CfaState(
        phase='intent',
        state='IDEA',
        actor='intent_team',
        history=[],
        backtrack_count=0,
        task_id=task_id,
        parent_id='',
        team_id=team_id,
        depth=0,
    )


def make_child_state(parent: CfaState, team_id: str, task_id: str = '') -> CfaState:
    """Create a child CfaState linked to a parent dispatch.

    Per spec Section 7, the subteam does not re-derive intent — the delegated
    TASK already carries the approved intent from the outer scope.  The child
    still enters at the INTENT state (to acknowledge the inherited INTENT.md)
    but passes through it quickly rather than running the full intent-alignment
    phase.  ``phase`` matches ``phase_for_state(state)`` throughout the session;
    the first real transition will advance into planning.

    Linked to the parent via parent_id = parent.task_id, with
    depth = parent.depth + 1.
    """
    child_task_id = task_id or f"{team_id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    return CfaState(
        phase='intent',
        state='INTENT',
        actor='planning_team',
        history=[],
        backtrack_count=0,
        task_id=child_task_id,
        parent_id=parent.task_id,
        team_id=team_id,
        depth=parent.depth + 1,
    )


# ── Query functions ─────────────────────────────────────────────────────────────

def phase_for_state(state: str) -> str:
    """Return 'intent', 'planning', or 'execution' for a given state name.

    Raises ValueError for unknown states.
    """
    if state in INTENT_STATES:
        return 'intent'
    if state in PLANNING_STATES:
        return 'planning'
    if state in EXECUTION_STATES:
        return 'execution'
    raise ValueError(f"Unknown state: {state!r}")


def available_actions(state: str) -> list[tuple[str, str]]:
    """Return list of (action, actor) pairs valid from the given state.

    Returns empty list for terminal states. Raises ValueError for unknown states.
    """
    if state not in TRANSITIONS:
        raise ValueError(f"Unknown state: {state!r}")
    return [(action, actor) for action, _target, actor in TRANSITIONS[state]]


def is_phase_terminal(state: str) -> bool:
    """True for states that are terminal for their phase.

    INTENT — terminal for intent phase (also entry to planning).
    COMPLETED_WORK — globally terminal.
    WITHDRAWN — globally terminal.
    """
    return state in ('INTENT', 'COMPLETED_WORK', 'WITHDRAWN')


def is_globally_terminal(state: str) -> bool:
    """True only for COMPLETED_WORK and WITHDRAWN."""
    return state in ('COMPLETED_WORK', 'WITHDRAWN')


def is_root(cfa: CfaState) -> bool:
    """True if this is a root-level (uber-team) CfA instance."""
    return cfa.depth == 0 and not cfa.parent_id


def is_backtrack(from_state: str, action: str) -> bool:
    """True if this transition crosses phase boundaries backward.

    A backtrack occurs when the target state belongs to a phase earlier than
    the source state's phase in the progression: intent < planning < execution.
    """
    _phase_order = {'intent': 0, 'planning': 1, 'execution': 2}
    transitions = TRANSITIONS.get(from_state, [])
    for act, target, _actor in transitions:
        if act == action:
            from_phase = phase_for_state(from_state)
            to_phase = phase_for_state(target)
            return _phase_order[to_phase] < _phase_order[from_phase]
    return False


# ── Core state machine ──────────────────────────────────────────────────────────

def transition(cfa: CfaState, action: str) -> CfaState:
    """Validate action and return a new CfaState with updated fields.

    Raises InvalidTransition if the action is not valid from cfa.state.
    Does not mutate the original CfaState.

    The CfAMachine handles:
      - Transition validation (rejects invalid actions)
      - History tracking (after_transition hook)
      - Backtrack counting (after_transition hook)
      - Backtrack guards (cond='backtrack_allowed' on backtrack edges)
    """
    from statemachine.exceptions import TransitionNotAllowed
    from teaparty.cfa.statemachine.cfa_machine import (
        CfAMachine, CfATransitionModel, PHASE_SETS, TRANSITION_ACTORS,
    )

    current = cfa.state

    # Build the transition model so the machine's hooks can record side effects
    model = CfATransitionModel(
        phase_sets=PHASE_SETS,
        last_action=action,
        last_actor=cfa.actor,
    )

    # Validate and execute via the state machine
    event_name = action.replace('-', '_')
    try:
        sm = CfAMachine(start_value=current, cfa_model=model)
        sm.send(event_name)
    except (TransitionNotAllowed, ValueError):
        valid = [a for a, _ in available_actions(current)]
        raise InvalidTransition(
            f"Action {action!r} is not valid from state {current!r}. "
            f"Valid actions: {valid}"
        )

    target_state = sm.current_state_value
    next_actor = TRANSITION_ACTORS.get((current, action), 'system')
    new_phase = phase_for_state(target_state)

    # History and backtrack_count come from the machine's after_transition hook
    new_history = list(cfa.history) + model.history
    backtrack_count = cfa.backtrack_count + model.backtrack_count

    return CfaState(
        phase=new_phase,
        state=target_state,
        actor=next_actor,
        history=new_history,
        backtrack_count=backtrack_count,
        task_id=cfa.task_id,
        parent_id=cfa.parent_id,
        team_id=cfa.team_id,
        depth=cfa.depth,
    )


# ── Persistence ─────────────────────────────────────────────────────────────────

def save_state(cfa: CfaState, path: str) -> None:
    """Serialize CfaState to a JSON file at path (atomic write)."""
    import os
    dir_name = os.path.dirname(path) if os.path.dirname(path) else '.'
    os.makedirs(dir_name, exist_ok=True)
    data = {
        'phase': cfa.phase,
        'state': cfa.state,
        'actor': cfa.actor,
        'history': cfa.history,
        'backtrack_count': cfa.backtrack_count,
        'task_id': cfa.task_id,
        'parent_id': cfa.parent_id,
        'team_id': cfa.team_id,
        'depth': cfa.depth,
    }
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def load_state(path: str) -> CfaState:
    """Deserialize CfaState from a JSON file at path.

    Backward compatible — hierarchy fields default to empty/zero if absent.
    """
    with open(path) as f:
        data = json.load(f)
    return CfaState(
        phase=data['phase'],
        state=data['state'],
        actor=data['actor'],
        history=data.get('history', []),
        backtrack_count=data.get('backtrack_count', 0),
        task_id=data.get('task_id', ''),
        parent_id=data.get('parent_id', ''),
        team_id=data.get('team_id', ''),
        depth=data.get('depth', 0),
    )


def set_state_direct(cfa: CfaState, target_state: str) -> CfaState:
    """Directly set a CfaState to a target state, bypassing transition validation.

    This is the pragmatic escape hatch for the shell orchestration layer, where
    intermediate micro-transitions between phases are not observed by agents.
    Appends a synthetic 'set-state' history entry.
    """
    new_phase = phase_for_state(target_state)

    # Look up actor for the target state's first available transition,
    # or use 'system' if it's a terminal state
    edges = TRANSITIONS.get(target_state, [])
    actor = edges[0][2] if edges else 'system'

    history_entry = {
        'state': cfa.state,
        'action': 'set-state',
        'actor': 'system',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'target': target_state,
    }

    return CfaState(
        phase=new_phase,
        state=target_state,
        actor=actor,
        history=list(cfa.history) + [history_entry],
        backtrack_count=cfa.backtrack_count,
        task_id=cfa.task_id,
        parent_id=cfa.parent_id,
        team_id=cfa.team_id,
        depth=cfa.depth,
    )


# ── CLI ─────────────────────────────────────────────────────────────────────────

def _cli_test() -> None:
    """Run self-test assertions."""
    print("Running CfA state machine self-tests...")

    # make_initial_state
    cfa = make_initial_state()
    assert cfa.state == 'IDEA', f"Expected IDEA, got {cfa.state}"
    assert cfa.phase == 'intent', f"Expected intent, got {cfa.phase}"
    assert cfa.actor == 'human'
    assert cfa.backtrack_count == 0
    assert cfa.history == []
    print("  [OK] make_initial_state")

    # Happy path: IDEA → INTENT → PLANNING → WORK_IN_PROGRESS → COMPLETED_WORK
    cfa = transition(cfa, 'approve')
    assert cfa.state == 'INTENT'
    assert is_phase_terminal('INTENT')
    assert not is_globally_terminal('INTENT')
    cfa = transition(cfa, 'plan')
    assert cfa.state == 'PLANNING'
    cfa = transition(cfa, 'approve')
    assert cfa.state == 'WORK_IN_PROGRESS'
    cfa = transition(cfa, 'assert')
    assert cfa.state == 'WORK_ASSERT'
    cfa = transition(cfa, 'approve')
    assert cfa.state == 'COMPLETED_WORK'
    assert is_globally_terminal('COMPLETED_WORK')
    print("  [OK] Happy path: IDEA → COMPLETED_WORK")

    # Invalid transition raises InvalidTransition
    try:
        transition(cfa, 'approve')
        assert False, "Should have raised InvalidTransition"
    except InvalidTransition:
        pass
    print("  [OK] InvalidTransition raised for terminal state")

    # Backtrack detection
    assert is_backtrack('PLANNING', 'backtrack'), "PLANNING→backtrack should be backtrack"
    assert not is_backtrack('IDEA', 'approve'), "IDEA→approve is not a backtrack"
    print("  [OK] is_backtrack")

    # Backtrack count increment
    cfa2 = make_initial_state()
    cfa2 = transition(cfa2, 'approve')  # INTENT
    cfa2 = transition(cfa2, 'plan')     # PLANNING
    cfa2 = transition(cfa2, 'backtrack')  # IDEA (backtrack)
    assert cfa2.backtrack_count == 1, f"Expected 1, got {cfa2.backtrack_count}"
    print("  [OK] backtrack_count increments on cross-phase backtrack")

    # phase_for_state
    assert phase_for_state('IDEA') == 'intent'
    assert phase_for_state('PLANNING') == 'planning'
    assert phase_for_state('WORK_IN_PROGRESS') == 'execution'
    assert phase_for_state('COMPLETED_WORK') == 'execution'
    print("  [OK] phase_for_state")

    # available_actions
    actions = dict(available_actions('IDEA'))
    assert 'approve' in actions
    assert 'withdraw' in actions
    print("  [OK] available_actions")

    # Persistence round-trip
    import tempfile, os
    cfa3 = make_initial_state()
    cfa3 = transition(cfa3, 'approve')
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        tmp_path = f.name
    try:
        save_state(cfa3, tmp_path)
        loaded = load_state(tmp_path)
        assert loaded.state == cfa3.state
        assert loaded.phase == cfa3.phase
        assert loaded.actor == cfa3.actor
        assert loaded.backtrack_count == cfa3.backtrack_count
        assert len(loaded.history) == len(cfa3.history)
    finally:
        os.unlink(tmp_path)
    print("  [OK] save_state / load_state round-trip")

    # Hierarchy: make_child_state
    parent = make_initial_state(task_id='uber-001')
    parent = transition(parent, 'approve')
    parent = transition(parent, 'plan')
    parent = transition(parent, 'approve')
    assert parent.state == 'WORK_IN_PROGRESS'

    child = make_child_state(parent, 'coding')
    assert child.parent_id == 'uber-001'
    assert child.team_id == 'coding'
    assert child.depth == 1
    assert child.state == 'INTENT', f"Expected INTENT, got {child.state}"
    assert child.phase == 'intent', f"Expected intent, got {child.phase}"
    assert is_root(parent) is True  # depth=0, parent_id='' → root even with task_id set
    root = make_initial_state()
    assert is_root(root) is True
    assert is_root(child) is False
    print("  [OK] make_child_state + is_root")

    # Hierarchy: child transitions preserve hierarchy fields
    child = transition(child, 'plan')  # INTENT → PLANNING
    assert child.parent_id == 'uber-001'
    assert child.team_id == 'coding'
    assert child.depth == 1
    print("  [OK] hierarchy fields preserved through transitions")

    # Hierarchy: persistence round-trip with hierarchy fields
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        tmp_path2 = f.name
    try:
        save_state(child, tmp_path2)
        loaded2 = load_state(tmp_path2)
        assert loaded2.parent_id == 'uber-001'
        assert loaded2.team_id == 'coding'
        assert loaded2.depth == 1
    finally:
        os.unlink(tmp_path2)
    print("  [OK] hierarchy fields survive persistence round-trip")

    # set_state_direct
    cfa4 = make_initial_state()
    cfa4 = set_state_direct(cfa4, 'PLANNING')
    assert cfa4.state == 'PLANNING'
    assert cfa4.phase == 'planning'
    assert len(cfa4.history) == 1
    assert cfa4.history[0]['action'] == 'set-state'
    print("  [OK] set_state_direct")

    print("\nAll self-tests passed.")


def _cli_transitions() -> None:
    """Print all valid transitions in a readable table."""
    print(f"{'FROM STATE':<25} {'ACTION':<20} {'TO STATE':<25} {'ACTOR':<20}")
    print("-" * 90)
    for state, edges in TRANSITIONS.items():
        for action, target, actor in edges:
            marker = " [BACKTRACK]" if is_backtrack(state, action) else ""
            print(f"{state:<25} {action:<20} {target:<25} {actor:<20}{marker}")


def _cli_dot() -> None:
    """Output Graphviz DOT for visualization."""
    # Color nodes by phase
    phase_colors = {
        'intent':    'lightblue',
        'planning':  'lightyellow',
        'execution': 'lightgreen',
    }
    terminal_colors = {
        'COMPLETED_WORK': 'palegreen',
        'WITHDRAWN':      'lightsalmon',
    }

    print('digraph CfA {')
    print('  rankdir=LR;')
    print('  node [shape=box, style=filled, fontname="Helvetica"];')
    print()

    # Node declarations with colors
    for state in sorted(ALL_STATES):
        if state in terminal_colors:
            color = terminal_colors[state]
            shape = 'doublecircle'
        else:
            color = phase_colors.get(phase_for_state(state), 'white')
            shape = 'box'
        label = state.replace('_', '\\n')
        print(f'  {state} [label="{label}", fillcolor="{color}", shape="{shape}"];')

    print()

    # Edges
    for state, edges in TRANSITIONS.items():
        for action, target, actor in edges:
            style = 'dashed' if is_backtrack(state, action) else 'solid'
            color = 'red' if is_backtrack(state, action) else 'black'
            print(f'  {state} -> {target} [label="{action}\\n({actor})", style="{style}", color="{color}"];')

    print('}')


def _cli_init(args: list[str]) -> None:
    """Create initial root CfA state and save to file."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, help='Output file path')
    parser.add_argument('--task-id', default='', help='Optional task ID')
    parser.add_argument('--team', default='', help='Optional team ID')
    parsed = parser.parse_args(args)

    cfa = make_initial_state(task_id=parsed.task_id, team_id=parsed.team)
    save_state(cfa, parsed.output)


def _cli_make_child(args: list[str]) -> None:
    """Create a child CfA state linked to a parent."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--parent', required=True, help='Parent state file')
    parser.add_argument('--team', required=True, help='Team slug')
    parser.add_argument('--output', required=True, help='Output file path')
    parser.add_argument('--task-id', default='', help='Optional task ID')
    parsed = parser.parse_args(args)

    parent = load_state(parsed.parent)
    child = make_child_state(parent, parsed.team, task_id=parsed.task_id)
    save_state(child, parsed.output)


def _cli_set_state(args: list[str]) -> None:
    """Set state directly (bypassing transitions) — for shell orchestration."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--state-file', required=True, help='State file to modify')
    parser.add_argument('--target', required=True, help='Target state name')
    parsed = parser.parse_args(args)

    if parsed.target not in ALL_STATES:
        print(f"Unknown state: {parsed.target}", file=sys.stderr)
        sys.exit(1)

    cfa = load_state(parsed.state_file)
    cfa = set_state_direct(cfa, parsed.target)
    save_state(cfa, parsed.state_file)


def _cli_transition(args: list[str]) -> None:
    """Apply a validated transition to a CfA state file.

    Loads current state, validates the action against the transition table,
    applies the transition, saves the updated state, and prints the new state
    name to stdout.  Exits 1 if the action is not valid from the current state.
    """
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--state-file', required=True, help='State file to modify')
    parser.add_argument('--action', required=True, help='Action to take (e.g. approve, correct, withdraw)')
    parsed = parser.parse_args(args)

    cfa = load_state(parsed.state_file)
    try:
        cfa = transition(cfa, parsed.action)
    except InvalidTransition as e:
        print(f"InvalidTransition: {e}", file=sys.stderr)
        sys.exit(1)
    save_state(cfa, parsed.state_file)
    # Print new state name to stdout for shell capture
    print(cfa.state)


def _cli_read(args: list[str]) -> None:
    """Print current state as JSON summary to stdout."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--state-file', required=True, help='State file to read')
    parsed = parser.parse_args(args)

    cfa = load_state(parsed.state_file)
    summary = {
        'state': cfa.state,
        'phase': cfa.phase,
        'actor': cfa.actor,
        'backtrack_count': cfa.backtrack_count,
        'task_id': cfa.task_id,
        'parent_id': cfa.parent_id,
        'team_id': cfa.team_id,
        'depth': cfa.depth,
    }
    print(json.dumps(summary))


COMMANDS = {
    '--test': lambda args: _cli_test(),
    '--transitions': lambda args: _cli_transitions(),
    '--dot': lambda args: _cli_dot(),
    '--init': _cli_init,
    '--make-child': _cli_make_child,
    '--set-state': _cli_set_state,
    '--transition': _cli_transition,
    '--read': _cli_read,
}

if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: python3 cfa_state.py {' | '.join(COMMANDS.keys())}")
        sys.exit(1)

    cmd = sys.argv[1]
    COMMANDS[cmd](sys.argv[2:])
