"""Unified agent launcher — one codepath, config-driven, SLA-compliant.

Every agent in TeaParty launches through the functions in this module.
The launcher reads .teaparty/ config and produces the correct ``claude -p``
invocation.  No special cases, no alternative paths.

Design: docs/systems/workspace/unified-launch.md
Issue: #394
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

import yaml

from teaparty.runners.claude import ClaudeResult
from teaparty.telemetry import events as _telem_events
from teaparty.telemetry import record_event


# ── Baseline deny rules ──────────────────────────────────────────────────────

# System-wide permission.deny rules injected into every agent's settings.
# Deny takes precedence over allow in Claude Code's permission model, so
# these rules hold even when an agent has a broad tool like bare ``Bash``
# or ``Edit`` in ``permissions.allow``.
#
# Scope of protection:
# - Destructive / exfil shell: rm -rf, sudo, pipe-to-shell installs.
# - Config tampering: writes to .claude/ (Claude Code config) and to the
#   management / project tiers of .teaparty/ (tool permissions live there;
#   letting an agent edit those would defeat this entire control). The
#   rules deliberately spare .teaparty/jobs/ so agents can still read and
#   write within their own job worktree.
BASELINE_DENY_RULES: tuple[str, ...] = (
    # Destructive shell
    'Bash(rm -rf *)',
    'Bash(rm -fr *)',
    'Bash(sudo *)',
    'Bash(chmod -R *)',
    # Pipe-to-shell (exfil / unreviewed install)
    'Bash(curl * | *sh*)',
    'Bash(curl * | bash*)',
    'Bash(wget * | *sh*)',
    'Bash(wget * | bash*)',
    # Claude Code config tampering — deny writes to the files that could
    # change agent behaviour. Deliberately spares .claude/skills/ so the
    # launcher-symlinked skills remain loadable, and leaves read access
    # unrestricted so skill discovery works.
    'Edit(*/.claude/settings.json)',
    'Edit(*/.claude/settings.local.json)',
    'Edit(*/.claude/agents/**)',
    'Edit(*/.claude/hooks/**)',
    'Edit(*/.claude/mcp.json)',
    'Write(*/.claude/settings.json)',
    'Write(*/.claude/settings.local.json)',
    'Write(*/.claude/agents/**)',
    'Write(*/.claude/hooks/**)',
    'Write(*/.claude/mcp.json)',
    # TeaParty config tampering — agent definitions, skill bodies,
    # workgroup rosters, and the top-level YAMLs are the load-bearing
    # config that an agent could rewrite to alter its own behaviour or
    # escape its sandbox.  Worktrees of dispatched tasks live under
    # ``.teaparty/management/sessions/`` and ``.teaparty/project/sessions/``,
    # and CfA-job worktrees live under ``.teaparty/jobs/`` — none of
    # those are denied here, so an agent can write its own deliverables.
    # Avoid broad ``*/.teaparty/management/**`` patterns: they catch
    # session worktrees too, and prompt the user on every in-tree write.
    'Edit(*/.teaparty/management/agents/**)',
    'Edit(*/.teaparty/management/skills/**)',
    'Edit(*/.teaparty/management/workgroups/**)',
    'Edit(*/.teaparty/management/teaparty.yaml)',
    'Edit(*/.teaparty/management/settings.yaml)',
    'Edit(*/.teaparty/management/external-projects.yaml)',
    'Edit(*/.teaparty/project/agents/**)',
    'Edit(*/.teaparty/project/skills/**)',
    'Edit(*/.teaparty/project/workgroups/**)',
    'Edit(*/.teaparty/project/project.yaml)',
    'Edit(*/.teaparty/project/settings.yaml)',
    'Edit(*/.teaparty/teaparty.yaml)',
    'Write(*/.teaparty/management/agents/**)',
    'Write(*/.teaparty/management/skills/**)',
    'Write(*/.teaparty/management/workgroups/**)',
    'Write(*/.teaparty/management/teaparty.yaml)',
    'Write(*/.teaparty/management/settings.yaml)',
    'Write(*/.teaparty/management/external-projects.yaml)',
    'Write(*/.teaparty/project/agents/**)',
    'Write(*/.teaparty/project/skills/**)',
    'Write(*/.teaparty/project/workgroups/**)',
    'Write(*/.teaparty/project/project.yaml)',
    'Write(*/.teaparty/project/settings.yaml)',
    'Write(*/.teaparty/teaparty.yaml)',
)


# Baseline allow rules — explicit permission grants added to every
# agent's settings at launch. These cover paths Claude Code may
# implicitly prompt for even when a bare tool name is in allow (e.g.
# reading its own .claude/ config when loading skills).
#
# The four messaging primitives are minimum-complement for any agent
# that participates in the dispatch protocol: ``Send`` to delegate or
# reply, ``AskQuestion`` to escalate to the proxy/human, and
# ``ListTeamMembers`` / ``CloseConversation`` for leads that route
# work and tear down threads.  Hand-replicating these in every
# lead's per-agent settings.yaml — as the codebase did before — is
# brittle: one accidental edit silently breaks a lead's ability to
# send messages, find team members, ask questions, or close threads.
# Putting them in the baseline turns the minimum complement into a
# structural guarantee.  Specialist members get them too; that's
# fine — the deny list still gates anything they shouldn't write to,
# and a specialist needs ``Send`` to ``Reply`` to its dispatcher
# regardless.
BASELINE_ALLOW_RULES: tuple[str, ...] = (
    'Read(*/.claude/**)',
    'Read(*/.claude/skills/**)',
    # Skill is the built-in tool agents use to invoke skills in
    # headless mode. Without this, the agent sees skills listed in its
    # frontmatter but can't run them — the CLI prompts for permission
    # on every Skill call.
    'Skill',
    # Messaging primitives — minimum complement for any dispatch
    # participant.  See module-level comment above for rationale.
    'mcp__teaparty-config__Send',
    'mcp__teaparty-config__AskQuestion',
    'mcp__teaparty-config__ListTeamMembers',
    'mcp__teaparty-config__CloseConversation',
)
# ``Delegate`` is intentionally NOT in this baseline.  It is granted
# role-conditionally by ``_role_implied_tools``: an agent gets
# Delegate when its team roster contains members of role
# ``project-lead`` or ``workgroup-lead`` (i.e. the agent dispatches
# to recipients that run their own workflow skill on launch).
# Workgroup-leads (whose members are all ``workgroup-agent``) and
# specialists (no team) get only ``Send``.




def _inject_baseline_deny(settings: dict) -> None:
    """Merge the baseline deny / allow lists and disable auto-memory.

    Appends without duplicates so a project can add its own entries
    alongside the baseline. Called by every launch path so agents never
    see a settings file without these rules.

    Auto-memory is disabled because Claude Code stores it under
    ``<CLAUDE_CONFIG_DIR>/projects/<cwd-hash>/memory/`` — outside the
    agent's worktree cwd. The cwd sandbox refuses access; the agent
    sees a permission failure on what should be transparent state. The
    engine already manages session state via ``.cfa-state.json`` and
    worktree files; agents do not need cross-session auto-memory on
    top of that.
    """
    perms = settings.get('permissions') or {}

    existing_deny = list(perms.get('deny') or [])
    seen_deny = set(existing_deny)
    for rule in BASELINE_DENY_RULES:
        if rule not in seen_deny:
            existing_deny.append(rule)
            seen_deny.add(rule)
    perms['deny'] = existing_deny

    existing_allow = list(perms.get('allow') or [])
    seen_allow = set(existing_allow)
    for rule in BASELINE_ALLOW_RULES:
        if rule not in seen_allow:
            existing_allow.append(rule)
            seen_allow.add(rule)
    perms['allow'] = existing_allow

    settings['permissions'] = perms
    settings['autoMemoryEnabled'] = False


def _inject_role_implied_tools(
    settings: dict, *, agent_name: str, teaparty_home: str,
) -> None:
    """Merge role-conditional tool grants into ``permissions.allow``.

    Called by every compose path after ``_inject_baseline_deny`` so the
    universal baseline lands first and role-specific tools layer on
    top.  See ``_role_implied_tools`` for the role rule.
    """
    extras = _role_implied_tools(
        agent_name=agent_name, teaparty_home=teaparty_home,
    )
    if not extras:
        return
    perms = settings.get('permissions') or {}
    existing_allow = list(perms.get('allow') or [])
    seen_allow = set(existing_allow)
    for rule in extras:
        if rule not in seen_allow:
            existing_allow.append(rule)
            seen_allow.add(rule)
    perms['allow'] = existing_allow
    settings['permissions'] = perms


# Layer 3 — path-scoping bare ``Write``/``Edit``/``NotebookEdit`` grants
# to the worktree — was deliberately removed.  It was defense-in-depth
# on top of the worktree-jail hook (layer 4) and the deny patterns
# (layer 2), but its safety contribution depended on Claude Code's
# permission-pattern matcher exactly normalising paths the same way
# the agent did.  In practice the matcher's quirks (symlink resolution
# differences on macOS where ``/var`` resolves to ``/private/var``,
# absolute-vs-relative comparison, glob-anchor edge cases) caused
# in-tree writes to fall through to permission prompts.  Workers
# blocked on prompts that the user couldn't see, exited their turn
# with "I'm blocked on permission," and the dispatch tree stalled.
#
# Bare ``Write`` / ``Edit`` are now passed through to Claude CLI
# unchanged.  Out-of-tree writes are stopped by the PreToolUse
# worktree-jail hook (registered at compose time).  Catalog writes
# are stopped by ``BASELINE_DENY_RULES``.  The worktree's git
# isolation is the underlying boundary.  Three layers of protection
# remain; the brittle middle layer is gone.


# ── Data ─────────────────────────────────────────────────────────────────────

@dataclass
class Session:
    """An agent session — 1:1 with a Claude session ID.

    Three launch modes live in this dataclass:

    - **Privileged top-level chat** (OM, a project lead as top-level of
      its project's chat): ``launch_cwd`` is the real repo root; no
      worktree fields are set; no merge target.

    - **Dispatched chat** (everyone else that runs in a subchat):
      ``worktree_path`` is the per-session worktree dir on branch
      ``worktree_branch`` (``session/{session_id}``). The merge_target_*
      fields record where ``CloseConversation`` must squash-merge the
      session branch back to. For same-repo dispatches the target is
      the dispatcher's worktree/branch (the dispatcher's working state
      is the integration branch). For the cross-repo exception (OM
      dispatches a project lead whose repo differs) the target is the
      project repo's **default branch**, in the project's main checkout.

    - **CfA job**: ``launch_cwd`` holds the worktree path (legacy field
      name); merge_target fields empty. The CfA engine owns its
      worktree lifecycle separately from CloseConversation.
    """
    id: str
    path: str
    agent_name: str
    scope: str
    claude_session_id: str = ''
    launch_cwd: str = ''
    worktree_path: str = ''
    worktree_branch: str = ''
    merge_target_repo: str = ''
    merge_target_branch: str = ''
    merge_target_worktree: str = ''
    # Execution phase — written continuously by the subtree loop so that
    # a pause (task cancellation) lands with an accurate snapshot.
    # One of 'launching', 'awaiting', 'complete'.
    phase: str = 'launching'
    # Final integrated reply text — populated on normal loop exit so a
    # resumed parent can collect a 'complete' child's answer without
    # re-running any LLM work.
    response_text: str = ''
    # The project this session belongs to (slug). Empty for management
    # sessions. Used by pause/resume to scope subtree walks.
    project_slug: str = ''
    # Parent session id for on-disk tree walking. Empty at the root.
    parent_session_id: str = ''
    # The message currently being processed. Persisted at the start of
    # each turn so a launching-phase resume can re-run that turn via
    # --resume with the same input. The in-flight grandchild ids at the
    # time the session entered 'awaiting' are needed by the resume
    # walker to rebuild the task chain.
    current_message: str = ''
    in_flight_gc_ids: list[str] = field(default_factory=list)
    # Dispatcher's initial input to this session (the `composite` used
    # on the first _launch). Retained so a launching-phase resume of
    # the very first turn has the original prompt to re-run.
    initial_message: str = ''


# ── Agent definition resolution ──────────────────────────────────────────────

def resolve_agent_definition(
    agent_name: str,
    scope: str,
    teaparty_home: str,
    *,
    org_home: str | None = None,
) -> str:
    """Resolve the agent definition path: scope-first, fall back to management.

    Search order:
      1. {teaparty_home}/{scope}/agents/{agent_name}/agent.md
      2. {teaparty_home}/management/agents/{agent_name}/agent.md
      3. {org_home}/management/agents/{agent_name}/agent.md  (if org_home differs)

    The org_home parameter supports CfA project jobs, where teaparty_home is
    the project's .teaparty/ directory and the org-level management catalog
    lives at {poc_root}/.teaparty/ (Issue #408).

    Returns the absolute path to the agent.md file.

    Raises:
        FileNotFoundError: If no agent definition exists in any search location.
    """
    # 1. Scope-specific path in primary home
    scope_path = os.path.join(
        teaparty_home, scope, 'agents', agent_name, 'agent.md',
    )
    if os.path.isfile(scope_path):
        return scope_path

    # 2. Management fallback in primary home (unless already looking there)
    if scope != 'management':
        mgmt_path = os.path.join(
            teaparty_home, 'management', 'agents', agent_name, 'agent.md',
        )
        if os.path.isfile(mgmt_path):
            return mgmt_path

    # 3. Org management catalog (CfA project jobs: project home ≠ org home)
    if org_home and os.path.normpath(org_home) != os.path.normpath(teaparty_home):
        org_mgmt_path = os.path.join(
            org_home, 'management', 'agents', agent_name, 'agent.md',
        )
        if os.path.isfile(org_mgmt_path):
            return org_mgmt_path

    raise FileNotFoundError(
        f'No agent definition for {agent_name!r} in scope {scope!r} '
        f'at {teaparty_home!r}'
        + (f' or org management at {org_home!r}' if org_home else '')
    )


# ── Skill staging (shared by chat-tier and worktree-tier launches) ──────────

def _role_implied_tools(
    *, agent_name: str, teaparty_home: str,
) -> list[str]:
    """Return tool names implied by the agent's role (issue #423).

    ``mcp__teaparty-config__Delegate`` is granted only to agents whose
    team roster contains at least one member of role ``project-lead``
    or ``workgroup-lead`` — i.e. agents that dispatch to recipients
    that run their own workflow skill on launch.  The OM and project-
    leads qualify; workgroup-leads (whose members are all
    ``workgroup-agent``) and specialists do not.

    The rule comes directly from how Delegate is supposed to work:
    its ``skill=`` parameter prescribes the workflow rail at the
    *recipient*.  If the recipient runs no workflow, the dispatcher
    has no use for Delegate's distinguishing feature; it should use
    ``Send`` instead.  Making Delegate structurally unavailable to
    workgroup-leads removes the off-ramp that let research-lead pass
    ``skill='attempt-task'`` to a specialist in live joke-book runs.

    Returns ``[]`` for any agent the roster does not identify as a
    lead-dispatching agent, including agents whose roster lookup
    fails — callers append nothing in that case.
    """
    try:
        from teaparty.config.roster import derive_team_roster
        roster = derive_team_roster(agent_name, teaparty_home)
    except Exception:
        return []
    if roster is None or not roster.members:
        return []
    if any(
        m.role in ('project-lead', 'workgroup-lead')
        for m in roster.members
    ):
        return ['mcp__teaparty-config__Delegate']
    return []


def _role_implied_skills(
    *, agent_name: str, teaparty_home: str,
) -> list[str]:
    """Return skill names implied by the agent's role (issue #423).

    A workgroup-lead's procedural rails live in the ``attempt-task``
    skill — when ``Delegate(skill='attempt-task')`` lands at a
    workgroup-lead, that slash command must resolve.  Auto-staging
    the skill for every agent the roster identifies as a
    workgroup-lead removes the per-agent frontmatter edit and keeps
    the role-vs-skill mapping in one place.

    Detection: ``derive_team_roster(agent_name)`` returns the team
    headed by this agent.  Workgroup-leads head teams whose direct
    members are ``workgroup-agent``; project-leads head teams whose
    members are ``workgroup-lead``; the OM heads a team of
    project-leads + management workgroup-leads + proxy.  The
    member-role check distinguishes a workgroup-lead unambiguously
    without parsing names.

    Returns ``[]`` for any agent the roster does not identify as a
    workgroup-lead, including agents the roster lookup fails for —
    callers append nothing in that case.
    """
    try:
        from teaparty.config.roster import derive_team_roster
        roster = derive_team_roster(agent_name, teaparty_home)
    except Exception:
        return []
    if roster is None or not roster.members:
        return []
    if any(m.role == 'workgroup-agent' for m in roster.members):
        return ['attempt-task']
    return []


def _stage_skills(
    *,
    allowed_skills: list[str],
    worktree_skills_dest: str,
    scope: str,
    teaparty_home: str,
    org_home: str | None = None,
) -> None:
    """Stage an agent's declared skills for a Claude Code launch.

    Skills are staged in two places:

    1. ``<worktree_skills_dest>/<name>/`` — project-local copy (only when
       the caller supplies a writable destination, i.e. the dispatch-tier
       path that composes a worktree).  Chat-tier launches pass ``''``
       here since there is no per-launch worktree to populate.
    2. ``$CLAUDE_CONFIG_DIR/skills/<name>/`` — the location Claude Code's
       headless ``Skill`` tool actually discovers from. In ``claude -p``
       the cwd's ``.claude/skills/`` is not on the discovery path; without
       this copy the agent sees its frontmatter-declared skill listed
       in the system prompt but ``/<name>`` fails with
       "Unknown skill: <name>".  Writes are idempotent (same source,
       same content) across concurrent launches.

    When ``allowed_skills`` is empty both destinations are left untouched
    beyond cleaning ``worktree_skills_dest``.
    """
    # Clean the per-launch worktree skills dir; the CLAUDE_CONFIG_DIR one
    # is shared so we do not wipe it — each launch just (re)writes the
    # specific skills it needs.
    if worktree_skills_dest and os.path.isdir(worktree_skills_dest):
        shutil.rmtree(worktree_skills_dest)
    if not allowed_skills:
        return

    claude_config_dir = os.environ.get('CLAUDE_CONFIG_DIR', '')
    config_skills_dest = (
        os.path.join(claude_config_dir, 'skills') if claude_config_dir else ''
    )
    if worktree_skills_dest:
        os.makedirs(worktree_skills_dest, exist_ok=True)
    if config_skills_dest:
        os.makedirs(config_skills_dest, exist_ok=True)

    # Search order: scope in primary home → management in primary home →
    # management in org home (Issue #408 fallback for project jobs).
    for skill_name in allowed_skills:
        skill_src = os.path.join(
            teaparty_home, scope, 'skills', skill_name,
        )
        if not os.path.isdir(skill_src) and scope != 'management':
            skill_src = os.path.join(
                teaparty_home, 'management', 'skills', skill_name,
            )
        if not os.path.isdir(skill_src) and org_home:
            skill_src = os.path.join(
                org_home, 'management', 'skills', skill_name,
            )
        if not os.path.isdir(skill_src):
            continue
        if worktree_skills_dest:
            shutil.copytree(
                skill_src,
                os.path.join(worktree_skills_dest, skill_name),
            )
        if config_skills_dest:
            target = os.path.join(config_skills_dest, skill_name)
            if os.path.isdir(target):
                shutil.rmtree(target)
            shutil.copytree(skill_src, target)


# ── Worktree composition ────────────────────────────────────────────────────

def compose_launch_worktree(
    *,
    worktree: str,
    agent_name: str,
    scope: str,
    teaparty_home: str,
    org_home: str | None = None,
    mcp_port: int = 0,
    session_id: str = '',
    caller_conversation_id: str = '',
) -> None:
    """Compose the .claude/ directory in a worktree for an agent launch.

    Writes into the existing .claude/ directory without overwriting CLAUDE.md.
    The repo's CLAUDE.md is the project-level instruction file and must not
    be replaced.

    Composes:
    - .claude/agents/{name}.md — the agent's own definition
    - .claude/skills/{name}/ — filtered by agent's skills: frontmatter
    - .claude/settings.json — scope settings merged with agent settings
    - .mcp.json — HTTP MCP endpoint scoped to the agent

    org_home: when set, the org-level .teaparty/ directory used as a
    management-catalog fallback for agent definitions and skills that
    are not found in teaparty_home (Issue #408).
    """
    from teaparty.config.config_reader import read_agent_frontmatter

    try:
        agent_def_path = resolve_agent_definition(
            agent_name, scope, teaparty_home, org_home=org_home,
        )
        fm = read_agent_frontmatter(agent_def_path)
    except FileNotFoundError:
        # Agent definition not in .teaparty/ — compose what we can
        # (settings, MCP config) without the agent-specific parts.
        agent_def_path = ''
        fm = {}

    claude_dir = os.path.join(worktree, '.claude')
    os.makedirs(claude_dir, exist_ok=True)

    # ── Agent definition ─────────────────────────────────────────────────
    agents_dir = os.path.join(claude_dir, 'agents')
    os.makedirs(agents_dir, exist_ok=True)
    # Clean old agent definitions
    for entry in os.scandir(agents_dir):
        if entry.is_symlink() or entry.name.endswith('.md'):
            os.unlink(entry.path)
    if agent_def_path:
        dest_md = os.path.join(agents_dir, f'{agent_name}.md')
        # For leads, append the team roster so the model has the
        # answer to "who is on my team" without a ListTeamMembers
        # round-trip.  No-op for specialists (returns body unchanged).
        try:
            with open(agent_def_path) as _f:
                _raw = _f.read()
        except OSError:
            _raw = ''
        if _raw:
            with open(dest_md, 'w') as _f:
                _f.write(_agent_md_with_roster(
                    _raw,
                    agent_name=agent_name,
                    scope=scope,
                    teaparty_home=teaparty_home,
                ))
        else:
            shutil.copy2(agent_def_path, dest_md)

    # ── Skills (frontmatter allowlist + role-implied) ───────────────────
    _declared = list(fm.get('skills') or [])
    _implied = _role_implied_skills(
        agent_name=agent_name, teaparty_home=teaparty_home,
    )
    _allowed: list[str] = list(_declared)
    for s in _implied:
        if s not in _allowed:
            _allowed.append(s)
    _stage_skills(
        allowed_skills=_allowed,
        worktree_skills_dest=os.path.join(claude_dir, 'skills'),
        scope=scope,
        teaparty_home=teaparty_home,
        org_home=org_home,
    )

    # ── Settings (scope base + agent override) ───────────────────────────
    settings = _merge_settings(agent_name, scope, teaparty_home)
    _inject_baseline_deny(settings)
    _inject_role_implied_tools(
        settings, agent_name=agent_name, teaparty_home=teaparty_home,
    )
    _register_worktree_jail_hook(settings)
    settings_path = os.path.join(claude_dir, 'settings.json')
    with open(settings_path, 'w') as f:
        json.dump(settings, f, indent=2)

    # ── Hooks (stage scripts into worktree) ──────────────────────────────
    # Hook declarations in settings.yaml reference scripts by relative path
    # (e.g. ".claude/hooks/enforce-ownership.sh"). For external-project
    # worktrees those scripts are not present in the git checkout, so copy
    # them from the config-source repos. Also stage the CfA jail hook
    # (teaparty/workspace/worktree_hook.py) at .claude/hooks/ so runtime-
    # injected hook declarations in actors.py resolve without the script
    # having to live in every project's git tree.
    _stage_hook_scripts(
        worktree=worktree,
        settings=settings,
        teaparty_home=teaparty_home,
        org_home=org_home,
    )

    # ── MCP config ───────────────────────────────────────────────────────
    if mcp_port:
        if session_id:
            mcp_url = f'http://localhost:{mcp_port}/mcp/{scope}/{agent_name}/{session_id}'
        else:
            mcp_url = f'http://localhost:{mcp_port}/mcp/{scope}/{agent_name}'
        # The caller's own bus conv_id — MCP middleware parses this
        # ``?conv=`` param and sets the ``current_conversation_id``
        # contextvar.  Every spawn_fn reads that contextvar to stamp
        # ``parent_conversation_id`` on new dispatches — the single
        # codepath that replaces three independent ``f'dispatch:{sid}'``
        # derivations (chat tier, CfA engine, escalation).
        if caller_conversation_id:
            from urllib.parse import quote
            mcp_url = (
                f'{mcp_url}?conv={quote(caller_conversation_id, safe="")}'
            )
        mcp_data = {
            'mcpServers': {
                'teaparty-config': {
                    'type': 'http',
                    'url': mcp_url,
                },
            },
        }
        mcp_path = os.path.join(worktree, '.mcp.json')
        with open(mcp_path, 'w') as f:
            json.dump(mcp_data, f, indent=2)


def _render_team_roster_block(
    *, agent_name: str, scope: str, teaparty_home: str,
) -> str:
    """Return a ``## Your team`` markdown block for a lead's agent.md.

    A lead's first action is delegation, which requires knowing who is
    on the team.  Today the lead has to call ``ListTeamMembers`` on
    every dispatch; in the live joke-book run, ``research-lead`` skipped
    that call and went straight to Write.  Inlining the roster removes
    that off-ramp — the answer is already in the system prompt, so the
    model's autonomous "I see what to do, let me just do it" instinct
    has nowhere to bypass.

    Returns ``''`` when the agent is not a lead (no roster from
    ``derive_team_roster``) or when the lookup fails — caller appends
    nothing in that case.  Every line below pulls weight: the lead name
    is the team identity; each member's one-line description is what
    the model uses to route.
    """
    try:
        from teaparty.config.roster import derive_team_roster
        roster = derive_team_roster(agent_name, teaparty_home)
    except Exception:
        return ''
    if roster is None or not roster.members:
        return ''
    lines = ['## Your team', '']
    for m in roster.members:
        desc = (m.description or m.role or '').strip().splitlines()[0] if (
            m.description or m.role) else ''
        if desc:
            lines.append(f'- **{m.name}** — {desc}')
        else:
            lines.append(f'- **{m.name}**')
    lines.append('')
    lines.append('Send to a member by name. Do not call ListTeamMembers.')
    return '\n'.join(lines) + '\n'


def _agent_md_with_roster(
    raw: str, *, agent_name: str, scope: str, teaparty_home: str,
) -> str:
    """Append the team roster to the agent.md body when the agent is a lead.

    Preserves the original frontmatter and body; the roster lands at
    the end so the role/responsibility text reads first and the team
    listing serves as the "given this team, dispatch" reference.
    No-op when the agent is not a lead.
    """
    block = _render_team_roster_block(
        agent_name=agent_name, scope=scope, teaparty_home=teaparty_home,
    )
    if not block:
        return raw
    sep = '' if raw.endswith('\n') else '\n'
    return f'{raw}{sep}\n{block}'


def _stage_hook_scripts(
    *,
    worktree: str,
    settings: dict,
    teaparty_home: str,
    org_home: str | None,
) -> None:
    """Copy hook scripts referenced by the composed settings into the worktree.

    Two sources contribute scripts:

    1. **Declared hooks.** Every ``command`` in ``settings['hooks']`` is
       shlex-split; any token that resolves to an existing file under the
       project source repo (``dirname(teaparty_home)``) or the org source
       repo (``dirname(org_home)``) is copied to the same relative path
       in the worktree. This lets projects declare hooks whose scripts
       live in ``.claude/hooks/`` of the config-source repo and have them
       appear in the worktree without being checked into git.

    2. **Jail hook.** ``teaparty/workspace/worktree_hook.py`` ships with
       the teaparty package and must be available as
       ``.claude/hooks/worktree_hook.py`` in every CfA job worktree —
       ``AgentRunner`` runtime-injects a ``PreToolUse`` hook pointing
       there. We always stage it so external projects work too.
    """
    import shlex

    # 1. Declared hook scripts from settings.
    source_roots: list[str] = []
    if teaparty_home:
        source_roots.append(os.path.dirname(teaparty_home.rstrip('/')))
    if org_home:
        source_roots.append(os.path.dirname(org_home.rstrip('/')))

    hooks_section = settings.get('hooks') or {}
    if isinstance(hooks_section, dict):
        for _event, entries in hooks_section.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                for hook in entry.get('hooks') or []:
                    if not isinstance(hook, dict):
                        continue
                    command = hook.get('command') or ''
                    if not command:
                        continue
                    try:
                        tokens = shlex.split(command)
                    except ValueError:
                        continue
                    for token in tokens:
                        if os.path.isabs(token):
                            continue
                        for root in source_roots:
                            src = os.path.join(root, token)
                            if os.path.isfile(src):
                                dst = os.path.join(worktree, token)
                                os.makedirs(
                                    os.path.dirname(dst), exist_ok=True,
                                )
                                shutil.copy2(src, dst)
                                break

    # 2. Package-infrastructure hooks — ship with the teaparty package and
    #    are always staged so that any `hooks:` declaration referencing them
    #    at ``.claude/hooks/{name}`` resolves without the script needing to
    #    live in every project's git tree.
    package_hooks_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'workspace',
    )
    package_hooks = [
        'worktree_hook.py',    # Read/Edit/Write/Glob/Grep jail
        'bash_jail_hook.py',   # Bash jail: absolute paths + repo internals
    ]
    for hook_name in package_hooks:
        src = os.path.join(package_hooks_dir, hook_name)
        if os.path.isfile(src):
            dst = os.path.join(worktree, '.claude', 'hooks', hook_name)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)


def chat_config_dir(
    teaparty_home: str,
    scope: str,
    agent_name: str,
    qualifier: str,
) -> str:
    """Return the per-launch config directory for a chat-tier agent.

    Issue #397 fixes the location at
    ``{teaparty_home}/{scope}/agents/{agent_name}/{qualifier}/config/``.
    Parallel instances of the same agent use different *qualifier*
    strings (child session id for dispatches, ``AgentSession.qualifier``
    for top-level invokes) so they do not clobber each other.

    When *qualifier* is empty (singleton agents like the office manager)
    the qualifier segment is omitted:
    ``{teaparty_home}/{scope}/agents/{agent_name}/config/``.
    """
    if qualifier:
        safe_qualifier = qualifier.replace('/', '-').replace(':', '-').replace(' ', '-')
        return os.path.join(
            teaparty_home, scope, 'agents', agent_name, safe_qualifier, 'config',
        )
    return os.path.join(teaparty_home, scope, 'agents', agent_name, 'config')


def compose_launch_config(
    *,
    config_dir: str,
    agent_name: str,
    scope: str,
    teaparty_home: str,
    mcp_port: int = 0,
    session_id: str = '',
    caller_conversation_id: str = '',
) -> dict[str, str]:
    """Compose per-launch config files for a chat-tier agent launch.

    Writes three files into *config_dir* (the spec'd location under
    ``{teaparty_home}/{scope}/agents/{agent_name}/{qualifier}/config/``):

    - ``settings.json`` — merged scope + agent settings with tool allow list.
    - ``mcp.json`` — scoped HTTP MCP endpoint.
    - ``agent.json`` — the persona as a ``--agents`` JSON payload.

    Does NOT write into the launch cwd. The real repo's ``.claude/`` and
    ``.mcp.json`` are never touched.

    Returns a dict with:
        settings_path: absolute path to the composed settings.json
        mcp_path: absolute path to the composed mcp.json (or '')
        agents_file: absolute path to the on-disk agent.json (or '')
        agents_json: the same agents payload as an inline JSON string
    """
    from teaparty.config.config_reader import read_agent_frontmatter

    os.makedirs(config_dir, exist_ok=True)

    # Settings: scope base + agent override (same merge as worktree path).
    # settings.yaml is the authoritative whitelist; agent.md frontmatter
    # `tools:` is a legacy fallback for agents not yet migrated.
    settings = _merge_settings(agent_name, scope, teaparty_home)
    try:
        agent_def_path = resolve_agent_definition(agent_name, scope, teaparty_home)
        fm = read_agent_frontmatter(agent_def_path)
    except FileNotFoundError:
        agent_def_path = ''
        fm = {}

    # Fallback: if settings.yaml doesn't grant permissions, derive them
    # from the frontmatter tools list. The CLI's permission prompt fires
    # when a tool is visible (via --tools) but not in permissions.allow,
    # so both the flag and the allow list must cover the same set.
    if not (settings.get('permissions') or {}).get('allow'):
        tools_str = fm.get('tools', '')
        if tools_str:
            fallback = [t.strip() for t in tools_str.split(',') if t.strip()]
            perms = settings.get('permissions') or {}
            perms['allow'] = fallback
            settings['permissions'] = perms

    _inject_baseline_deny(settings)
    _inject_role_implied_tools(
        settings, agent_name=agent_name, teaparty_home=teaparty_home,
    )
    _register_worktree_jail_hook(settings)
    settings_path = os.path.join(config_dir, 'settings.json')
    with open(settings_path, 'w') as f:
        json.dump(settings, f, indent=2)

    # Stage skills into $CLAUDE_CONFIG_DIR/skills/ — chat-tier has no
    # per-launch worktree to populate, but the discovery path the
    # ``Skill`` tool uses is the shared CLAUDE_CONFIG_DIR one.  Without
    # this call a chat-tier agent's ``skills:`` frontmatter is inert
    # and its ``/<name>`` slash command fails with "Unknown skill".
    _declared_chat = list(fm.get('skills') or [])
    _implied_chat = _role_implied_skills(
        agent_name=agent_name, teaparty_home=teaparty_home,
    )
    _allowed_chat: list[str] = list(_declared_chat)
    for s in _implied_chat:
        if s not in _allowed_chat:
            _allowed_chat.append(s)
    _stage_skills(
        allowed_skills=_allowed_chat,
        worktree_skills_dest='',
        scope=scope,
        teaparty_home=teaparty_home,
    )

    # MCP endpoint — scoped to this agent/session so tools can route.
    # Also carries the caller's conv_id as ``?conv=`` so the MCP
    # middleware can set ``current_conversation_id`` — the single
    # source of truth for "what conv owns this MCP call" (see
    # ``teaparty.mcp.registry.current_conversation_id``).
    mcp_path = ''
    if mcp_port:
        if session_id:
            mcp_url = f'http://localhost:{mcp_port}/mcp/{scope}/{agent_name}/{session_id}'
        else:
            mcp_url = f'http://localhost:{mcp_port}/mcp/{scope}/{agent_name}'
        if caller_conversation_id:
            from urllib.parse import quote
            mcp_url = (
                f'{mcp_url}?conv={quote(caller_conversation_id, safe="")}'
            )
        mcp_data = {
            'mcpServers': {
                'teaparty-config': {
                    'type': 'http',
                    'url': mcp_url,
                },
            },
        }
        mcp_path = os.path.join(config_dir, 'mcp.json')
        with open(mcp_path, 'w') as f:
            json.dump(mcp_data, f, indent=2)

    # Agent definition. Pulls the agent.md body as the system prompt so
    # Claude Code loads the persona without needing a .claude/agents/
    # file in the cwd. Written to disk as agent.json AND returned as an
    # inline JSON string so the caller can choose --agents-file or
    # --agents (both are wired through ClaudeRunner).
    agents_json = ''
    agents_file = ''
    if agent_def_path:
        try:
            with open(agent_def_path) as f:
                raw = f.read()
        except OSError:
            raw = ''
        body = raw
        if raw.startswith('---'):
            parts = raw.split('---', 2)
            if len(parts) == 3:
                body = parts[2].lstrip('\n')
        # Append the team roster for leads so the model has the team
        # listing in its system prompt without a ListTeamMembers call.
        body = _agent_md_with_roster(
            body,
            agent_name=agent_name,
            scope=scope,
            teaparty_home=teaparty_home,
        )
        entry: dict[str, Any] = {
            'description': fm.get('description', '') or agent_name,
            'prompt': body,
        }
        model = fm.get('model')
        if model:
            entry['model'] = model
        max_turns = fm.get('maxTurns')
        if max_turns:
            entry['maxTurns'] = max_turns
        disallowed = fm.get('disallowedTools')
        if disallowed:
            entry['disallowedTools'] = disallowed
        payload = {agent_name: entry}
        agents_json = json.dumps(payload)
        agents_file = os.path.join(config_dir, 'agent.json')
        with open(agents_file, 'w') as f:
            json.dump(payload, f, indent=2)

    return {
        'settings_path': settings_path,
        'mcp_path': mcp_path,
        'agents_json': agents_json,
        'agents_file': agents_file,
    }


def _register_worktree_jail_hook(settings: dict) -> None:
    """Add a PreToolUse declaration for ``worktree_hook.py``.

    The hook is the actual sandbox boundary for an agent's filesystem
    writes: it denies any absolute path that resolves outside the
    agent's cwd.  Without it registered, Claude CLI falls back to its
    default permission flow — which prompts the user for any tool
    invocation outside the allow list, surfacing blocking prompts the
    operator never sees and stalling dispatched workers.

    The command path is **absolute** and resolves to the script as
    shipped with the teaparty package.  Two launch shapes need this
    hook:

    - **Worktree-tier** (every CfA worker, every dispatched chat
      child) has ``.claude/hooks/`` populated by ``_stage_hook_scripts``,
      so a relative path would also work — but the absolute path
      hurts nothing here.
    - **Chat-tier** (top-level chats: OM, project leads, the proxy)
      runs from a ``launch_cwd`` that is the config dir or the repo
      root, neither of which has ``.claude/hooks/`` next to it.  A
      relative ``python3 .claude/hooks/worktree_hook.py`` produces
      ``can't open file`` on every Read/Edit/Write/Glob/Grep call,
      and the agent (most visibly the proxy) gives a meta-response
      about hook errors instead of acting on the gate.  An absolute
      path collapses both shapes onto one codepath.

    The jail boundary itself is still ``os.getcwd()`` inside the
    hook — that gives the agent's runtime cwd, not the location of
    the script — so this change does not weaken the sandbox.

    Idempotent: appends a single ``Read|Edit|Write|Glob|Grep`` matcher
    entry.  No-op if a declaration whose command resolves to
    ``worktree_hook.py`` is already present (under any path).
    """
    hooks = settings.setdefault('hooks', {})
    if not isinstance(hooks, dict):
        hooks = {}
        settings['hooks'] = hooks
    pre = hooks.setdefault('PreToolUse', [])
    if not isinstance(pre, list):
        pre = []
        hooks['PreToolUse'] = pre
    # Absolute path so the hook resolves whether or not the launch
    # path stages a ``.claude/hooks/`` directory next to the cwd.
    script_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'workspace', 'worktree_hook.py',
    )
    cmd = f'python3 {script_path}'
    # Idempotency: any existing declaration that ends in
    # ``worktree_hook.py`` (relative or absolute) counts as installed.
    # Migrating an existing relative entry to absolute happens via
    # rewrite below so a stale settings file from before this change
    # is healed on the next launch.
    for entry in pre:
        if not isinstance(entry, dict):
            continue
        for h in (entry.get('hooks') or []):
            if not isinstance(h, dict):
                continue
            existing = h.get('command') or ''
            if existing == cmd:
                return
            if existing.endswith('worktree_hook.py') or existing.endswith(
                    'worktree_hook.py"',  # quoted form
            ):
                # Heal a stale relative-path entry to absolute.
                h['command'] = cmd
                return
    pre.append({
        'matcher': 'Read|Edit|Write|Glob|Grep',
        'hooks': [{'type': 'command', 'command': cmd}],
    })


def derive_tools_from_settings(
    allow: list[str], frontmatter_tools: str = '',
) -> str | None:
    """Build the ``--tools`` string passed to Claude CLI.

    Claude CLI's ``--tools`` argument is the visibility whitelist:
    tools NOT in this list are not part of the agent's tool catalog.
    The list is derived from the agent's ``permissions.allow`` (or, for
    agents not yet migrated, from the frontmatter ``tools:`` field).
    Permission-style entries like ``Write(/path/**)`` are stripped to
    bare names (``Write``).

    Returns the comma-joined string, or ``None`` when no allow list is
    available (caller falls through to whatever the CLI defaults
    expose).

    What this function deliberately does NOT do: inject
    ``ToolSearch``.  An earlier implementation forced ToolSearch into
    every agent's ``--tools``, which let agents fetch the schema of
    any tool registered with any MCP server — including tools outside
    their allow list — and then attempt to call them.  Calls hit the
    permission-prompt path and stalled.  Whitelisting only works when
    discovery is also gated; an agent that legitimately needs tool
    discovery must add ``ToolSearch`` to its own
    ``permissions.allow``.
    """
    effective_allow = allow
    if not effective_allow and frontmatter_tools:
        effective_allow = [
            t.strip() for t in frontmatter_tools.split(',') if t.strip()
        ]
    if not effective_allow:
        return None
    bare_names: list[str] = []
    seen: set[str] = set()
    for entry in effective_allow:
        paren = entry.find('(')
        name = entry[:paren].strip() if paren > 0 else entry.strip()
        if name and name not in seen:
            bare_names.append(name)
            seen.add(name)
    return ','.join(bare_names)


def _merge_settings(
    agent_name: str,
    scope: str,
    teaparty_home: str,
) -> dict:
    """Merge scope-level settings with agent-level settings (agent wins)."""
    base_path = os.path.join(teaparty_home, scope, 'settings.yaml')
    base = _load_yaml(base_path) or {}

    agent_settings_path = os.path.join(
        teaparty_home, scope, 'agents', agent_name, 'settings.yaml',
    )
    override = _load_yaml(agent_settings_path) or {}
    if override:
        base = _deep_merge(base, override)
    return base


def _load_yaml(path: str) -> dict | None:
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return yaml.safe_load(f) or None


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result




# ── Session lifecycle ────────────────────────────────────────────────────────

MAX_CONVERSATIONS_PER_AGENT = 3


def create_session(
    *,
    agent_name: str,
    scope: str,
    teaparty_home: str,
    session_id: str = '',
    parent_dir: str = '',
) -> Session:
    """Create a new session.

    By default, the session lives under ``{teaparty_home}/{scope}/sessions/<sid>/``
    — the catalog-keyed layout used for top-level chat sessions.
    When ``parent_dir`` is supplied, the session lives at
    ``{parent_dir}/<sid>/`` instead, used for dispatched task sessions
    that should live under the dispatching job's directory rather than
    under the catalog (so a job's workers are filesystem-children of
    the job, with matching lifetime and discoverability).

    Writes metadata.json with the agent name.  If session_id is
    provided, uses it (for stable session keying); otherwise generates
    a random ID.
    """
    if not session_id:
        session_id = uuid.uuid4().hex[:12]
    if parent_dir:
        session_path = os.path.join(parent_dir, session_id)
    else:
        sessions_dir = os.path.join(teaparty_home, scope, 'sessions')
        session_path = os.path.join(sessions_dir, session_id)
    os.makedirs(session_path, exist_ok=True)

    session = Session(
        id=session_id,
        path=session_path,
        agent_name=agent_name,
        scope=scope,
    )
    _save_session_metadata(session)
    return session


def load_session(
    *,
    agent_name: str,
    scope: str,
    teaparty_home: str,
    session_id: str,
    parent_dir: str = '',
) -> Session | None:
    """Load an existing session.

    Mirrors :func:`create_session`: when ``parent_dir`` is supplied,
    looks at ``{parent_dir}/<sid>/`` first; otherwise (or as a fallback
    if the parent_dir path is missing) checks the legacy
    ``{teaparty_home}/{scope}/sessions/<sid>/``.  The fallback covers
    sessions created before the layout change.

    Returns None if neither location holds a metadata.json.
    """
    candidates: list[str] = []
    if parent_dir:
        candidates.append(os.path.join(parent_dir, session_id))
    candidates.append(
        os.path.join(teaparty_home, scope, 'sessions', session_id)
    )
    session_path = ''
    for cand in candidates:
        if os.path.isfile(os.path.join(cand, 'metadata.json')):
            session_path = cand
            break
    if not session_path:
        session_path = candidates[0]
    meta_path = os.path.join(session_path, 'metadata.json')
    if not os.path.isfile(meta_path):
        return None
    try:
        with open(meta_path) as f:
            meta = json.load(f)
        return Session(
            id=session_id,
            path=session_path,
            agent_name=meta.get('agent_name', agent_name),
            scope=meta.get('scope', scope),
            claude_session_id=meta.get('claude_session_id', ''),
            launch_cwd=meta.get('launch_cwd', ''),
            worktree_path=meta.get('worktree_path', ''),
            worktree_branch=meta.get('worktree_branch', ''),
            merge_target_repo=meta.get('merge_target_repo', ''),
            merge_target_branch=meta.get('merge_target_branch', ''),
            merge_target_worktree=meta.get('merge_target_worktree', ''),
            phase=meta.get('phase', 'launching'),
            response_text=meta.get('response_text', ''),
            project_slug=meta.get('project_slug', ''),
            parent_session_id=meta.get('parent_session_id', ''),
            current_message=meta.get('current_message', ''),
            in_flight_gc_ids=list(meta.get('in_flight_gc_ids', [])),
            initial_message=meta.get('initial_message', ''),
        )
    except (json.JSONDecodeError, OSError):
        return None


def _save_session_metadata(session: Session) -> None:
    """Write metadata.json for a session."""
    meta = {
        'session_id': session.id,
        'agent_name': session.agent_name,
        'scope': session.scope,
        'claude_session_id': session.claude_session_id,
        'launch_cwd': session.launch_cwd,
        'worktree_path': session.worktree_path,
        'worktree_branch': session.worktree_branch,
        'merge_target_repo': session.merge_target_repo,
        'merge_target_branch': session.merge_target_branch,
        'merge_target_worktree': session.merge_target_worktree,
        'phase': session.phase,
        'response_text': session.response_text,
        'project_slug': session.project_slug,
        'parent_session_id': session.parent_session_id,
        'current_message': session.current_message,
        'in_flight_gc_ids': session.in_flight_gc_ids,
        'initial_message': session.initial_message,
    }
    meta_path = os.path.join(session.path, 'metadata.json')
    tmp = meta_path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(meta, f, indent=2)
    os.replace(tmp, meta_path)


# ── Phase transitions (pause/resume plumbing, issue #403) ───────────────────

def _update_phase_fields(session: Session, fields: dict[str, Any]) -> None:
    """Read-modify-write only the named phase fields in metadata.json.

    Other fields (claude_session_id, conversation_map, etc.) are preserved
    from disk so a concurrent update from a different codepath is not
    clobbered. Same pattern as _update_conversation_map.
    """
    meta_path = os.path.join(session.path, 'metadata.json')
    try:
        with open(meta_path) as f:
            meta = json.load(f)
    except (json.JSONDecodeError, OSError):
        meta = {}
    meta.update(fields)
    tmp = meta_path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(meta, f, indent=2)
    os.replace(tmp, meta_path)


def mark_launching(session: Session, current_message: str) -> None:
    """Record that the session is about to enter ``await _launch(...)``.

    The current_message is persisted so a launching-phase resume can
    re-send the same turn input under --resume. Cancellation between
    this call and the next transition lands in the launching await
    with phase='launching' and the correct input already on disk.
    """
    session.phase = 'launching'
    session.current_message = current_message
    _update_phase_fields(
        session,
        {'phase': 'launching', 'current_message': current_message},
    )


def mark_awaiting(session: Session, in_flight_gc_ids: list[str]) -> None:
    """Record that the session is about to enter ``await gather(...)``.

    The grandchild ids being awaited are persisted so the resume walker
    can locate those sessions on disk and rebuild the gather target set.
    """
    session.phase = 'awaiting'
    session.in_flight_gc_ids = list(in_flight_gc_ids)
    _update_phase_fields(
        session,
        {'phase': 'awaiting', 'in_flight_gc_ids': list(in_flight_gc_ids)},
    )


def mark_complete(session: Session, response_text: str) -> None:
    """Record that the subtree loop exited normally with a final reply.

    The stored response_text lets a resumed parent collect this session's
    answer without re-running any LLM work.
    """
    session.phase = 'complete'
    session.response_text = response_text
    _update_phase_fields(
        session, {'phase': 'complete', 'response_text': response_text},
    )


def check_slot_available(
    session: Session, bus=None, conv_id: str = '',
) -> bool:
    """Check whether the agent has a free conversation slot (#422).

    Slot count comes from the bus — the single source of truth for the
    dispatch tree.  ``conv_id`` is the dispatcher's conversation id
    (e.g. ``'om'``, ``'lead:project:qualifier'``) — children under this
    id are this session's live dispatches.  Terminal-state children
    (closed/withdrawn) do not count.

    If bus is None, returns True (no enforcement possible without the
    source of truth).
    """
    if bus is None:
        return True
    live_states = {'pending', 'active', 'paused'}
    query_conv = conv_id or f'dispatch:{session.id}'
    live = [
        c for c in bus.children_of(query_conv) if c.state.value in live_states
    ]
    return len(live) < MAX_CONVERSATIONS_PER_AGENT


# ── Session health ───────────────────────────────────────────────────────────

def detect_poisoned_session(events: list[dict]) -> bool:
    """Detect a poisoned session from stream events.

    A session is poisoned when the MCP server fails to start —
    --resume on that session silently fails forever.
    """
    for ev in events:
        if ev.get('type') != 'system':
            continue
        for srv in ev.get('mcp_servers', []):
            if srv.get('status') == 'failed':
                return True
    return False


def should_clear_session(*, response_text: str, session_id: str) -> bool:
    """Determine whether the session ID should be cleared.

    An empty response means the session is dead — clear it so the next
    invocation starts fresh.
    """
    return not response_text and bool(session_id)


# ── LLM caller type and default implementation ──────────────────────────────

# An llm_caller is an async function that takes the launch parameters and
# returns a ClaudeResult. launch() delegates to it after composing the
# worktree and resolving settings. The default wraps ClaudeRunner.
#
# Tests can pass a scripted caller (see teaparty.runners.scripted) to
# exercise the dispatch machinery without real claude subprocesses.
LLMCaller = Callable[..., Any]  # async (**kwargs) -> ClaudeResult


async def _default_claude_caller(**kwargs) -> ClaudeResult:
    """Default llm_caller: runs ClaudeRunner on the given parameters."""
    from teaparty.runners.claude import ClaudeRunner
    # agent_name is informational for scripted callers; ClaudeRunner
    # doesn't take it — the message parameter carries the prompt.
    kwargs.pop('agent_name', None)
    message = kwargs.pop('message')
    runner = ClaudeRunner(message, **kwargs)
    return await runner.run()


async def _default_ollama_caller(**kwargs) -> ClaudeResult:
    """llm_caller: runs OllamaRunner on the given parameters."""
    from teaparty.runners.ollama import OllamaRunner
    _sanitize_caller_kwargs(kwargs)
    kwargs.pop('agent_name', None)
    kwargs.pop('on_pid', None)  # Ollama runner doesn't have a subprocess PID hook
    message = kwargs.pop('message')
    runner = OllamaRunner(message, **kwargs)
    return await runner.run()


def _sanitize_caller_kwargs(kwargs: dict) -> dict:
    """Strip chat-tier-only kwargs that scripted/legacy callers don't accept.

    The unified launcher passes settings_path/mcp_config_path/strict_mcp_config
    so the real ClaudeRunner can wire up per-launch config, but scripted
    test callers and older adapters don't accept them — drop them here.
    """
    for k in ('settings_path', 'mcp_config_path', 'strict_mcp_config',
              'on_pid'):
        kwargs.pop(k, None)
    return kwargs


# ── The launcher ─────────────────────────────────────────────────────────────

async def launch(
    *,
    agent_name: str,
    message: str,
    scope: str,
    teaparty_home: str,
    org_home: str | None = None,
    worktree: str = '',
    tier: str = 'job',
    launch_cwd: str = '',
    config_dir: str = '',
    resume_session: str = '',
    mcp_port: int = 0,
    on_stream_event: Callable[[dict], None] | None = None,
    event_bus: Any = None,
    session_id: str = '',
    telemetry_scope: str = '',
    heartbeat_file: str = '',
    parent_heartbeat: str = '',
    children_file: str = '',
    stall_timeout: int = 1800,
    # Optional overrides — callers that derive config from other sources
    # (e.g. CfA PhaseConfig) can bypass the standard .teaparty/ derivation.
    settings_override: dict[str, Any] | None = None,
    agents_json: str | None = None,
    agents_file: str | None = None,
    stream_file: str = '',
    env_vars: dict[str, str] | None = None,
    permission_mode_override: str = '',
    tools_override: str | None = None,
    # LLM backend — default is real claude, tests inject scripted caller.
    llm_caller: LLMCaller = _default_claude_caller,
    # MCP handler routes — installed in the in-process registry before
    # the subprocess spawns so Send / CloseConversation / AskQuestion
    # are immediately reachable by agent_name.  Single registration
    # site shared by both tiers (see issue #422).
    mcp_routes: Any = None,
    # The conv_id this agent owns in the bus — included in the MCP
    # URL as ``?conv=``.  The MCP middleware reads it and sets the
    # ``current_conversation_id`` contextvar, which every spawn_fn
    # uses as ``parent_conversation_id`` for new dispatches.  Callers
    # must pass their own caller's conv_id; derivation sites (any code
    # that builds ``f'dispatch:{something.id}'`` as parent) are the
    # bug class this fix eliminates.  Empty => MCP handlers fall back
    # to session-id derivation (preserves test paths).
    caller_conversation_id: str = '',
) -> ClaudeResult:
    """Launch an agent through the unified codepath.

    1. Composes the worktree .claude/ from .teaparty/ config
    2. Reads agent frontmatter for tools and permissions
    3. Builds a sanitized environment
    4. Registers MCP handler routes for this agent (if supplied)
    5. Runs the subprocess via ClaudeRunner, streams events, returns result

    This is the only function that spawns agent subprocesses.

    The *_override parameters allow callers to layer additional settings
    (e.g. CfA jail hooks) on top of the config-derived baseline.
    """
    from teaparty.mcp.registry import register_agent_mcp_routes
    # ``mcp_routes`` arrives fully composed: a top-level session built
    # its own bundle in ``_ensure_bus_listener``; a dispatched child's
    # bundle was rebuilt by ``schedule_child_dispatch`` with a
    # child-specific dispatcher (parent_lead set from the conversation
    # context).  The launcher just installs what it was given — no
    # re-derivation here.  This keeps routing scope a property of the
    # conversation that initiated the launch, not something rebuilt
    # from a config tree at the receiving end.
    register_agent_mcp_routes(agent_name, mcp_routes)
    from teaparty.config.config_reader import read_agent_frontmatter
    from teaparty.runners.claude import ClaudeRunner

    # Cut 19: when launching a child whose conv_id we know, hand
    # ClaudeRunner an on_pid callback that stamps the spawn PID +
    # OS create_time onto the bus's DISPATCH conversation row.
    # Recovery later reads (pid, started) and asks the OS whether
    # the same process is still alive — the bus is the single
    # source of truth, no heartbeat files involved in recovery.
    on_pid_callback: Callable[[int, float], None] | None = None
    if caller_conversation_id and caller_conversation_id.startswith('dispatch:'):
        # The teaparty_home is the convention root; the bus DB lives
        # at <scope>/messages.db beneath it.  We resolve here so
        # ClaudeRunner doesn't need to know the bus layout.
        _bus_db = os.path.join(teaparty_home, scope, 'messages.db')
        if os.path.exists(_bus_db):
            _conv_id = caller_conversation_id

            def _stamp_pid(pid: int, started: float, _db=_bus_db, _cid=_conv_id) -> None:
                from teaparty.messaging.conversations import SqliteMessageBus
                _bus = SqliteMessageBus(_db)
                try:
                    _bus.set_conversation_process(_cid, pid, started)
                finally:
                    _bus.close()

            on_pid_callback = _stamp_pid

    # Two launch tiers:
    #   job:  CfA jobs — compose a worktree, run subprocess inside it.
    #   chat: management chat — run at the real repo, config via CLI flags.
    is_chat = (tier == 'chat')
    chat_settings_path = ''
    chat_mcp_path = ''
    chat_agents_json = ''
    chat_agents_file = ''
    if is_chat:
        if not launch_cwd:
            raise ValueError('launch(tier="chat") requires launch_cwd')
        if not config_dir:
            raise ValueError('launch(tier="chat") requires config_dir')
        os.makedirs(config_dir, exist_ok=True)
        cfg = compose_launch_config(
            config_dir=config_dir,
            agent_name=agent_name,
            scope=scope,
            teaparty_home=teaparty_home,
            mcp_port=mcp_port,
            session_id=session_id,
            caller_conversation_id=caller_conversation_id,
        )
        chat_settings_path = cfg['settings_path']
        chat_mcp_path = cfg['mcp_path']
        chat_agents_json = cfg['agents_json']
        chat_agents_file = cfg.get('agents_file', '')
    else:
        compose_launch_worktree(
            worktree=worktree,
            agent_name=agent_name,
            scope=scope,
            teaparty_home=teaparty_home,
            org_home=org_home,
            mcp_port=mcp_port,
            session_id=session_id,
            caller_conversation_id=caller_conversation_id,
        )

    # Read agent frontmatter for tools and permission mode
    try:
        agent_def_path = resolve_agent_definition(
            agent_name, scope, teaparty_home, org_home=org_home,
        )
        fm = read_agent_frontmatter(agent_def_path)
    except FileNotFoundError:
        fm = {}

    # Permission mode
    permission_mode = permission_mode_override or fm.get('permissionMode', 'default') or 'default'

    # Settings: scope base + agent override, authoritative for the whitelist.
    # Frontmatter `tools:` is a legacy fallback only used when settings.yaml
    # has no permissions.allow.
    if settings_override is not None:
        settings = dict(settings_override)
    else:
        settings = _merge_settings(agent_name, scope, teaparty_home)
    _inject_baseline_deny(settings)
    _inject_role_implied_tools(
        settings, agent_name=agent_name, teaparty_home=teaparty_home,
    )
    _register_worktree_jail_hook(settings)

    # Derive --tools from settings.yaml's permissions.allow; fall back to
    # frontmatter tools: for agents that have not yet migrated to settings.yaml.
    # ``--tools`` takes BARE tool names ("Write", "Edit"); permission
    # patterns ("Write(/path/**)") are stripped to bare names.
    tools = tools_override
    if tools is None:
        tools = derive_tools_from_settings(
            (settings.get('permissions') or {}).get('allow') or [],
            fm.get('tools', ''),
        )

    if is_chat:
        effective_cwd = launch_cwd
        effective_stream = stream_file or os.path.join(config_dir, 'stream.jsonl')
        # Prefer inline --agents JSON composed into the config dir over
        # whatever the caller passed; chat tier owns the agent definition.
        effective_agents_json = agents_json or chat_agents_json
        effective_settings_path = chat_settings_path
        effective_mcp_path = chat_mcp_path
        strict_mcp = True
    else:
        effective_cwd = worktree
        effective_stream = stream_file or os.path.join(worktree, '.stream.jsonl')
        effective_agents_json = agents_json
        effective_settings_path = ''
        effective_mcp_path = ''
        strict_mcp = False

    # Point telemetry at this teaparty_home (idempotent) and emit
    # turn_start before the subprocess runs.
    try:
        from teaparty.telemetry import set_teaparty_home
        set_teaparty_home(teaparty_home)
    except Exception:
        pass

    _tscope = telemetry_scope or scope
    record_event(
        _telem_events.TURN_START,
        scope=_tscope,
        agent_name=agent_name,
        session_id=session_id,
        data={
            'trigger': 'dispatch' if resume_session else 'new',
            'claude_session': resume_session or '',
            'model': '',
            'resume_from_phase': None,
        },
    )
    _turn_start_wall = time.time()

    # Delegate to the llm_caller. Default is _default_claude_caller
    # which wraps ClaudeRunner. Tests inject a scripted caller.
    result = await llm_caller(
        agent_name=agent_name,
        message=message,
        cwd=effective_cwd,
        stream_file=effective_stream,
        lead=agent_name,
        settings=settings,
        settings_path=effective_settings_path,
        mcp_config_path=effective_mcp_path,
        strict_mcp_config=strict_mcp,
        permission_mode=permission_mode,
        tools=tools,
        resume_session=resume_session or None,
        on_stream_event=on_stream_event,
        on_pid=on_pid_callback,
        event_bus=event_bus,
        session_id=session_id,
        heartbeat_file=heartbeat_file,
        parent_heartbeat=parent_heartbeat,
        children_file=children_file,
        stall_timeout=stall_timeout,
        agents_json=effective_agents_json,
        agents_file=agents_file,
        env_vars=env_vars or {},
    )

    # Emit turn_complete with per-turn cost, tokens, and duration.
    record_event(
        _telem_events.TURN_COMPLETE,
        scope=_tscope,
        agent_name=agent_name,
        session_id=session_id or result.session_id,
        data={
            'duration_ms':          result.duration_ms,
            'exit_code':            result.exit_code,
            'cost_usd':             result.cost_usd,
            'input_tokens':         result.input_tokens,
            'output_tokens':        result.output_tokens,
            'cache_read_tokens':    getattr(result, 'cache_read_tokens', 0),
            'cache_create_tokens':  getattr(result, 'cache_create_tokens', 0),
            'response_text_len':    len(getattr(result, 'response_text', '') or ''),
            'tools_called':         getattr(result, 'tools_called', {}) or {},
            'wall_duration_ms':     int((time.time() - _turn_start_wall) * 1000),
        },
    )

    return result
