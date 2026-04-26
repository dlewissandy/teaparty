#!/usr/bin/env python3
"""Conversation for Action (CfA) state machine — five states, flat.

States (working → terminal):
  INTENT     — intent-alignment skill runs here
  PLAN       — planning skill runs here
  EXECUTE    — execute skill runs here
  DONE       — terminal: work approved
  WITHDRAWN  — terminal: work abandoned

Each state's skill runs to completion in a single invocation, writes
``./.phase-outcome.json`` with an action (``APPROVED_INTENT`` /
``APPROVED_PLAN`` / ``APPROVED_WORK`` / ``REALIGN`` / ``REPLAN`` /
``WITHDRAW``), and halts.  The orchestrator reads the action and
applies it via :func:`apply_response` — ``ACTION_TO_STATE`` names the
target state.

The actor is always the project lead; there is no per-state actor
lookup.  ``CfaState`` is a pydantic model so serialization is free.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


# ── Vocabularies ──────────────────────────────────────────────────────────
#
# StrEnum so the values are real strings (Pydantic serialization, JSON
# round-trips, ``state == 'INTENT'`` style checks all keep working) while
# the symbol gives us a single source of truth for misspelling-resistant
# comparison and IDE completion.

class State(StrEnum):
    INTENT    = 'INTENT'
    PLAN      = 'PLAN'
    EXECUTE   = 'EXECUTE'
    DONE      = 'DONE'
    WITHDRAWN = 'WITHDRAWN'


class Action(StrEnum):
    APPROVED_INTENT = 'APPROVED_INTENT'
    APPROVED_PLAN   = 'APPROVED_PLAN'
    APPROVED_WORK   = 'APPROVED_WORK'
    REALIGN         = 'REALIGN'
    REPLAN          = 'REPLAN'
    WITHDRAW        = 'WITHDRAW'
    FAILURE         = 'FAILURE'


TERMINAL_STATES: frozenset[State] = frozenset({State.DONE, State.WITHDRAWN})

# Working-state ordering — used by ``apply_response`` to detect
# backtracks.  Terminal states aren't ordered (you can't backtrack out
# of a terminal state).
_STATE_ORDER: dict[State, int] = {
    State.INTENT:  0,
    State.PLAN:    1,
    State.EXECUTE: 2,
}


# ``ACTION_TO_STATE`` is the only routing table: each action names the
# state to land in.  ``APPROVED_*`` advance forward; ``REALIGN`` /
# ``REPLAN`` are backtracks; ``WITHDRAW`` is a terminal abort.
# ``FAILURE`` is the engine's own infra-failure signal — skills don't
# emit it and it does not appear here.
ACTION_TO_STATE: dict[Action, State] = {
    Action.APPROVED_INTENT: State.PLAN,
    Action.APPROVED_PLAN:   State.EXECUTE,
    Action.APPROVED_WORK:   State.DONE,
    Action.REALIGN:         State.INTENT,
    Action.REPLAN:          State.PLAN,
    Action.WITHDRAW:        State.WITHDRAWN,
}


# ── Data model ─────────────────────────────────────────────────────────────

class CfaState(BaseModel):
    """Full state of a Conversation for Action instance.

    Pydantic model — ``model_dump_json()`` / ``model_validate_json()``
    give us serialization for free.
    """
    model_config = ConfigDict(extra='ignore')

    state: State
    history: list = Field(default_factory=list)
    backtrack_count: int = 0
    task_id: str = ''


# ── Factories ──────────────────────────────────────────────────────────────

def make_initial_state(task_id: str = '') -> CfaState:
    """Create the initial CfaState at INTENT."""
    return CfaState(state=State.INTENT, task_id=task_id)


# ── Query functions ────────────────────────────────────────────────────────

def is_globally_terminal(state: str) -> bool:
    """True only for DONE and WITHDRAWN."""
    return state in TERMINAL_STATES


# ── Transition ─────────────────────────────────────────────────────────────

def set_state_direct(cfa: CfaState, target_state: State) -> CfaState:
    """Set ``cfa`` to ``target_state``, no backtrack-count bookkeeping.

    Used when the caller needs to land in a state without going through
    a skill's response (initial state setup, external withdraw, etc.).
    Appends a synthetic ``set-state`` history entry.
    """
    history_entry = {
        'state': cfa.state,
        'action': 'set-state',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'target': target_state,
    }
    return CfaState(
        state=target_state,
        history=cfa.history + [history_entry],
        backtrack_count=cfa.backtrack_count,
        task_id=cfa.task_id,
    )


def apply_response(cfa: CfaState, target_state: State) -> CfaState:
    """Apply a skill's response by setting state to its named target.

    Increments ``backtrack_count`` when the move is to an earlier
    working state (e.g. EXECUTE → INTENT via REALIGN); otherwise
    behaves like :func:`set_state_direct`.
    """
    out = set_state_direct(cfa, target_state)
    new_ord = _STATE_ORDER.get(target_state)
    old_ord = _STATE_ORDER.get(cfa.state)
    if new_ord is not None and old_ord is not None and new_ord < old_ord:
        out.backtrack_count += 1
    return out


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
