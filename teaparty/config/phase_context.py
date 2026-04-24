"""Phase task context — config-derived prose blocks injected into CfA phases.

Each working CfA phase (``intent`` / ``planning`` / ``execution``) runs
a skill that benefits from project-aware context: norms framed as
constraints, the list of teams the lead may dispatch to, the catalog of
available skills, etc.  The engine *triggers* phase invocation; the
*content* of those context blocks is config-resolution that lives here.

Each function returns a ready-to-inject string, or ``''`` when there is
nothing to add.  The engine concatenates whatever the relevant phase
needs onto the base task — no formatting decisions in the engine, no
YAML schema knowledge in the engine.

These are pure functions over config inputs.  They take what they need
explicitly so they can be tested without standing up an Orchestrator.
"""
from __future__ import annotations

import os
from typing import Mapping


def intent_constraints_block(
    *,
    project_dir: str = '',
    teaparty_home: str = '',
) -> str:
    """Frame project + org norms as constraints for the intent phase.

    Loads norms from the management team and (when ``project_dir`` is
    set) the project team, runs them through ``resolve_norms`` to merge
    + dedupe, and wraps the result in the ``--- Constraints ---``
    block the intent skill expects.  Empty when neither layer has
    norms — the engine then injects nothing.

    Args:
        project_dir: Project repo root.  Empty for OM-level CfAs that
            have no project to load norms from.
        teaparty_home: Optional explicit path to the management
            ``.teaparty/`` directory.  Defaulted by ``load_management_team``.
    """
    from teaparty.config.config_reader import (
        load_management_team,
        load_project_team,
        resolve_norms,
    )

    org_norms: dict[str, list[str]] = {}
    project_norms: dict[str, list[str]] = {}

    try:
        mgmt = (
            load_management_team(teaparty_home=teaparty_home)
            if teaparty_home else load_management_team()
        )
        org_norms = mgmt.norms
    except (FileNotFoundError, OSError):
        pass

    if project_dir:
        try:
            proj = load_project_team(project_dir)
            project_norms = proj.norms
        except (FileNotFoundError, OSError):
            pass

    norms_text = resolve_norms(
        org_norms=org_norms, project_norms=project_norms,
    )
    if not norms_text:
        return ''

    return (
        '\n\n--- Constraints ---\n'
        'The following constraints apply to this project. If the request '
        'would violate any of these constraints, escalate — do not accept '
        'the request as-is. Escalation is the correct response when '
        'constraints cannot be met.\n\n'
        f'{norms_text}\n'
        '--- end ---'
    )


def available_teams_block(
    *,
    project_teams: Mapping[str, object] | None,
    project_workdir: str,
    team_override: str = '',
) -> str:
    """Frame "what teams + skills can the planner reference?" for planning.

    Combines the resolved team roster (from ``PhaseConfig.project_teams``)
    with the available-skills catalog under ``{project_workdir}/skills/``
    and any team-scoped ``{project_workdir}/teams/{team_override}/skills/``.
    Wraps the result in the ``--- Planning Constraints ---`` block the
    planning skill expects.  Empty when neither layer contributes —
    the engine then injects nothing.
    """
    parts: list[str] = []

    if project_teams:
        team_names = sorted(project_teams.keys())
        parts.append(
            'Available teams for dispatch: '
            + ', '.join(team_names) + '.\n'
            'Only reference these teams in the plan. If the task requires '
            'capabilities not covered by these teams, escalate.'
        )

    skills_summary = list_available_skills(
        project_workdir=project_workdir,
        team_override=team_override,
    )
    if skills_summary:
        parts.append(
            'Available skills (learned procedures that can seed the plan):\n'
            + skills_summary
        )

    if not parts:
        return ''

    return (
        '\n\n--- Planning Constraints ---\n'
        + '\n\n'.join(parts)
        + '\n--- end ---'
    )


def list_available_skills(
    *,
    project_workdir: str,
    team_override: str = '',
) -> str:
    """List skill names + descriptions from the project's skills dirs.

    Walks ``{project_workdir}/skills/`` and (when ``team_override`` is
    set) ``{project_workdir}/teams/{team_override}/skills/``, parses
    each ``*.md``'s frontmatter, and returns a newline-joined ``- name:
    description`` summary.  Skills marked ``needs_review: true`` are
    excluded — they aren't safe for the planner to seed plans with.
    Duplicates by name are de-duped, with team-scoped winning over
    project-scoped (it appears first in the lookup order).

    Returns ``''`` when no skills are visible.
    """
    from teaparty.util.skill_lookup import _parse_frontmatter

    skills_dirs: list[tuple[str, str]] = []
    if team_override:
        team_skills = os.path.join(
            project_workdir, 'teams', team_override, 'skills',
        )
        skills_dirs.append(('team', team_skills))
    project_skills = os.path.join(project_workdir, 'skills')
    skills_dirs.append(('project', project_skills))

    seen_names: set[str] = set()
    entries: list[str] = []

    for _scope, dirpath in skills_dirs:
        if not os.path.isdir(dirpath):
            continue
        for filename in sorted(os.listdir(dirpath)):
            if not filename.endswith('.md'):
                continue
            path = os.path.join(dirpath, filename)
            if not os.path.isfile(path):
                continue
            try:
                meta, _ = _parse_frontmatter(path)
            except Exception:
                continue
            if meta.get('needs_review', '').lower() == 'true':
                continue
            name = meta.get('name', filename[:-3])
            if name in seen_names:
                continue
            seen_names.add(name)
            desc = meta.get('description', '')
            entry = f'- {name}'
            if desc:
                entry += f': {desc}'
            entries.append(entry)

    return '\n'.join(entries)
