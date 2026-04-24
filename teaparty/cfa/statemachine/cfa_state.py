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

The actor is always the project lead; there is no per-state actor
lookup.  Terminal states (DONE, WITHDRAWN) are their own phase
``'terminal'`` — they are not execution states.  The machine is
**static**: five states, three working phases, ten edges.
``CfaState`` is a pydantic model so serialization is free.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from pydantic import BaseModel, Field


# ── State machine definition (the entire machine is here) ──────────────────

# Each entry: state → [(action, target_state), ...]
# Terminal states have no outgoing edges.
TRANSITIONS: dict[str, list[tuple[str, str]]] = {
    'INTENT': [
        ('approve',  'PLAN'),
        ('withdraw', 'WITHDRAWN'),
    ],
    'PLAN': [
        ('approve',  'EXECUTE'),
        ('realign',  'INTENT'),
        ('withdraw', 'WITHDRAWN'),
    ],
    'EXECUTE': [
        ('approve',  'DONE'),
        ('replan',   'PLAN'),
        ('realign',  'INTENT'),
        ('withdraw', 'WITHDRAWN'),
    ],
    'DONE': [],
    'WITHDRAWN': [],
}

INTENT_STATES    = frozenset({'INTENT'})
PLANNING_STATES  = frozenset({'PLAN'})
EXECUTION_STATES = frozenset({'EXECUTE'})
TERMINAL_STATES  = frozenset({'DONE', 'WITHDRAWN'})
ALL_STATES       = INTENT_STATES | PLANNING_STATES | EXECUTION_STATES | TERMINAL_STATES

# Phase progression — used for backtrack detection.  Terminal has no
# order (you can't backtrack out of a terminal state).
_PHASE_ORDER = {'intent': 0, 'planning': 1, 'execution': 2}


# ── Exception ──────────────────────────────────────────────────────────────

class InvalidTransition(Exception):
    """Raised when an action is not valid from the current state."""


# ── Data model ─────────────────────────────────────────────────────────────

class CfaState(BaseModel):
    """Full state of a Conversation for Action instance.

    Pydantic model — ``model_dump_json()`` / ``model_validate_json()``
    give us serialization for free.  ``save_state`` / ``load_state``
    wrap those with atomic file I/O.
    """
    phase: str           # 'intent' | 'planning' | 'execution' | 'terminal'
    state: str           # 'INTENT' | 'PLAN' | 'EXECUTE' | 'DONE' | 'WITHDRAWN'
    history: list = Field(default_factory=list)
    backtrack_count: int = 0
    task_id: str = ''


# ── Factories ──────────────────────────────────────────────────────────────

def make_initial_state(task_id: str = '') -> CfaState:
    """Create the initial CfaState at INTENT."""
    return CfaState(phase='intent', state='INTENT', task_id=task_id)


# ── Query functions ────────────────────────────────────────────────────────

def phase_for_state(state: str) -> str:
    """Return the phase label for a state.

    Working phases: 'intent' / 'planning' / 'execution'.
    Terminal states (DONE, WITHDRAWN) are 'terminal'.
    """
    if state in INTENT_STATES:
        return 'intent'
    if state in PLANNING_STATES:
        return 'planning'
    if state in EXECUTION_STATES:
        return 'execution'
    if state in TERMINAL_STATES:
        return 'terminal'
    raise ValueError(f'Unknown state: {state!r}')


def available_actions(state: str) -> list[str]:
    """Return the list of actions valid from *state*.

    Empty list for terminal states.  Raises ValueError for unknown states.
    """
    if state not in TRANSITIONS:
        raise ValueError(f'Unknown state: {state!r}')
    return [action for action, _target in TRANSITIONS[state]]


def is_globally_terminal(state: str) -> bool:
    """True only for DONE and WITHDRAWN."""
    return state in TERMINAL_STATES


def is_backtrack(from_state: str, action: str) -> bool:
    """True if this transition moves to an earlier working phase.

    Transitions into terminal states are never backtracks — they are
    ends, not moves.
    """
    for act, target in TRANSITIONS.get(from_state, []):
        if act == action:
            target_phase = phase_for_state(target)
            from_phase = phase_for_state(from_state)
            if target_phase == 'terminal' or from_phase == 'terminal':
                return False
            return _PHASE_ORDER[target_phase] < _PHASE_ORDER[from_phase]
    return False


# ── Transition ─────────────────────────────────────────────────────────────

def transition(cfa: CfaState, action: str) -> CfaState:
    """Validate *action* from ``cfa.state`` and return the new CfaState.

    Raises ``InvalidTransition`` if the action is not valid from the
    current state.  Does not mutate ``cfa``.  Appends a history entry
    and increments ``backtrack_count`` for cross-phase backward moves.
    """
    for act, target in TRANSITIONS.get(cfa.state, []):
        if act == action:
            history_entry = {
                'state': cfa.state,
                'action': action,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
            new_phase = phase_for_state(target)
            old_phase = phase_for_state(cfa.state)
            is_working_backtrack = (
                new_phase != 'terminal'
                and old_phase != 'terminal'
                and _PHASE_ORDER[new_phase] < _PHASE_ORDER[old_phase]
            )
            return CfaState(
                phase=new_phase,
                state=target,
                history=cfa.history + [history_entry],
                backtrack_count=cfa.backtrack_count + (1 if is_working_backtrack else 0),
                task_id=cfa.task_id,
            )
    raise InvalidTransition(
        f'Action {action!r} is not valid from state {cfa.state!r}. '
        f'Valid actions: {available_actions(cfa.state)}'
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
    history_entry = {
        'state': cfa.state,
        'action': 'set-state',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'target': target_state,
    }
    return CfaState(
        phase=phase_for_state(target_state),
        state=target_state,
        history=cfa.history + [history_entry],
        backtrack_count=cfa.backtrack_count,
        task_id=cfa.task_id,
    )


# ── Persistence ────────────────────────────────────────────────────────────

def save_state(cfa: CfaState, path: str) -> None:
    """Serialize CfaState to *path* atomically via pydantic."""
    dir_name = os.path.dirname(path) or '.'
    os.makedirs(dir_name, exist_ok=True)
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w') as f:
            f.write(cfa.model_dump_json(indent=2))
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def load_state(path: str) -> CfaState:
    """Deserialize CfaState from *path* via pydantic."""
    with open(path) as f:
        return CfaState.model_validate_json(f.read())
