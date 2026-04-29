"""Specification tests for compose-time staging of `attempt-task`
on workgroup-leads (issue #423).

The skill must reach a workgroup-lead's launch path without the
agent.md frontmatter being edited. `derive_team_roster` recognizes
the agent's role; the launcher stages the skill when the role is
`workgroup-lead`.

Two launch paths must be covered:

- **Worktree-tier** (`compose_launch_worktree`): dispatched workgroup-
  leads launched in a job worktree. The skill body must end up at
  `{worktree}/.claude/skills/attempt-task/SKILL.md`.

- **Chat-tier** (`compose_launch_config`): the skill must be staged
  into the agent's `CLAUDE_CONFIG_DIR/skills/` so the slash command
  resolves on launch.

Specialists and project-leads must NOT receive `attempt-task` via
auto-staging (their frontmatter does not list it; auto-staging is
role-conditioned). This negative-space assertion catches the bug
where the staging predicate is too permissive.
"""
from __future__ import annotations

import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _make_teaparty_home_with_workgroup(tmp: str) -> str:
    """Build a minimal teaparty home where `research-lead` is a
    workgroup-lead with a `researcher` member. Returns the home path."""
    tp_home = os.path.join(tmp, '.teaparty')

    # ── Top-level teaparty.yaml (declares management catalog) ───────
    os.makedirs(os.path.join(tp_home, 'management'), exist_ok=True)
    with open(os.path.join(tp_home, 'management', 'teaparty.yaml'), 'w') as f:
        f.write(textwrap.dedent("""\
            name: Management
            description: Test management.
            lead: office-manager
            humans:
              decider: tester
            projects: []
            members:
              workgroups:
              - Research
              agents: []
              skills: []
            workgroups:
            - name: Research
              config: workgroups/research.yaml
            stats:
              storage: .teaparty/stats/management.json
        """))

    # ── Research workgroup ─────────────────────────────────────────
    wg_dir = os.path.join(tp_home, 'management', 'workgroups')
    os.makedirs(wg_dir, exist_ok=True)
    with open(os.path.join(wg_dir, 'research.yaml'), 'w') as f:
        f.write(textwrap.dedent("""\
            name: Research
            description: Test research workgroup
            lead: research-lead
            members:
              agents:
              - researcher
        """))

    # ── research-lead agent.md ─────────────────────────────────────
    rl_dir = os.path.join(tp_home, 'management', 'agents', 'research-lead')
    os.makedirs(rl_dir, exist_ok=True)
    with open(os.path.join(rl_dir, 'agent.md'), 'w') as f:
        f.write('---\nname: research-lead\n---\nlead body\n')
    with open(os.path.join(rl_dir, 'settings.yaml'), 'w') as f:
        f.write('permissions:\n  allow:\n  - Read\n')

    # ── researcher specialist agent.md ─────────────────────────────
    res_dir = os.path.join(tp_home, 'management', 'agents', 'researcher')
    os.makedirs(res_dir, exist_ok=True)
    with open(os.path.join(res_dir, 'agent.md'), 'w') as f:
        f.write('---\nname: researcher\n---\nspecialist body\n')

    # ── attempt-task skill (the canonical body the launcher copies) ─
    skill_dir = os.path.join(tp_home, 'management', 'skills', 'attempt-task')
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, 'SKILL.md'), 'w') as f:
        f.write(textwrap.dedent("""\
            ---
            name: attempt-task
            description: Test stub
            ---
            # Test stub body
        """))

    return tp_home


class AttemptTaskStagingChatTierTest(unittest.TestCase):
    """`compose_launch_config` stages `attempt-task` for workgroup-leads.

    Chat-tier staging targets ``$CLAUDE_CONFIG_DIR/skills/`` — the
    discovery path Claude Code's headless ``Skill`` tool reads.  In
    these tests the dir is set to a temp path so the assertion
    inspects per-test state, not the test runner's dotfiles.
    """

    def setUp(self) -> None:
        self._prior_env = os.environ.get('CLAUDE_CONFIG_DIR')

    def tearDown(self) -> None:
        if self._prior_env is None:
            os.environ.pop('CLAUDE_CONFIG_DIR', None)
        else:
            os.environ['CLAUDE_CONFIG_DIR'] = self._prior_env

    def test_workgroup_lead_chat_tier_gets_attempt_task(self) -> None:
        from teaparty.runners.launcher import compose_launch_config

        with tempfile.TemporaryDirectory() as tmp:
            tp_home = _make_teaparty_home_with_workgroup(tmp)
            claude_home = os.path.join(tmp, 'claude-home')
            os.environ['CLAUDE_CONFIG_DIR'] = claude_home
            config_dir = os.path.join(tmp, 'cfg')
            compose_launch_config(
                config_dir=config_dir,
                agent_name='research-lead',
                scope='management',
                teaparty_home=tp_home,
            )
            staged = os.path.join(
                claude_home, 'skills', 'attempt-task', 'SKILL.md',
            )
            self.assertTrue(
                os.path.isfile(staged),
                f'compose_launch_config must stage attempt-task for '
                f'a workgroup-lead at {staged!r}. Without staging the '
                f'recipient cannot resolve the `/attempt-task` skill '
                f'invocation that Delegate prepends.',
            )
            # Verify the staged file is the skill body, not an empty
            # file or a wrong-source copy. The fixture wrote a known
            # marker to the canonical skill path; the staged copy must
            # round-trip it.
            self.assertIn(
                'Test stub body',
                Path(staged).read_text(),
                f'Staged attempt-task at {staged!r} does not contain '
                f'the expected fixture body. The staging path is wrong, '
                f'or the copy is incomplete/empty.',
            )

    def test_specialist_chat_tier_does_not_get_attempt_task(self) -> None:
        """A specialist whose frontmatter does not list attempt-task
        must not receive it via auto-staging — the staging predicate
        is role-conditioned, not blanket."""
        from teaparty.runners.launcher import compose_launch_config

        with tempfile.TemporaryDirectory() as tmp:
            tp_home = _make_teaparty_home_with_workgroup(tmp)
            claude_home = os.path.join(tmp, 'claude-home')
            os.environ['CLAUDE_CONFIG_DIR'] = claude_home
            config_dir = os.path.join(tmp, 'cfg')
            compose_launch_config(
                config_dir=config_dir,
                agent_name='researcher',
                scope='management',
                teaparty_home=tp_home,
            )
            staged = os.path.join(
                claude_home, 'skills', 'attempt-task', 'SKILL.md',
            )
            self.assertFalse(
                os.path.isfile(staged),
                f'compose_launch_config must NOT auto-stage attempt-task '
                f'for a specialist. Staging is role-conditioned to '
                f'workgroup-leads. Found at: {staged!r}',
            )


class AttemptTaskStagingWorktreeTierTest(unittest.TestCase):
    """`compose_launch_worktree` stages `attempt-task` for workgroup-leads."""

    def test_workgroup_lead_worktree_tier_gets_attempt_task(self) -> None:
        from teaparty.runners.launcher import compose_launch_worktree

        with tempfile.TemporaryDirectory() as tmp:
            tp_home = _make_teaparty_home_with_workgroup(tmp)
            worktree = os.path.join(tmp, 'wt')
            os.makedirs(worktree)
            compose_launch_worktree(
                worktree=worktree,
                agent_name='research-lead',
                scope='management',
                teaparty_home=tp_home,
            )
            staged = os.path.join(
                worktree, '.claude', 'skills', 'attempt-task', 'SKILL.md',
            )
            self.assertTrue(
                os.path.isfile(staged),
                f'compose_launch_worktree must stage attempt-task for '
                f'a workgroup-lead at {staged!r}. Without staging, '
                f'dispatched workgroup-leads cannot resolve the '
                f'`/attempt-task` slash invocation.',
            )
            self.assertIn(
                'Test stub body',
                Path(staged).read_text(),
                f'Staged attempt-task at {staged!r} does not contain '
                f'the expected fixture body. The staging path is wrong, '
                f'or the copy is incomplete/empty.',
            )

    def test_specialist_worktree_tier_does_not_get_attempt_task(self) -> None:
        from teaparty.runners.launcher import compose_launch_worktree

        with tempfile.TemporaryDirectory() as tmp:
            tp_home = _make_teaparty_home_with_workgroup(tmp)
            worktree = os.path.join(tmp, 'wt-spec')
            os.makedirs(worktree)
            compose_launch_worktree(
                worktree=worktree,
                agent_name='researcher',
                scope='management',
                teaparty_home=tp_home,
            )
            staged = os.path.join(
                worktree, '.claude', 'skills', 'attempt-task', 'SKILL.md',
            )
            self.assertFalse(
                os.path.isfile(staged),
                f'compose_launch_worktree must NOT auto-stage '
                f'attempt-task for a specialist. Staging is '
                f'role-conditioned to workgroup-leads. Found at: '
                f'{staged!r}',
            )


class AttemptTaskStagingRosterFailureTest(unittest.TestCase):
    """Compose must not crash if roster lookup fails — graceful no-op."""

    def setUp(self) -> None:
        self._prior_env = os.environ.get('CLAUDE_CONFIG_DIR')

    def tearDown(self) -> None:
        if self._prior_env is None:
            os.environ.pop('CLAUDE_CONFIG_DIR', None)
        else:
            os.environ['CLAUDE_CONFIG_DIR'] = self._prior_env

    def test_compose_does_not_crash_on_missing_workgroup_config(self) -> None:
        """If `derive_team_roster` returns None (config missing,
        unknown agent name, etc.), the launcher logs and proceeds
        without staging attempt-task. Compose must not raise."""
        from teaparty.runners.launcher import compose_launch_config

        with tempfile.TemporaryDirectory() as tmp:
            # No teaparty.yaml at all — roster lookup will return None.
            tp_home = os.path.join(tmp, '.teaparty')
            os.makedirs(os.path.join(
                tp_home, 'management', 'agents', 'unknown-agent'))
            with open(os.path.join(
                    tp_home, 'management', 'agents',
                    'unknown-agent', 'agent.md'), 'w') as f:
                f.write('---\nname: unknown-agent\n---\nbody\n')

            claude_home = os.path.join(tmp, 'claude-home')
            os.environ['CLAUDE_CONFIG_DIR'] = claude_home
            config_dir = os.path.join(tmp, 'cfg-unknown')
            # Must not raise.
            compose_launch_config(
                config_dir=config_dir,
                agent_name='unknown-agent',
                scope='management',
                teaparty_home=tp_home,
            )
            # And the skill is not staged (because roster said it's not a lead).
            staged = os.path.join(
                claude_home, 'skills', 'attempt-task', 'SKILL.md',
            )
            self.assertFalse(
                os.path.isfile(staged),
                f'When roster lookup is inconclusive, attempt-task '
                f'must NOT be staged (no role inference from a missing '
                f'config). Found at: {staged!r}',
            )


if __name__ == '__main__':
    unittest.main()
