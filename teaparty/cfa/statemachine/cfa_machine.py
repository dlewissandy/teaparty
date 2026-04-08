"""CfA state machine as a python-statemachine StateMachine class.

Dynamically constructs a StateMachine subclass from the canonical JSON
definition (cfa-state-machine.json).  The resulting CfAMachine class makes
the CfA lifecycle — 25 states across three phases, with cross-phase
backtracks, actor routing, and review gates — visible as a single declared
artifact.

The JSON remains the single source of truth.  This module reads it once at
import time and produces the machine class.  No hand-written duplication.

Side effects (history tracking, backtrack counting) are handled by
after_transition hooks on the machine, not manually in transition().

Guards:
  - Backtrack transitions carry cond='backtrack_allowed', so the machine
    can suppress cross-phase backtracks when configured to do so
    (e.g., subteams with suppress_backtracks=True).
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone

from statemachine import State, StateMachine


# ── Load JSON ──────────────────────────────────────────────────────────────

_MACHINE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'cfa-state-machine.json',
)


def _load_machine(path: str = _MACHINE_FILE) -> dict:
    with open(path) as f:
        return json.load(f)


# ── Phase lookup (needed by hooks) ────────────────────────────────────────

def _build_phase_sets(machine: dict) -> dict[str, frozenset[str]]:
    return {
        phase_name: frozenset(info['states'])
        for phase_name, info in machine['phases'].items()
    }


_PHASE_ORDER = {'intent': 0, 'planning': 1, 'execution': 2}


def _phase_for(state_value: str, phase_sets: dict[str, frozenset[str]]) -> str:
    for phase_name, states in phase_sets.items():
        if state_value in states:
            return phase_name
    raise ValueError(f"Unknown state: {state_value!r}")


# ── Factory ────────────────────────────────────────────────────────────────

def _build_machine_class(machine: dict) -> type:
    """Construct a StateMachine subclass from the JSON machine definition.

    Each state in the JSON becomes a State() attribute on the class.
    Each unique action name becomes an event (transition) attribute,
    composed with | for actions that originate from multiple states.

    Hooks:
      after_transition — appends to model.history, increments backtrack_count

    Guards:
      backtrack_allowed — gates cross-phase backtrack transitions;
        returns True by default, configurable via constructor kwarg
    """
    terminal_states = set(machine.get('terminal_states', []))
    phase_sets = _build_phase_sets(machine)

    # Collect all states with their phase membership
    all_state_names: set[str] = set()
    for phase_info in machine['phases'].values():
        all_state_names.update(phase_info['states'])

    # Determine initial state (IDEA)
    initial_state = machine['phases']['intent']['states'][0]

    # Create State objects — attribute names are prefixed with st_ to avoid
    # collisions with event names (e.g., PLAN state vs plan action).
    # value= preserves the original uppercase name for current_state_value/start_value.
    attrs: dict = {}
    state_objs: dict[str, State] = {}  # state_name -> State object
    for name in sorted(all_state_names):
        attr_name = f'st_{name.lower()}'
        state_obj = State(
            value=name,
            initial=(name == initial_state),
            final=(name in terminal_states),
        )
        attrs[attr_name] = state_obj
        state_objs[name] = state_obj

    # Identify which (from_state, action) edges are backtracks
    backtrack_edges: set[tuple[str, str]] = set()
    for from_name, edges in machine['transitions'].items():
        for edge in edges:
            if edge.get('backtrack'):
                backtrack_edges.add((from_name, edge['action']))

    # Group transitions by action name for | composition
    # Each entry: action_name -> list of (from_State, to_State, is_backtrack)
    action_edges: dict[str, list[tuple[State, State, bool]]] = defaultdict(list)
    for from_name, edges in machine['transitions'].items():
        for edge in edges:
            action = edge['action']
            event_name = action.replace('-', '_')
            from_state = state_objs[from_name]
            to_state = state_objs[edge['to']]
            is_bt = (from_name, action) in backtrack_edges
            action_edges[event_name].append((from_state, to_state, is_bt))

    # Build transition attributes using .to() and | composition
    # Backtrack edges get cond='backtrack_allowed' as a guard
    for event_name, edges in action_edges.items():
        composed = None
        for from_state, to_state, is_bt in edges:
            if is_bt:
                transition = from_state.to(to_state, cond='backtrack_allowed')
            else:
                transition = from_state.to(to_state)
            if composed is None:
                composed = transition
            else:
                composed = composed | transition
        attrs[event_name] = composed

    # ── Guard: backtrack_allowed ───────────────────────────────────────
    def backtrack_allowed(self):
        """Guard for cross-phase backtrack transitions.

        Returns True by default.  Set suppress_backtracks=True in the
        constructor to block all backtrack transitions.
        """
        return not self._suppress_backtracks

    attrs['backtrack_allowed'] = backtrack_allowed

    # ── Hook: after_transition ─────────────────────────────────────────
    def after_transition(self, event, source, target):
        """Record history and count backtracks after every transition.

        Updates the model (CfaState wrapper) so the caller can read
        the accumulated history and backtrack_count after .send().
        """
        if not hasattr(self, '_cfa_model') or self._cfa_model is None:
            return

        model = self._cfa_model
        source_value = source.value
        target_value = target.value

        # History entry
        model.history.append({
            'state': source_value,
            'action': model.last_action,
            'actor': model.last_actor,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })

        # Backtrack counting
        source_phase = _phase_for(source_value, model.phase_sets)
        target_phase = _phase_for(target_value, model.phase_sets)
        if _PHASE_ORDER.get(target_phase, 0) < _PHASE_ORDER.get(source_phase, 0):
            model.backtrack_count += 1

    attrs['after_transition'] = after_transition

    # ── Custom __init__ ────────────────────────────────────────────────
    def __init__(self, suppress_backtracks=False, **kwargs):
        self._suppress_backtracks = suppress_backtracks
        self._cfa_model = kwargs.pop('cfa_model', None)
        super(CfAMachine, self).__init__(**kwargs)

    attrs['__init__'] = __init__

    # Create the class — note: we need CfAMachine name to be available
    # for the super() call in __init__, so we create it in two steps
    cls = type('CfAMachine', (StateMachine,), attrs)
    return cls


# ── Transition model ───────────────────────────────────────────────────────

class CfATransitionModel:
    """Lightweight model that accumulates side effects during a transition.

    Passed to CfAMachine via cfa_model= so the after_transition hook
    can record history and count backtracks.
    """
    def __init__(self, phase_sets: dict[str, frozenset[str]],
                 last_action: str, last_actor: str):
        self.phase_sets = phase_sets
        self.last_action = last_action
        self.last_actor = last_actor
        self.history: list[dict] = []
        self.backtrack_count: int = 0


# ── Module-level machine class ─────────────────────────────────────────────

_machine_json = _load_machine()
CfAMachine = _build_machine_class(_machine_json)

# Phase sets for external use (transition model, cfa_state.py)
PHASE_SETS = _build_phase_sets(_machine_json)

# Actor lookup: (from_state_name, action) -> actor
# The library doesn't carry arbitrary metadata on transitions,
# so we maintain this as a parallel dict.
TRANSITION_ACTORS: dict[tuple[str, str], str] = {}
for _from_name, _edges in _machine_json['transitions'].items():
    for _edge in _edges:
        TRANSITION_ACTORS[(_from_name, _edge['action'])] = _edge['actor']

# Backtrack edges: set of (from_state, action) pairs that are cross-phase backtracks
BACKTRACK_EDGES: frozenset[tuple[str, str]] = frozenset(
    (_from_name, _edge['action'])
    for _from_name, _edges in _machine_json['transitions'].items()
    for _edge in _edges
    if _edge.get('backtrack')
)
