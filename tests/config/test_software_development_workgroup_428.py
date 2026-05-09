"""Tests for the software-development workgroup and lead (issue #428).

Static inspection of the management catalog artifacts.  Layered:

  1. Workgroup YAML at ``.teaparty/management/workgroups/
     software-development.yaml`` — name, lead, member roster.
  2. Lead agent at ``.teaparty/management/agents/software-development-
     lead/`` — frontmatter (model, maxTurns, skills, disallowedTools)
     and ``settings.yaml`` allow list.
  3. Pipeline encoding — the lead's prompt body must name the four
     hops the issue specifies, each with the ``Delegate(skill=...)``
     argument the issue prescribes.  This is the load-bearing
     specification of the orchestrator's behaviour; if the body drifts
     the orchestrator silently improvises.
  4. Catalog registration — the workgroup must be enumerated in
     ``teaparty.yaml`` so the loader can discover it.
  5. Roster recognition — ``derive_team_roster('software-development-
     lead', ...)`` returns a Roster whose lead matches and whose
     members include coding-lead, quality-control-lead, and auditor.
  6. Dependencies (verify-only, per issue boundaries) — the upstream
     dependencies named by the issue exist: coding workgroup + lead,
     quality-control workgroup + lead, auditor agent, attempt-task
     skill, audit-issue skill, and the ``Delegate`` MCP tool.

Tests inspect on-disk artifacts; they do not invoke the agent.  These
artifacts are the deliverable.
"""
from __future__ import annotations

import os
import re
import unittest

import yaml


# ── Paths ───────────────────────────────────────────────────────────────────

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..'),
)
TEAPARTY_HOME = os.path.join(REPO_ROOT, '.teaparty')
MGMT_ROOT = os.path.join(TEAPARTY_HOME, 'management')
MGMT_WORKGROUPS = os.path.join(MGMT_ROOT, 'workgroups')
MGMT_AGENTS = os.path.join(MGMT_ROOT, 'agents')
MGMT_SKILLS = os.path.join(MGMT_ROOT, 'skills')
MGMT_TEAPARTY_YAML = os.path.join(MGMT_ROOT, 'teaparty.yaml')

WORKGROUP_NAME = 'software-development'
WORKGROUP_YAML = os.path.join(MGMT_WORKGROUPS, f'{WORKGROUP_NAME}.yaml')

LEAD_NAME = 'software-development-lead'
LEAD_DIR = os.path.join(MGMT_AGENTS, LEAD_NAME)
LEAD_AGENT_MD = os.path.join(LEAD_DIR, 'agent.md')
LEAD_SETTINGS = os.path.join(LEAD_DIR, 'settings.yaml')

EXPECTED_MEMBERS = ('coding-lead', 'quality-control-lead', 'auditor')

# The four hops the issue prescribes, in order.  Each tuple is
# (target_member, expected_skill_kwarg).  The lead's body must name
# every (target, skill) pair literally — this is the mechanism by
# which the pipeline is deterministic at every hop.
PIPELINE_HOPS = (
    ('coding-lead', 'attempt-task'),
    ('quality-control-lead', 'attempt-task'),
    ('auditor', 'audit-issue'),
    ('coding-lead', 'attempt-task'),
)


# ── Helpers ────────────────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n?(.*)\Z', re.DOTALL)


def _read_frontmatter_and_body(path: str) -> tuple[dict, str]:
    """Parse YAML frontmatter, returning ``(frontmatter, body)``."""
    with open(path) as fh:
        content = fh.read()
    m = _FRONTMATTER_RE.match(content)
    if not m:
        raise AssertionError(
            f'{path} is missing YAML frontmatter (must start with --- '
            f'and have a closing --- before the body)'
        )
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def _bare_allow(settings_path: str) -> set[str]:
    """The ``permissions.allow`` list with permission patterns stripped."""
    with open(settings_path) as fh:
        settings = yaml.safe_load(fh) or {}
    allow = (settings.get('permissions') or {}).get('allow') or []
    return {entry.split('(', 1)[0].strip() for entry in allow}


def _normalize_dashes(text: str) -> str:
    """Collapse smart quotes / em-dashes for substring searches."""
    return (
        text.replace('—', '--')
            .replace('–', '-')
            .replace('’', "'")
            .replace('‘', "'")
    )


# ── 1. Workgroup YAML ──────────────────────────────────────────────────────

class TestSoftwareDevelopmentWorkgroupYaml(unittest.TestCase):
    """The catalog entry at ``management/workgroups/software-development.yaml``."""

    def test_workgroup_yaml_file_exists_in_management_catalog(self):
        """AC1: the workgroup must live in the management catalog so any
        project that references it can resolve the entry — without this
        file, ``load_workgroup`` raises FileNotFoundError and roster
        derivation cannot find the team."""
        self.assertTrue(
            os.path.isfile(WORKGROUP_YAML),
            f'expected workgroup YAML at {WORKGROUP_YAML}',
        )

    def test_workgroup_yaml_loads_via_workgroup_loader(self):
        """AC1: ``load_workgroup`` is the single read path; if the YAML
        shape is wrong the loader raises and every downstream consumer
        (roster, lead spawn, ListTeamMembers) breaks at the same point."""
        from teaparty.config.config_reader import load_workgroup
        wg = load_workgroup(WORKGROUP_YAML)
        self.assertEqual(
            wg.name, WORKGROUP_NAME,
            f'workgroup.name must be {WORKGROUP_NAME!r}; got {wg.name!r}',
        )

    def test_workgroup_lead_field_names_software_development_lead(self):
        """AC1: the ``lead:`` field is the routing key — every dispatch
        to the workgroup goes to this agent name."""
        from teaparty.config.config_reader import load_workgroup
        wg = load_workgroup(WORKGROUP_YAML)
        self.assertEqual(
            wg.lead, LEAD_NAME,
            f'workgroup.lead must be {LEAD_NAME!r}; got {wg.lead!r}',
        )

    def test_workgroup_members_include_coding_lead_qc_lead_and_auditor(self):
        """AC1: the lead's pipeline dispatches to coding-lead,
        quality-control-lead, and auditor.  Any missing member means
        the corresponding pipeline hop has no covering agent and the
        attempt-task ``no covering member`` branch fires — silently
        breaking the orchestration."""
        from teaparty.config.config_reader import load_workgroup
        wg = load_workgroup(WORKGROUP_YAML)
        members = set(wg.members_agents)
        missing = set(EXPECTED_MEMBERS) - members
        self.assertEqual(
            missing, set(),
            f'workgroup.members.agents missing required members '
            f'{sorted(missing)}; got {sorted(members)}.  Each hop in '
            f'the pipeline must have a covering member in the roster.',
        )

    def test_workgroup_description_states_orchestration_purpose(self):
        """AC1: the description is what every dispatcher matches to
        decide whether to route here.  A vague description means
        callers can't tell if this is the right workgroup."""
        from teaparty.config.config_reader import load_workgroup
        wg = load_workgroup(WORKGROUP_YAML)
        desc = wg.description.lower()
        self.assertTrue(
            desc and 'issue' in desc,
            f'workgroup.description must mention "issue" so dispatchers '
            f'know this is per-issue orchestration; got {wg.description!r}',
        )


# ── 2. Lead agent ──────────────────────────────────────────────────────────

class TestSoftwareDevelopmentLeadAgent(unittest.TestCase):
    """The agent at ``management/agents/software-development-lead/``."""

    def test_lead_agent_directory_exists(self):
        self.assertTrue(
            os.path.isdir(LEAD_DIR),
            f'expected lead agent directory at {LEAD_DIR}',
        )

    def test_lead_agent_md_exists(self):
        self.assertTrue(
            os.path.isfile(LEAD_AGENT_MD),
            f'expected lead agent.md at {LEAD_AGENT_MD}',
        )

    def test_lead_settings_yaml_exists(self):
        self.assertTrue(
            os.path.isfile(LEAD_SETTINGS),
            f'expected lead settings.yaml at {LEAD_SETTINGS}',
        )

    def test_lead_frontmatter_name_matches_directory(self):
        """The frontmatter ``name:`` is the agent identity used by
        ``GetAgent`` and dispatch; mismatched name vs. directory
        silently breaks lookups."""
        fm, _ = _read_frontmatter_and_body(LEAD_AGENT_MD)
        self.assertEqual(
            fm.get('name'), LEAD_NAME,
            f'agent.md frontmatter name must equal {LEAD_NAME!r}; '
            f'got {fm.get("name")!r}',
        )

    def test_lead_skills_frontmatter_includes_attempt_task(self):
        """AC2: the issue prescribes attempt-task as the lead's
        workflow rail.  Without it the lead improvises on each
        dispatched message — the failure mode #423 fixed."""
        fm, _ = _read_frontmatter_and_body(LEAD_AGENT_MD)
        skills = fm.get('skills') or []
        self.assertIn(
            'attempt-task', skills,
            f'agent.md frontmatter skills must include "attempt-task"; '
            f'got {skills!r}.  attempt-task is the procedural rail '
            f'every workgroup-lead runs.',
        )

    def test_lead_disallowed_tools_match_workgroup_lead_baseline(self):
        """AC2: the unified workgroup-lead disallow list (TeamCreate,
        TeamDelete, Task, TaskOutput, TaskStop) must apply to this
        lead — these are the agent-runtime escape hatches no
        workgroup-lead should reach for."""
        fm, _ = _read_frontmatter_and_body(LEAD_AGENT_MD)
        disallowed = set(fm.get('disallowedTools') or [])
        required = {'TeamCreate', 'TeamDelete', 'Task',
                    'TaskOutput', 'TaskStop'}
        missing = required - disallowed
        self.assertEqual(
            missing, set(),
            f'agent.md disallowedTools missing baseline entries '
            f'{sorted(missing)}; got {sorted(disallowed)}.',
        )

    def test_lead_settings_allow_includes_delegate(self):
        """AC2: the issue requires every sub-dispatch to use Delegate
        (so the recipient runs a workflow skill on launch).  Without
        Delegate in the allow list the lead falls back to Send and the
        prefix prescription disappears — pipeline determinism broken."""
        bare = _bare_allow(LEAD_SETTINGS)
        self.assertIn(
            'mcp__teaparty-config__Delegate', bare,
            f'settings.yaml allow list must include '
            f'mcp__teaparty-config__Delegate; this is the tool the '
            f'pipeline uses for every hop.  Got: {sorted(bare)}',
        )

    def test_lead_settings_allow_includes_team_comm_primitives(self):
        """AC2: a workgroup-lead's real work is team-comm.  Send,
        Reply (implicit via final message), AskQuestion,
        CloseConversation, ListTeamMembers — every one is required to
        complete the pipeline (Send to continue an open thread,
        AskQuestion to escalate to the originator, CloseConversation
        to merge member branches, ListTeamMembers to discover roster)."""
        bare = _bare_allow(LEAD_SETTINGS)
        required = (
            'mcp__teaparty-config__Send',
            'mcp__teaparty-config__AskQuestion',
            'mcp__teaparty-config__CloseConversation',
            'mcp__teaparty-config__ListTeamMembers',
        )
        for tool in required:
            self.assertIn(
                tool, bare,
                f'settings.yaml allow list must include {tool}; '
                f'every workgroup-lead needs this team-comm primitive.  '
                f'Got: {sorted(bare)}',
            )

    def test_lead_settings_allow_excludes_bash(self):
        """AC2: the lead has no legitimate use for raw Bash — the
        worktree comes with the dispatch (no manual ``git worktree
        add``), member merges happen via CloseConversation (no manual
        ``git merge``), and final delivery is the job lifecycle (no
        manual ``git push``).  Bash in the allow list is an escape
        hatch begging for a future shortcut that bypasses the
        deterministic dispatch path."""
        bare = _bare_allow(LEAD_SETTINGS)
        self.assertNotIn(
            'Bash', bare,
            f'settings.yaml allow list must NOT include Bash; '
            f'the lead has no legitimate use for raw shell.  '
            f'Got: {sorted(bare)}',
        )


# ── 3. Pipeline encoding ───────────────────────────────────────────────────

class TestSoftwareDevelopmentLeadPipelineEncoding(unittest.TestCase):
    """The lead's body must name every hop literally so a future
    refactor or template-restamp cannot silently drop a step."""

    def test_body_names_each_pipeline_hop_with_correct_skill_prefix(self):
        """AC3: the four hops Coding -> QC -> Audit -> Coding each
        appear in the body, each with its prescribed ``skill=`` arg.
        We assert on (target, skill) pairs because the determinism
        guarantee is per-hop: the wrong skill at any hop breaks the
        workflow rail at the recipient."""
        _, body = _read_frontmatter_and_body(LEAD_AGENT_MD)
        body_norm = _normalize_dashes(body)

        for target, skill in PIPELINE_HOPS:
            target_present = target in body_norm
            self.assertTrue(
                target_present,
                f'agent.md body must name the dispatch target '
                f'{target!r} (one of the four pipeline hops); '
                f'body did not contain that string.',
            )
            # Every hop must name its skill argument verbatim.
            skill_arg = f"skill='{skill}'"
            skill_arg_alt = f'skill="{skill}"'
            self.assertTrue(
                skill_arg in body_norm or skill_arg_alt in body_norm,
                f'agent.md body must name the skill kwarg '
                f'{skill_arg!r} for the {target} hop; body did not '
                f'contain it.  This is the determinism guarantee — '
                f'without the skill prefix the recipient improvises.',
            )

    def test_body_orders_hops_coding_then_qc_then_audit_then_coding(self):
        """AC3: the order matters — Audit before second Coding (so the
        second Coding round consumes audit findings), QC before Audit
        (so audit reviews tested code, not raw output).  We verify
        ordering by index, not by re-spelling the sequence in prose
        (which a refactor could rewrite without changing meaning)."""
        _, body = _read_frontmatter_and_body(LEAD_AGENT_MD)
        body_norm = _normalize_dashes(body)

        # First occurrence of each Delegate target line.  We index on
        # the literal target+skill pair to disambiguate the two
        # coding-lead hops.
        first_coding = body_norm.find("Delegate(coding-lead")
        first_qc = body_norm.find("Delegate(quality-control-lead")
        audit_idx = body_norm.find("Delegate(auditor")
        # Second coding hop = next coding-lead occurrence after first.
        if first_coding == -1:
            second_coding = -1
        else:
            second_coding = body_norm.find(
                "Delegate(coding-lead", first_coding + 1,
            )

        for label, idx in (
            ('first coding-lead', first_coding),
            ('quality-control-lead', first_qc),
            ('auditor', audit_idx),
            ('second coding-lead', second_coding),
        ):
            self.assertGreater(
                idx, -1,
                f'agent.md body must contain the {label} dispatch; '
                f'index search returned -1.  Each of the four hops '
                f'must appear in the body in order.',
            )

        self.assertLess(
            first_coding, first_qc,
            f'first coding-lead hop must precede quality-control-lead '
            f'hop in the body; got indices coding={first_coding}, '
            f'qc={first_qc}.',
        )
        self.assertLess(
            first_qc, audit_idx,
            f'quality-control-lead hop must precede auditor hop; '
            f'got qc={first_qc}, audit={audit_idx}.',
        )
        self.assertLess(
            audit_idx, second_coding,
            f'auditor hop must precede the second coding-lead hop '
            f'(round 2 consumes audit findings); got '
            f'audit={audit_idx}, second_coding={second_coding}.',
        )

    def test_body_specifies_deliver_terminal_with_commit_and_reply(self):
        """AC4: when the pipeline completes, the lead's terminal step
        must commit assembled state on its session branch and Reply
        with a Deliver intent.  Without an explicit DELIVER step the
        attempt-task skill's chain-completion guarantee depends on
        the lead remembering — which is exactly what the procedural
        rail is meant to remove."""
        _, body = _read_frontmatter_and_body(LEAD_AGENT_MD)
        body_lower = body.lower()
        self.assertIn(
            'deliver', body_lower,
            f'agent.md body must specify a DELIVER terminal step; '
            f'word "deliver" not found.',
        )
        self.assertIn(
            'commit', body_lower,
            f'agent.md body must direct the lead to commit assembled '
            f'state in DELIVER (without commit, CloseConversation in '
            f'the originator merges nothing).',
        )
        self.assertIn(
            'reply', body_lower,
            f'agent.md body must direct the lead to Reply at DELIVER '
            f'(this is how the originator learns the work is done).',
        )


# ── 4. Catalog registration ────────────────────────────────────────────────

class TestSoftwareDevelopmentCatalogRegistration(unittest.TestCase):
    """The workgroup must be registered in ``teaparty.yaml`` so the
    loader discovers it."""

    def test_teaparty_yaml_registers_software_development_workgroup(self):
        """AC5: ``teaparty.yaml`` enumerates every workgroup the
        catalog knows about; entries here are what
        ``derive_team_roster`` walks through (path 4) for matrix-loaned
        workgroup-leads.  Missing here means the workgroup is invisible
        to roster derivation even when its YAML and lead exist."""
        with open(MGMT_TEAPARTY_YAML) as fh:
            data = yaml.safe_load(fh) or {}
        workgroups = data.get('workgroups') or []
        names = [(entry or {}).get('name', '') for entry in workgroups]
        self.assertTrue(
            any(n.lower() == WORKGROUP_NAME for n in names),
            f'teaparty.yaml workgroups: list must include '
            f'{WORKGROUP_NAME!r}; got names {names!r}',
        )

    def test_teaparty_yaml_entry_points_at_software_development_yaml(self):
        """AC5: the ``config:`` field on the entry resolves to the
        on-disk YAML; if the path drifts (e.g. a typo) the loader
        opens the wrong file or none at all."""
        with open(MGMT_TEAPARTY_YAML) as fh:
            data = yaml.safe_load(fh) or {}
        workgroups = data.get('workgroups') or []
        entry = next(
            (e for e in workgroups
             if (e or {}).get('name', '').lower() == WORKGROUP_NAME),
            None,
        )
        self.assertIsNotNone(
            entry,
            f'teaparty.yaml has no entry for {WORKGROUP_NAME!r}',
        )
        config_path = (entry or {}).get('config', '')
        resolved = os.path.join(MGMT_ROOT, config_path)
        self.assertEqual(
            os.path.normpath(resolved), os.path.normpath(WORKGROUP_YAML),
            f'teaparty.yaml entry config={config_path!r} must resolve '
            f'to {WORKGROUP_YAML!r}; got {resolved!r}',
        )


# ── 5. Roster recognition ──────────────────────────────────────────────────

class TestSoftwareDevelopmentRosterRecognition(unittest.TestCase):
    """``derive_team_roster`` must return a Roster for the lead — this
    is the precondition for spawning the agent at all."""

    def test_derive_team_roster_returns_roster_for_software_dev_lead(self):
        """AC5: derive_team_roster is the single entry point routing
        and ``ListTeamMembers`` both consume; ``None`` here means the
        lead cannot be dispatched to (the dispatcher rejects unknown
        leads) and ``ListTeamMembers`` returns nothing."""
        from teaparty.config.roster import derive_team_roster
        roster = derive_team_roster(LEAD_NAME, TEAPARTY_HOME)
        self.assertIsNotNone(
            roster,
            f'derive_team_roster({LEAD_NAME!r}) returned None; the '
            f'lead is not discoverable as a workgroup-lead in any '
            f'project or in management.members.workgroups.',
        )

    def test_roster_lead_field_matches_software_development_lead(self):
        from teaparty.config.roster import derive_team_roster
        roster = derive_team_roster(LEAD_NAME, TEAPARTY_HOME)
        assert roster is not None
        self.assertEqual(
            roster.lead, LEAD_NAME,
            f'Roster.lead must equal {LEAD_NAME!r}; got {roster.lead!r}',
        )

    def test_roster_members_include_each_pipeline_target(self):
        """AC5: every pipeline hop's target must appear as a Roster
        member — otherwise ``ListTeamMembers`` does not show it and
        the lead's ``Send``/``Delegate`` is rejected by the
        BusDispatcher (target not in routing table)."""
        from teaparty.config.roster import derive_team_roster
        roster = derive_team_roster(LEAD_NAME, TEAPARTY_HOME)
        assert roster is not None
        member_names = {m.name for m in roster.members}
        missing = set(EXPECTED_MEMBERS) - member_names
        self.assertEqual(
            missing, set(),
            f'Roster missing required members {sorted(missing)}; '
            f'got {sorted(member_names)}.  These are the targets the '
            f'lead Delegates to at every pipeline hop.',
        )


# ── 6. Dependencies (verify-only per issue boundaries) ─────────────────────

class TestSoftwareDevelopmentDependencies(unittest.TestCase):
    """The issue's "depends on" boundary: verify these exist; do not
    modify them.  A failure here is a real blocker (missing dependency),
    not a defect introduced by this issue's diff."""

    def test_coding_workgroup_and_lead_exist(self):
        coding_yaml = os.path.join(MGMT_WORKGROUPS, 'coding.yaml')
        coding_lead = os.path.join(MGMT_AGENTS, 'coding-lead', 'agent.md')
        self.assertTrue(
            os.path.isfile(coding_yaml),
            f'dependency missing: {coding_yaml}',
        )
        self.assertTrue(
            os.path.isfile(coding_lead),
            f'dependency missing: {coding_lead}',
        )

    def test_quality_control_workgroup_and_lead_exist(self):
        qc_yaml = os.path.join(MGMT_WORKGROUPS, 'quality-control.yaml')
        qc_lead = os.path.join(
            MGMT_AGENTS, 'quality-control-lead', 'agent.md',
        )
        self.assertTrue(
            os.path.isfile(qc_yaml),
            f'dependency missing: {qc_yaml}',
        )
        self.assertTrue(
            os.path.isfile(qc_lead),
            f'dependency missing: {qc_lead}',
        )

    def test_auditor_agent_exists(self):
        auditor_md = os.path.join(MGMT_AGENTS, 'auditor', 'agent.md')
        self.assertTrue(
            os.path.isfile(auditor_md),
            f'dependency missing: {auditor_md}.  The audit hop '
            f'targets this specialist.',
        )

    def test_attempt_task_skill_exists(self):
        skill_md = os.path.join(MGMT_SKILLS, 'attempt-task', 'SKILL.md')
        self.assertTrue(
            os.path.isfile(skill_md),
            f'dependency missing: {skill_md}.  The lead and the '
            f'coding-lead/qc-lead hops all run this skill.',
        )

    def test_audit_issue_skill_exists(self):
        # audit-issue is user-invocable and lives in ~/.claude/skills/
        # not the management catalog.  We accept either location: the
        # lead Delegates with skill='audit-issue' and the skill must
        # be resolvable from the recipient's runtime.
        candidates = (
            os.path.expanduser('~/.claude/skills/audit-issue/SKILL.md'),
            os.path.join(MGMT_SKILLS, 'audit-issue', 'SKILL.md'),
        )
        found = [c for c in candidates if os.path.isfile(c)]
        self.assertTrue(
            found,
            f'dependency missing: audit-issue skill not found at any '
            f'of {candidates}.  The audit hop dispatches this skill.',
        )

    def test_delegate_mcp_tool_is_registered(self):
        """The Delegate tool from #423 must be in the MCP server's
        registered tool list — without it the lead's settings.yaml
        allow entry resolves to nothing at runtime."""
        from teaparty.mcp.server.main import list_mcp_tool_names
        names = list_mcp_tool_names()
        self.assertIn(
            'mcp__teaparty-config__Delegate', names,
            f'Delegate not registered on the teaparty-config MCP '
            f'server; got names containing '
            f'{[n for n in names if "Delegate" in n]!r}',
        )


if __name__ == '__main__':
    unittest.main()
