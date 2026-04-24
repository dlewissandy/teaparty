"""Phase configuration for the CfA engine.

What varies per phase: ``stream_file`` (which .jsonl the lead's events
go to) and ``artifact`` (which file the skill is expected to write).
Everything else — ``agent_file='uber'``, ``lead='project-lead'``,
``permission_mode='acceptEdits'``, ``approval_state`` (phase name
uppercased) — is the same across all three phases.  Previously these
lived in ``phase-config.json`` as if they might vary.  They're
literal constants now.

Teams (dispatch workgroups) are listed here too: a small fixed set
of slugs used by withdraw / pause / summarize walkers and by the
agent-JSON resolver.  This is a snapshot; workgroup membership lives
in ``.teaparty/project/workgroups/*.yaml``.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


# ── Phase table (literal — used to be loaded from phase-config.json) ──────

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


@dataclass
class TeamSpec:
    """Configuration for a dispatch team."""
    name: str
    agent_file: str
    lead: str
    planning_permission_mode: str = ''
    execution_model: str = 'worktree'


# The three phases are uniform except for stream_file + artifact.
# Defaults common to all phases are set once here; any future
# divergence only changes the outlier.
_PHASE_DEFAULTS = dict(
    agent_file='uber',
    lead='project-lead',
    permission_mode='acceptEdits',
)
_PHASES: dict[str, PhaseSpec] = {
    name: PhaseSpec(
        name=name, **_PHASE_DEFAULTS,
        stream_file=stream,
        artifact=artifact,
        approval_state=name.upper() if name != 'execution' else 'EXECUTE',
    )
    for name, stream, artifact in (
        ('intent',    '.intent-stream.jsonl', 'INTENT.md'),
        ('planning',  '.plan-stream.jsonl',   'PLAN.md'),
        ('execution', '.exec-stream.jsonl',   None),
    )
}

# Dispatch teams.  Kept compact; most fields repeat per entry.
# ``execution_model='direct'`` is the only non-default — configuration
# team runs in-place instead of through a per-session worktree.
_TEAMS: dict[str, TeamSpec] = {
    name: TeamSpec(
        name=name, agent_file=name, lead=f'{name}-lead',
        planning_permission_mode='plan',
        execution_model=execution_model,
    )
    for name, execution_model in (
        ('art',           'worktree'),
        ('writing',       'worktree'),
        ('editorial',     'worktree'),
        ('research',      'worktree'),
        ('coding',        'worktree'),
        ('configuration', 'direct'),
    )
}

_DEFAULT_STALL_TIMEOUT = 1800
_DEFAULT_MAX_DISPATCH_RETRIES = 5


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
        self._project_lead: str = ''
        self.stall_timeout: int = 1800
        self.max_dispatch_retries: int = 5

        # Derived from state machine — not hardcoded
        self.valid_actions_by_state: dict[str, list[str]] = {}
        self.phase_for_state: dict[str, str] = {}

        self._load()

    def _load(self) -> None:
        self._load_phase_config()
        self._load_state_machine()
        self._load_project_config()
        self._load_project_claude_md()

    def _load_phase_config(self) -> None:
        """Copy the literal phase and team tables into instance state."""
        self._phases = dict(_PHASES)
        self._teams = dict(_TEAMS)
        self.stall_timeout = _DEFAULT_STALL_TIMEOUT
        self.max_dispatch_retries = _DEFAULT_MAX_DISPATCH_RETRIES

    def _load_state_machine(self) -> None:
        """Copy computed properties out of the cfa_state constants.

        Previously this read ``cfa-state-machine.json``; the JSON is
        gone — the state machine is literal constants in
        ``teaparty.cfa.statemachine.cfa_state``.  These two dicts
        remain as ``PhaseConfig`` fields for the handful of callers
        that reach them through ``config``; they're just projections
        of ``TRANSITIONS`` / ``phase_for_state``.
        """
        from teaparty.cfa.statemachine.cfa_state import (
            TRANSITIONS, phase_for_state,
        )
        for state in TRANSITIONS:
            self.phase_for_state[state] = phase_for_state(state)
            self.valid_actions_by_state[state] = [
                action for action, _target, _actor in TRANSITIONS[state]
            ]

    def _load_project_config(self) -> None:
        """Load project-scoped config from project.yaml (lead) and project.json (overrides)."""
        if not self.project_dir:
            return

        # Load project lead from project.yaml — the canonical project config.
        # This is the same file the bridge reads via load_project_team() (Issue #408).
        yaml_path = os.path.join(
            self.project_dir, '.teaparty', 'project', 'project.yaml',
        )
        if os.path.exists(yaml_path):
            try:
                import yaml as _yaml
                with open(yaml_path) as f:
                    data = _yaml.safe_load(f)
                if data and isinstance(data, dict):
                    self._project_lead = data.get('lead', '') or ''
            except Exception:
                pass

        # Legacy: project.json phase/team overrides (no project currently has one).
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
        """Load org-level agent definitions for a team from .teaparty/ format.

        Reads the workgroup YAML to get lead + member agents, then reads
        each agent's agent.md to compose a dict matching the --agents JSON
        format: {name: {description, prompt, model, maxTurns, disallowedTools}}.
        """
        if team_name in self._org_agents:
            return self._org_agents[team_name]

        team_spec = self._teams.get(team_name)
        if not team_spec:
            return {}

        # Try .teaparty/project/agents/ format first
        agents = self._load_agents_from_teaparty(team_name, team_spec)
        if agents:
            self._org_agents[team_name] = agents
            return agents

        # Fallback: legacy agents/*.json (for backward compat during migration)
        if team_spec.agent_file:
            agent_path = os.path.join(self.poc_root, team_spec.agent_file)
            if os.path.exists(agent_path):
                with open(agent_path) as f:
                    agents = json.load(f)
                self._org_agents[team_name] = agents
                return agents

        return {}

    def _load_agents_from_teaparty(self, team_name: str, team_spec: 'TeamSpec') -> dict[str, Any]:
        """Load agent definitions from .teaparty/project/ format."""
        import yaml

        wg_path = os.path.join(
            self.poc_root, '.teaparty', 'project', 'workgroups', f'{team_name}.yaml',
        )
        if not os.path.isfile(wg_path):
            return {}

        with open(wg_path) as f:
            wg = yaml.safe_load(f)
        if not wg:
            return {}

        # Collect agent names: lead + members
        agent_names = []
        lead = wg.get('lead', '')
        if lead:
            agent_names.append(lead)
        members = wg.get('members', {})
        agent_names.extend(members.get('agents', []))

        agents_base = os.path.join(self.poc_root, '.teaparty', 'project', 'agents')
        agents: dict[str, Any] = {}
        for name in agent_names:
            agent_md = os.path.join(agents_base, name, 'agent.md')
            if not os.path.isfile(agent_md):
                continue
            agent_def = self._parse_agent_md(agent_md)
            if agent_def:
                agents[name] = agent_def

        return agents

    @staticmethod
    def _parse_agent_md(path: str) -> dict[str, Any] | None:
        """Parse an agent.md file into the --agents JSON format."""
        import yaml

        with open(path) as f:
            content = f.read()

        if not content.startswith('---'):
            return None

        parts = content.split('---', 2)
        if len(parts) < 3:
            return None

        fm = yaml.safe_load(parts[1])
        if not fm:
            return None

        prompt = parts[2].strip()

        result: dict[str, Any] = {
            'description': fm.get('description', ''),
            'prompt': prompt,
            'model': fm.get('model', 'sonnet'),
        }
        if 'maxTurns' in fm:
            result['maxTurns'] = fm['maxTurns']
        if 'timeout' in fm:
            result['timeout'] = fm['timeout']
        if 'disallowedTools' in fm:
            result['disallowedTools'] = fm['disallowedTools']

        return result

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

    def resolve_agents_json(self, team_name: str) -> str:
        """Produce the JSON string for a team's agents, suitable for --agents."""
        agents = self.resolve_team_agents(team_name)
        if not agents:
            return ''
        return json.dumps(agents)

    def resolve_phase(self, phase_name: str) -> PhaseSpec:
        """Resolve a PhaseSpec with project overrides applied.

        Resolution order:
          1. Org defaults from phase-config.json.
          2. Project.json phase overrides (legacy, no project currently uses this).
          3. Project lead from project.yaml: substituted when the org default is
             the generic 'project-lead' sentinel (Issue #408).

        Intent, planning, and execution phases all use the generic
        'project-lead' sentinel in phase-config.json and get substituted
        for the project's actual lead (e.g. 'joke-book-lead'). One agent
        carries the job across all three phases; skills differentiate the
        phase-specific behaviour.
        """
        base = self._phases[phase_name]

        # Apply legacy project.json phase overrides if present.
        project_phases = self._project_config.get('phases', {})
        overrides = project_phases.get(phase_name, {})
        if overrides:
            base = PhaseSpec(
                name=base.name,
                agent_file=overrides.get('agent_file', base.agent_file),
                lead=overrides.get('lead', base.lead),
                permission_mode=overrides.get('permission_mode', base.permission_mode),
                stream_file=base.stream_file,
                artifact=base.artifact,
                approval_state=base.approval_state,
            )

        # Substitute project lead from project.yaml when the phase uses the generic
        # 'project-lead' sentinel and the project has a configured lead (Issue #408).
        if base.lead == 'project-lead' and self._project_lead:
            base = PhaseSpec(
                name=base.name,
                agent_file=base.agent_file,
                lead=self._project_lead,
                permission_mode=base.permission_mode,
                stream_file=base.stream_file,
                artifact=base.artifact,
                approval_state=base.approval_state,
            )

        return base

    @property
    def project_lead(self) -> str:
        """The project's configured lead agent name, or empty string if not set."""
        return self._project_lead

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


def get_team_names(poc_root: str | None = None) -> tuple[str, ...]:
    """Return dispatch team slugs.

    Used by bridge and orchestrator code that needs to scan dispatch
    directories without constructing a full PhaseConfig.  The
    ``poc_root`` parameter is accepted for API compatibility with
    legacy callers but no longer used — the team list is a constant.
    """
    return tuple(_TEAMS.keys())
