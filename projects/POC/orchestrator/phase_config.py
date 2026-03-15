"""Phase configuration loader.

Loads phase-config.json and derives computed properties from the CfA
state machine definition — no hardcoded state sets.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PhaseSpec:
    """Configuration for a single CfA phase."""
    name: str
    agent_file: str
    lead: str
    permission_mode: str
    stream_file: str
    artifact: str | None
    approval_state: str
    settings_overlay: dict[str, Any] = field(default_factory=dict)


@dataclass
class TeamSpec:
    """Configuration for a dispatch team."""
    name: str
    agent_file: str
    lead: str
    planning_permission_mode: str = ''


class PhaseConfig:
    """Unified configuration derived from phase-config.json + cfa-state-machine.json."""

    def __init__(self, poc_root: str):
        self.poc_root = poc_root
        self._phases: dict[str, PhaseSpec] = {}
        self._teams: dict[str, TeamSpec] = {}
        self.stall_timeout: int = 1800
        self.max_dispatch_retries: int = 5

        # Derived from state machine — not hardcoded
        self.human_actor_states: frozenset[str] = frozenset()
        self.approval_gate_successors: dict[str, str] = {}
        self.valid_actions_by_state: dict[str, list[str]] = {}
        self.phase_for_state: dict[str, str] = {}

        self._load()

    def _load(self) -> None:
        self._load_phase_config()
        self._load_state_machine()

    def _load_phase_config(self) -> None:
        path = os.path.join(os.path.dirname(__file__), 'phase-config.json')
        with open(path) as f:
            raw = json.load(f)

        for name, spec in raw['phases'].items():
            self._phases[name] = PhaseSpec(
                name=name,
                agent_file=spec['agent_file'],
                lead=spec['lead'],
                permission_mode=spec['permission_mode'],
                stream_file=spec['stream_file'],
                artifact=spec.get('artifact'),
                approval_state=spec['approval_state'],
                settings_overlay=spec.get('settings_overlay', {}),
            )

        for name, spec in raw.get('teams', {}).items():
            self._teams[name] = TeamSpec(
                name=name,
                agent_file=spec['agent_file'],
                lead=spec['lead'],
                planning_permission_mode=spec.get('planning_permission_mode', ''),
            )

        self.stall_timeout = raw.get('stall_timeout_seconds', 1800)
        self.max_dispatch_retries = raw.get('max_dispatch_retries', 5)

    def _load_state_machine(self) -> None:
        """Derive computed properties from cfa-state-machine.json."""
        path = os.path.join(self.poc_root, 'cfa-state-machine.json')
        with open(path) as f:
            machine = json.load(f)

        # Build phase-for-state mapping
        for phase_name, phase_def in machine['phases'].items():
            for state in phase_def['states']:
                self.phase_for_state[state] = phase_name

        # Derive human-actor states: states where ALL outgoing transitions
        # have actor in ('human', 'approval_gate').
        human_states = set()
        for state, edges in machine['transitions'].items():
            if not edges:
                continue  # terminal states
            actors = {e['actor'] for e in edges}
            if actors <= {'human', 'approval_gate'}:
                human_states.add(state)
        self.human_actor_states = frozenset(human_states)

        # Derive approval gate successors: for each *_ASSERT state,
        # the 'approve' action's target.
        for state, edges in machine['transitions'].items():
            for edge in edges:
                if edge['action'] == 'approve':
                    self.approval_gate_successors[state] = edge['to']

        # Valid actions per state (for review classification)
        for state, edges in machine['transitions'].items():
            self.valid_actions_by_state[state] = [e['action'] for e in edges]

    def phase(self, name: str) -> PhaseSpec:
        return self._phases[name]

    def team(self, name: str) -> TeamSpec:
        return self._teams[name]

    @property
    def phases(self) -> dict[str, PhaseSpec]:
        return dict(self._phases)

    @property
    def teams(self) -> dict[str, TeamSpec]:
        return dict(self._teams)

    def resolve_agent_path(self, agent_file: str) -> str:
        """Resolve a relative agent file path against poc_root."""
        return os.path.join(self.poc_root, agent_file)
