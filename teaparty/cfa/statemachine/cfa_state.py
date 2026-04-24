#!/usr/bin/env python3
"""Conversation for Action (CfA) state machine — five states, three phases.

States (working → terminal):
  INTENT     — intent-alignment skill runs here
  PLAN       — planning skill runs here
  EXECUTE    — execute skill runs here
  DONE       — terminal: work approved
  WITHDRAWN  — terminal: work abandoned

Each phase's skill runs to completion in a single invocation, writes
``./.phase-outcome.json`` with an outcome string (``APPROVE`` /
``REALIGN`` / ``REPLAN`` / ``WITHDRAW``), and halts.  The orchestrator
reads the outcome and calls ``transition(cfa, action)`` — action is
the lowercase outcome (``approve`` / ``realign`` / ``replan`` /
``withdraw``).

The machine is **static** — five states, three phases, ten edges.
Previously this module loaded from ``cfa-state-machine.json`` and
wrapped the definition in a third-party ``python-statemachine``
StateMachine class (``cfa_machine.py``, 232 lines of ceremony for a
5-state table).  The JSON + wrapper layer is deleted; what replaces
it is the literal table below plus a 15-line ``transition()``.  If
the machine ever gets complex enough to need a library, it won't be
this machine.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone


# ── State machine definition (the entire machine is here) ──────────────────

# Each entry: state → [(action, target_state, actor), ...]
# Terminal states have no outgoing edges.
TRANSITIONS: dict[str, list[tuple[str, str, str]]] = {
    'INTENT': [
        ('approve',  'PLAN',      'intent_team'),
        ('withdraw', 'WITHDRAWN', 'intent_team'),
    ],
    'PLAN': [
        ('approve',  'EXECUTE',   'planning_team'),
        ('realign',  'INTENT',    'planning_team'),
        ('withdraw', 'WITHDRAWN', 'planning_team'),
    ],
    'EXECUTE': [
        ('approve',  'DONE',      'project_lead'),
        ('replan',   'PLAN',      'project_lead'),
        ('realign',  'INTENT',    'project_lead'),
        ('withdraw', 'WITHDRAWN', 'project_lead'),
    ],
    'DONE': [],
    'WITHDRAWN': [],
}

INTENT_STATES    = frozenset({'INTENT'})
PLANNING_STATES  = frozenset({'PLAN'})
EXECUTION_STATES = frozenset({'EXECUTE', 'DONE', 'WITHDRAWN'})
ALL_STATES       = INTENT_STATES | PLANNING_STATES | EXECUTION_STATES
TERMINAL_STATES  = frozenset({'DONE', 'WITHDRAWN'})

# Phase progression — used for backtrack detection.
_PHASE_ORDER = {'intent': 0, 'planning': 1, 'execution': 2}


# ── Exception ──────────────────────────────────────────────────────────────

class InvalidTransition(Exception):
    """Raised when an action is not valid from the current state."""


# ── Data model ─────────────────────────────────────────────────────────────

@dataclass
class CfaState:
    """Full state of a Conversation for Action instance."""
    phase: str           # 'intent' | 'planning' | 'execution'
    state: str           # 'INTENT' | 'PLAN' | 'EXECUTE' | 'DONE' | 'WITHDRAWN'
    actor: str           # who should act next (from the transition table)
    history: list = field(default_factory=list)
    backtrack_count: int = 0
    task_id: str = ''
    # Hierarchy fields — recursive CfA through team delegation.
    parent_id: str = ''
    team_id: str = ''
    depth: int = 0


# ── Factories ──────────────────────────────────────────────────────────────

def make_initial_state(task_id: str = '', team_id: str = '') -> CfaState:
    """Create the initial CfaState at INTENT, ready for the intent team."""
    return CfaState(
        phase='intent', state='INTENT', actor='intent_team',
        task_id=task_id, team_id=team_id,
    )


def make_child_state(parent: CfaState, team_id: str, task_id: str = '') -> CfaState:
    """Create a child CfaState linked to a parent dispatch.

    The subteam does not re-derive intent — the delegated TASK already
    carries the approved intent from the outer scope.  The child enters
    at INTENT to acknowledge the inherited INTENT.md and quickly
    approves through it rather than running the full intent-alignment
    dialog.
    """
    child_task_id = (
        task_id
        or f"{team_id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    )
    return CfaState(
        phase='intent', state='INTENT', actor='intent_team',
        task_id=child_task_id,
        parent_id=parent.task_id,
        team_id=team_id,
        depth=parent.depth + 1,
    )


# ── Query functions ────────────────────────────────────────────────────────

def phase_for_state(state: str) -> str:
    """Return 'intent' / 'planning' / 'execution' for a given state."""
    if state in INTENT_STATES:
        return 'intent'
    if state in PLANNING_STATES:
        return 'planning'
    if state in EXECUTION_STATES:
        return 'execution'
    raise ValueError(f'Unknown state: {state!r}')


def available_actions(state: str) -> list[tuple[str, str]]:
    """Return list of (action, actor) pairs valid from *state*.

    Empty list for terminal states.  Raises ValueError for unknown states.
    """
    if state not in TRANSITIONS:
        raise ValueError(f'Unknown state: {state!r}')
    return [(action, actor) for action, _target, actor in TRANSITIONS[state]]


def is_phase_terminal(state: str) -> bool:
    """True for globally terminal states (DONE, WITHDRAWN)."""
    return state in TERMINAL_STATES


def is_globally_terminal(state: str) -> bool:
    """True only for DONE and WITHDRAWN."""
    return state in TERMINAL_STATES


def is_root(cfa: CfaState) -> bool:
    """True if this is a root-level (uber-team) CfA instance."""
    return cfa.depth == 0 and not cfa.parent_id


def is_backtrack(from_state: str, action: str) -> bool:
    """True if this transition moves to an earlier phase."""
    for act, target, _actor in TRANSITIONS.get(from_state, []):
        if act == action:
            return (
                _PHASE_ORDER[phase_for_state(target)]
                < _PHASE_ORDER[phase_for_state(from_state)]
            )
    return False


# ── Transition ─────────────────────────────────────────────────────────────

def transition(cfa: CfaState, action: str) -> CfaState:
    """Validate *action* from ``cfa.state`` and return the new CfaState.

    Raises ``InvalidTransition`` if the action is not valid from the
    current state.  Does not mutate ``cfa``.  Appends a history entry
    and increments ``backtrack_count`` for cross-phase backward moves.
    """
    for act, target, actor in TRANSITIONS.get(cfa.state, []):
        if act == action:
            history_entry = {
                'state': cfa.state,
                'action': action,
                'actor': cfa.actor,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
            new_phase = phase_for_state(target)
            new_backtrack_count = cfa.backtrack_count + (
                1 if _PHASE_ORDER[new_phase]
                < _PHASE_ORDER[phase_for_state(cfa.state)]
                else 0
            )
            return CfaState(
                phase=new_phase,
                state=target,
                actor=actor,
                history=cfa.history + [history_entry],
                backtrack_count=new_backtrack_count,
                task_id=cfa.task_id,
                parent_id=cfa.parent_id,
                team_id=cfa.team_id,
                depth=cfa.depth,
            )
    valid = [a for a, _ in available_actions(cfa.state)]
    raise InvalidTransition(
        f'Action {action!r} is not valid from state {cfa.state!r}. '
        f'Valid actions: {valid}'
    )


def set_state_direct(cfa: CfaState, target_state: str) -> CfaState:
    """Set ``cfa`` to ``target_state``, bypassing transition validation.

    Pragmatic escape hatch for the shell orchestration layer — skip-intent
    / execute-only flows jump straight to a working state without an
    agent producing an outcome.  Appends a synthetic ``set-state``
    history entry.  Does NOT update ``backtrack_count``.
    """
    if target_state not in ALL_STATES:
        raise ValueError(f'Unknown state: {target_state!r}')
    edges = TRANSITIONS.get(target_state, [])
    next_actor = edges[0][2] if edges else 'system'
    history_entry = {
        'state': cfa.state,
        'action': 'set-state',
        'actor': 'system',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'target': target_state,
    }
    return CfaState(
        phase=phase_for_state(target_state),
        state=target_state,
        actor=next_actor,
        history=cfa.history + [history_entry],
        backtrack_count=cfa.backtrack_count,
        task_id=cfa.task_id,
        parent_id=cfa.parent_id,
        team_id=cfa.team_id,
        depth=cfa.depth,
    )


# ── Persistence ────────────────────────────────────────────────────────────

def save_state(cfa: CfaState, path: str) -> None:
    """Serialize CfaState to *path* atomically."""
    dir_name = os.path.dirname(path) or '.'
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
    """Deserialize CfaState from *path*."""
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
