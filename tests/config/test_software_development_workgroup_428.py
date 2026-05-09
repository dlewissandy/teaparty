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
        decide whether to route here.  The workgroup's distinguishing
        feature is *orchestration of the per-issue pipeline* — both
        words must appear so a description like "manages
        issue-tracker tickets" or "for issues that arise during
        meetings" cannot pass this gate.

        This addresses audit finding #4 — the prior single-word
        check accepted unrelated meanings of "issue"."""
        from teaparty.config.config_reader import load_workgroup
        wg = load_workgroup(WORKGROUP_YAML)
        desc_lower = wg.description.lower()
        self.assertIn(
            'issue', desc_lower,
            f'workgroup.description must mention "issue" so '
            f'dispatchers know this workgroup is per-issue.  '
            f'Got {wg.description!r}',
        )
        self.assertIn(
            'orchestrat', desc_lower,
            f'workgroup.description must mention "orchestrat" '
            f'(orchestration / orchestrate) — the workgroup\'s '
            f'distinguishing feature is orchestration of the per-issue '
            f'pipeline.  A vague description risks misrouting.  '
            f'Got {wg.description!r}',
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

    def test_lead_frontmatter_pins_model_and_max_turns(self):
        """The runtime contract: ``model:`` selects the Claude
        variant; ``maxTurns:`` bounds the iteration budget.  The
        pipeline takes at minimum 4 hops (round-1 coding, QC,
        audit, round-2 coding) plus DELIVER plus at least one
        audit-loop iteration if findings appear — call it 8 turns
        floor.  The chosen value is 30 (plenty of headroom); the
        test asserts the floor so a future contributor cannot
        silently lower the cap below what the pipeline needs.

        This addresses audit finding #6 — the prior tests covered
        name/skills/disallowed but left model and maxTurns
        unasserted, so removing model (defaulting to whatever the
        harness picks) or lowering maxTurns to 4 would not fail
        any test."""
        fm, _ = _read_frontmatter_and_body(LEAD_AGENT_MD)
        model = fm.get('model')
        self.assertTrue(
            isinstance(model, str) and model.strip(),
            f'agent.md frontmatter must pin a non-empty model '
            f'(do not let the lead default to the harness pick); '
            f'got {model!r}.',
        )
        max_turns = fm.get('maxTurns')
        self.assertIsInstance(
            max_turns, int,
            f'agent.md frontmatter maxTurns must be an int; '
            f'got {type(max_turns).__name__} ({max_turns!r}).',
        )
        # Floor = 4 hops + DELIVER + 1 audit-loop iteration with
        # rework + buffer.  8 is the absolute minimum; we choose
        # this floor as a runtime contract so a future contributor
        # cannot silently break the pipeline by lowering the cap.
        self.assertGreaterEqual(
            max_turns, 8,
            f'agent.md frontmatter maxTurns ({max_turns}) is below '
            f'the pipeline minimum (8 = 4 hops + DELIVER + at '
            f'least one audit-loop iteration with rework, plus '
            f'buffer).  Lowering this cap below the floor breaks '
            f'the lead silently mid-pipeline.',
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

    def test_lead_settings_allow_matches_ac2_tool_prescription(self):
        """AC2: every prescribed tool from the issue's AC2 must
        appear in the allow list.  AC2 lists eleven tool names —
        Read, Glob, Grep, Write, Edit, ListTeamMembers, Send, Reply,
        AskQuestion, CloseConversation, Delegate.  We assert ten of
        them; ``Reply`` is intentionally excluded because no
        ``Reply`` MCP tool exists (the agent's reply is the final
        text turn that the runtime propagates as a Reply intent —
        verified by grep across teaparty/mcp/server/main.py).

        This addresses audit finding #2 — the prior tests asserted
        only Delegate and the four team-comm primitives, leaving
        Read/Glob/Grep/Write/Edit unverified.  Removing Write
        silently broke AC4's DELIVER instruction (the lead is told
        to use Write/Edit to assemble the Deliver payload)."""
        bare = _bare_allow(LEAD_SETTINGS)
        # The ten real tools AC2 lists.  Reply is omitted by design.
        required = {
            'Read',
            'Glob',
            'Grep',
            'Write',
            'Edit',
            'mcp__teaparty-config__ListTeamMembers',
            'mcp__teaparty-config__Send',
            'mcp__teaparty-config__AskQuestion',
            'mcp__teaparty-config__CloseConversation',
            'mcp__teaparty-config__Delegate',
        }
        missing = required - bare
        self.assertEqual(
            missing, set(),
            f'AC2 tool prescription not satisfied; settings.yaml '
            f'allow list is missing {sorted(missing)}.  Got: '
            f'{sorted(bare)}.  Each tool the AC names must be '
            f'present — DELIVER specifically depends on Write/Edit, '
            f'and inspection of merged deliverables depends on '
            f'Read/Glob/Grep.',
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

    def test_each_delegate_call_carries_its_own_skill_kwarg_in_call_args(self):
        """AC3: the determinism guarantee is *per hop*.  Every
        ``Delegate(target, ...)`` call in the body must have its
        ``skill='...'`` argument inside its own argument list — not
        elsewhere in the body, not in a separate prose paragraph.

        Counted by call site so a naked round-2 ``Delegate(coding-lead,
        <findings>)`` cannot ride on round-1's ``skill='attempt-task'``
        substring.  Counted exactly so an extra unintended
        ``Delegate(target, ...)`` is also flagged.

        This addresses audit finding #1 — the prior whole-body
        substring scan accepted naked Delegate calls and free-floating
        ``skill='...'`` strings."""
        _, body = _read_frontmatter_and_body(LEAD_AGENT_MD)
        body_norm = _normalize_dashes(body)

        # Expected (target, skill) -> count of calls with that exact
        # binding.  The four hops collapse to three (target, skill)
        # tuples because both coding-lead hops use skill='attempt-task'.
        expected_bindings = {
            ('coding-lead', 'attempt-task'): 2,
            ('quality-control-lead', 'attempt-task'): 1,
            ('auditor', 'audit-issue'): 1,
        }

        for (target, skill), expected_count in expected_bindings.items():
            bound_matches = []
            naked_count = 0
            pos = 0
            while True:
                idx = body_norm.find(f'Delegate({target}', pos)
                if idx == -1:
                    break
                # Find the closing ')' of this call.  Markdown allows
                # nested parens in prose like (e.g. <findings>) so we
                # take the first matching ')' after the call's open.
                end = body_norm.find(')', idx)
                call = (
                    body_norm[idx:end + 1] if end != -1 else body_norm[idx:]
                )
                if (f"skill='{skill}'" in call
                        or f'skill="{skill}"' in call):
                    bound_matches.append(idx)
                else:
                    naked_count += 1
                pos = idx + 1

            self.assertEqual(
                len(bound_matches), expected_count,
                f"expected {expected_count} Delegate({target}, ..., "
                f"skill='{skill}') call(s) with the skill kwarg bound "
                f"to the call's own argument list; found "
                f'{len(bound_matches)} bound and {naked_count} naked '
                f'(skill kwarg missing or wrong inside the call args).  '
                f'The determinism guarantee is per-hop: every call '
                f'must carry its own skill prefix.',
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

    def test_body_has_deliver_section_with_commit_and_reply_directives(self):
        """AC4: the DELIVER terminal step must exist as a real
        section in the lead's body — not merely as the words
        'deliver', 'commit', 'reply' appearing somewhere.

        Locates a heading whose label starts with DELIVER, then
        asserts the section content (everything until the next
        heading or end-of-body) contains both a commit directive and
        a Reply directive.

        This addresses audit finding #3 — the prior substring scan
        of the whole body passed even when the DELIVER section was
        deleted, because 'commit' survived in the Tools paragraph
        (commit_all_pending) and 'reply' survived in Tools/
        Escalation paragraphs."""
        _, body = _read_frontmatter_and_body(LEAD_AGENT_MD)

        # Find a DELIVER heading, then take everything up to the next
        # heading at the same or higher level.
        m = re.search(
            r'^#{1,6}\s+DELIVER\b.*?(?=^#{1,6}\s|\Z)',
            body,
            re.MULTILINE | re.DOTALL | re.IGNORECASE,
        )
        self.assertIsNotNone(
            m,
            f'agent.md body must have a DELIVER section (heading '
            f'line beginning with #..# DELIVER); found none.  '
            f'Sections present: '
            f'{re.findall(r"^#{1,6}\s+\S+", body, re.MULTILINE)}',
        )
        assert m is not None
        section_lower = m.group(0).lower()
        self.assertIn(
            'commit', section_lower,
            f'DELIVER section must address commit semantics (either '
            f'directing the lead to commit, or explicitly delegating '
            f'commit to the framework via commit_all_pending).  '
            f'Section start: {m.group(0)[:200]!r}',
        )
        self.assertIn(
            'reply', section_lower,
            f'DELIVER section must direct the lead to Reply with the '
            f'Deliver intent (this is how the originator learns the '
            f'pipeline is complete).',
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

    def test_roster_members_have_workgroup_agent_role(self):
        """AC5: each member's ``role`` is what BusDispatcher reads
        to decide routing tier.  For workgroup members the role is
        ``'workgroup-agent'``; if the role drops or swaps (e.g. a
        refactor emits empty string or the wrong role for every
        member), routing decisions go wrong silently.

        This addresses audit finding #5 — the prior test only
        verified member presence, not the role contract."""
        from teaparty.config.roster import derive_team_roster
        roster = derive_team_roster(LEAD_NAME, TEAPARTY_HOME)
        assert roster is not None
        roles = {m.name: m.role for m in roster.members}
        for member in EXPECTED_MEMBERS:
            self.assertEqual(
                roles.get(member), 'workgroup-agent',
                f'roster member {member!r} must have '
                f"role='workgroup-agent' for BusDispatcher routing; "
                f'got {roles.get(member)!r}.  Roles map: {roles!r}',
            )

    def test_roster_has_mesh_among_members_flag_set(self):
        """AC5: the workgroup's distinguishing routing trait is mesh
        — members address each other within the team (through the
        lead's mediation) rather than being hub-and-spoke off the
        lead alone.  ``mesh_among_members=True`` is what makes
        ``build_routing_table`` emit the within-team peer pairs.

        This addresses audit finding #5 — the prior tests did not
        assert the mesh flag, so flipping it to False would silently
        change the routing topology."""
        from teaparty.config.roster import derive_team_roster
        roster = derive_team_roster(LEAD_NAME, TEAPARTY_HOME)
        assert roster is not None
        self.assertTrue(
            roster.mesh_among_members,
            f'software-development workgroup roster must be mesh '
            f'(mesh_among_members=True) so members can address each '
            f'other through the lead.  Got mesh_among_members='
            f'{roster.mesh_among_members!r}.',
        )

    def test_project_lead_roster_includes_software_development_lead(self):
        """AC4: the lead reports completion back to the project lead.
        For that dispatch to be possible the project-lead's roster
        must list software-development-lead as a member — otherwise
        the project-lead's BusDispatcher rejects the Delegate
        (unknown member) and the pipeline cannot be invoked."""
        from teaparty.config.config_reader import load_project_team
        from teaparty.config.roster import derive_team_roster

        project_dir = REPO_ROOT
        proj = load_project_team(project_dir)
        roster = derive_team_roster(proj.lead, TEAPARTY_HOME)
        self.assertIsNotNone(
            roster,
            f'derive_team_roster({proj.lead!r}) returned None; the '
            f'project-lead itself is not discoverable.',
        )
        assert roster is not None
        member_names = {m.name for m in roster.members}
        self.assertIn(
            LEAD_NAME, member_names,
            f'project-lead roster must include {LEAD_NAME!r} as a '
            f'member so the project-lead can Delegate to it.  '
            f'Got members {sorted(member_names)}.  Add '
            f'software-development to the project.yaml `workgroups:` '
            f'list AND `members.workgroups:` list.',
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
