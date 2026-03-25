"""CfA state machine as a python-statemachine StateMachine class.

Dynamically constructs a StateMachine subclass from the canonical JSON
definition (cfa-state-machine.json).  The resulting CfAMachine class makes
the CfA lifecycle — 25 states across three phases, with cross-phase
backtracks, actor routing, and review gates — visible as a single declared
artifact.

The JSON remains the single source of truth.  This module reads it once at
import time and produces the machine class.  No hand-written duplication.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict

from statemachine import State, StateMachine


# ── Load JSON ──────────────────────────────────────────────────────────────

_MACHINE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'cfa-state-machine.json',
)


def _load_machine(path: str = _MACHINE_FILE) -> dict:
    with open(path) as f:
        return json.load(f)


# ── Factory ────────────────────────────────────────────────────────────────

def _build_machine_class(machine: dict) -> type:
    """Construct a StateMachine subclass from the JSON machine definition.

    Each state in the JSON becomes a State() attribute on the class.
    Each unique action name becomes an event (transition) attribute,
    composed with | for actions that originate from multiple states.
    """
    terminal_states = set(machine.get('terminal_states', []))

    # Collect all states with their phase membership
    all_state_names: set[str] = set()
    for phase_info in machine['phases'].values():
        all_state_names.update(phase_info['states'])

    # Determine initial state (IDEA)
    initial_state = machine['phases']['intent']['states'][0]

    # Create State objects — attribute names are prefixed with st_ to avoid
    # collisions with event names (e.g., PLAN state vs plan action).
    # value= preserves the original uppercase name for current_state_value/start_value.
    attrs: dict[str, State] = {}
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

    # Group transitions by action name for | composition
    # Each entry: action_name -> list of (from_State, to_State)
    action_edges: dict[str, list[tuple[State, State]]] = defaultdict(list)
    for from_name, edges in machine['transitions'].items():
        for edge in edges:
            action = edge['action']
            event_name = action.replace('-', '_')
            from_state = state_objs[from_name]
            to_state = state_objs[edge['to']]
            action_edges[event_name].append((from_state, to_state))

    # Build transition attributes using .to() and | composition
    for event_name, edges in action_edges.items():
        composed = None
        for from_state, to_state in edges:
            transition = from_state.to(to_state)
            if composed is None:
                composed = transition
            else:
                composed = composed | transition
        attrs[event_name] = composed

    # Create the class
    return type('CfAMachine', (StateMachine,), attrs)


# ── Module-level machine class ─────────────────────────────────────────────

_machine_json = _load_machine()
CfAMachine = _build_machine_class(_machine_json)

# Actor lookup: (from_state_name, action) -> actor
# The library doesn't carry arbitrary metadata on transitions,
# so we maintain this as a parallel dict.
TRANSITION_ACTORS: dict[tuple[str, str], str] = {}
for _from_name, _edges in _machine_json['transitions'].items():
    for _edge in _edges:
        TRANSITION_ACTORS[(_from_name, _edge['action'])] = _edge['actor']
