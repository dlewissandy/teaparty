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
    execution_model: str = 'worktree'


class PhaseConfig:
    """Unified configuration derived from phase-config.json + cfa-state-machine.json.

    Optionally layered with project-scoped overrides from project_dir/project.json.
    Resolution order: org defaults → project overrides.
    """

    def __init__(self, poc_root: str, project_dir: str | None = None):
        self.poc_root = poc_root
        self.project_dir = project_dir
        self._phases: dict[str, PhaseSpec] = {}
        self._teams: dict[str, TeamSpec] = {}
        self._project_config: dict[str, Any] = {}
        self._org_agents: dict[str, dict[str, Any]] = {}
        self._project_claude_md: str = ''
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
        self._load_project_config()
        self._load_project_claude_md()

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
                execution_model=spec.get('execution_model', 'worktree'),
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

    def _load_project_config(self) -> None:
        """Load project-scoped team config from project_dir/project.json."""
        if not self.project_dir:
            return
        path = os.path.join(self.project_dir, 'project.json')
        if not os.path.exists(path):
            return
        with open(path) as f:
            self._project_config = json.load(f)

    def _load_project_claude_md(self) -> None:
        """Load project rules from .teaparty/project/project.md if it exists."""
        if not self.project_dir:
            return
        path = os.path.join(self.project_dir, '.teaparty', 'project', 'project.md')
        try:
            with open(path) as f:
                self._project_claude_md = f.read()
        except (FileNotFoundError, OSError):
            pass

    def _load_org_agents(self, team_name: str) -> dict[str, Any]:
        """Load the org-level agent definitions for a team."""
        if team_name in self._org_agents:
            return self._org_agents[team_name]
        team_spec = self._teams.get(team_name)
        if not team_spec:
            return {}
        agent_path = os.path.join(self.poc_root, team_spec.agent_file)
        if not os.path.exists(agent_path):
            return {}
        with open(agent_path) as f:
            agents = json.load(f)
        self._org_agents[team_name] = agents
        return agents

    @property
    def project_teams(self) -> dict[str, TeamSpec]:
        """Teams available to the current project.

        If a project config exists with a 'teams' key, returns only those
        teams that are both listed in the project config and defined in the
        org catalogue.  Otherwise returns all org teams.
        """
        project_team_names = self._project_config.get('teams')
        if project_team_names is None:
            return dict(self._teams)
        return {
            name: spec
            for name, spec in self._teams.items()
            if name in project_team_names
        }

    @property
    def project_claude_md(self) -> str:
        """Project-scoped CLAUDE.md content, or empty string if none."""
        return self._project_claude_md

    def resolve_team_spec(self, team_name: str) -> TeamSpec:
        """Resolve a TeamSpec with project overrides applied.

        Handles planning_permission_mode override from project config.
        """
        import copy
        base = self._teams.get(team_name)
        if not base:
            raise KeyError(f'Unknown team: {team_name}')
        result = copy.copy(base)
        project_teams = self._project_config.get('teams', {})
        team_overrides = project_teams.get(team_name, {})
        if 'planning_permission_mode' in team_overrides:
            result.planning_permission_mode = team_overrides['planning_permission_mode']
        return result

    def resolve_phase(self, phase_name: str) -> PhaseSpec:
        """Resolve a PhaseSpec with project overrides applied.

        Project config can override agent_file, lead, permission_mode,
        and settings_overlay per phase.  Unoverridden fields keep org defaults.
        """
        base = self._phases[phase_name]
        project_phases = self._project_config.get('phases', {})
        overrides = project_phases.get(phase_name, {})
        if not overrides:
            return base
        return PhaseSpec(
            name=base.name,
            agent_file=overrides.get('agent_file', base.agent_file),
            lead=overrides.get('lead', base.lead),
            permission_mode=overrides.get('permission_mode', base.permission_mode),
            stream_file=base.stream_file,
            artifact=base.artifact,
            approval_state=base.approval_state,
            settings_overlay=overrides.get('settings_overlay', base.settings_overlay),
        )

    def resolve_team_agents(self, team_name: str) -> dict[str, dict[str, Any]]:
        """Resolve agent definitions for a team with project overrides applied.

        Resolution order: org defaults → project overrides.
        - model: project value replaces org value
        - prompt_addition: appended to org prompt with newline separator
        - disallowedTools: project value replaces org value
        """
        org_agents = self._load_org_agents(team_name)
        if not org_agents:
            return {}

        # Deep copy to avoid mutating cached org definitions
        import copy
        resolved = copy.deepcopy(org_agents)

        # Apply project overrides if they exist
        project_teams = self._project_config.get('teams', {})
        team_overrides = project_teams.get(team_name, {})
        agent_overrides = team_overrides.get('agent_overrides', {})

        for agent_name, overrides in agent_overrides.items():
            if agent_name not in resolved:
                continue
            agent = resolved[agent_name]
            if 'model' in overrides:
                agent['model'] = overrides['model']
            if 'prompt_addition' in overrides:
                agent['prompt'] = agent.get('prompt', '') + '\n\n' + overrides['prompt_addition']
            if 'disallowedTools' in overrides:
                agent['disallowedTools'] = overrides['disallowedTools']
            if 'allowedTools' in overrides:
                agent['allowedTools'] = overrides['allowedTools']
            if 'permission_mode' in overrides:
                agent['permission_mode'] = overrides['permission_mode']

        return resolved

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


_team_names_cache: tuple[str, ...] | None = None


def get_team_names(poc_root: str | None = None) -> tuple[str, ...]:
    """Return team names from phase-config.json, cached after first load.

    Used by bridge and orchestrator code that needs to scan dispatch
    directories without constructing a full PhaseConfig.
    """
    global _team_names_cache
    if _team_names_cache is not None:
        return _team_names_cache

    if poc_root is None:
        from orchestrator import find_poc_root
        poc_root = find_poc_root()

    config_path = os.path.join(poc_root, 'orchestrator', 'phase-config.json')
    try:
        with open(config_path) as f:
            config = json.load(f)
        _team_names_cache = tuple(config.get('teams', {}).keys())
    except (OSError, json.JSONDecodeError):
        _team_names_cache = ()
    return _team_names_cache
