"""Specification tests for the Delegate MCP tool (issue #423).

`Delegate(member, task, skill=None)` is shape-isomorphic to `Send` plus
two added behaviours that distinguish work dispatch from peer messaging:

1. **Open thread precondition**: when the caller already has an open
   dispatch conversation to *member*, `Delegate` rejects without
   launching anything and names the existing channel so the caller can
   switch to `Send` for follow-up.

2. **Workflow prefix**: when `skill` is set, the recipient's first
   dispatched composite is preceded by a directive naming the skill
   with a leading slash (e.g. `Run the /attempt-task skill...`). This
   routes the message to the model, which invokes the skill via the
   `Skill` tool — the same pattern the engine uses to start
   `intent-alignment` / `planning` / `execute` for project-leads.

Each test is load-bearing: reverting the corresponding production
behaviour must produce a specific, named failure.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.mcp import registry as mcp_registry


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class DelegateReturnShapeTest(unittest.TestCase):
    """Acceptance criterion 1: return shape matches `Send`."""

    def setUp(self) -> None:
        mcp_registry.clear()

    def tearDown(self) -> None:
        mcp_registry.clear()

    def _register_succeeding_spawn(self, captured: list) -> None:
        async def spawn(member, composite, context_id):
            captured.append((member, composite, context_id))
            return ('abc12345', '/tmp/wt', '')
        mcp_registry.register_spawn_fn('caller-agent', spawn)
        mcp_registry.current_agent_name.set('caller-agent')

    def test_delegate_returns_dispatch_conversation_id(self) -> None:
        """A successful Delegate returns JSON whose `conversation_id`
        matches `Send`'s shape: `dispatch:<sid>`.
        """
        from teaparty.mcp.tools.messaging import _default_delegate_post

        captured: list = []
        self._register_succeeding_spawn(captured)
        result = _run(_default_delegate_post(
            'target-member', 'do this work', skill=None,
        ))
        payload = json.loads(result)
        self.assertEqual(
            payload.get('status'), 'message_sent',
            f'Delegate must return status=message_sent on success; '
            f'got: {payload}',
        )
        self.assertTrue(
            payload.get('conversation_id', '').startswith('dispatch:'),
            f'Delegate must return conversation_id of shape '
            f'dispatch:<sid>; got: {payload.get("conversation_id")!r}',
        )


class DelegateWorkflowPrefixTest(unittest.TestCase):
    """Acceptance criteria 3 & 4: skill prefix injection."""

    def setUp(self) -> None:
        mcp_registry.clear()

    def tearDown(self) -> None:
        mcp_registry.clear()

    def _register_capturing_spawn(self, captured: list) -> None:
        async def spawn(member, composite, context_id):
            captured.append({'member': member, 'composite': composite,
                             'context_id': context_id})
            return ('sid123', '/tmp/wt', '')
        mcp_registry.register_spawn_fn('caller-agent', spawn)
        mcp_registry.current_agent_name.set('caller-agent')

    def test_skill_set_injects_directive_naming_skill_with_slash(self) -> None:
        """When `skill='attempt-task'`, the dispatched composite must
        contain a directive that names the skill prefixed with `/`,
        following the same pattern the engine uses for project-leads
        (e.g. `Run the /attempt-task skill...`).

        The prefix is built by ``delegate_handler`` (the public entry
        point) before the post_fn is called, so this test exercises
        the handler — not the bare post_fn — to cover the full path.
        """
        from teaparty.mcp.tools.messaging import delegate_handler

        captured: list = []
        self._register_capturing_spawn(captured)

        async def post(member, composite, skill):
            from teaparty.mcp.tools.messaging import _default_delegate_post
            return await _default_delegate_post(
                member, composite, skill,
            )

        _run(delegate_handler(
            member='workgroup-lead', task='produce a report',
            skill='attempt-task',
            scratch_path='/no/such/scratch',
            post_fn=post,
        ))
        self.assertEqual(len(captured), 1)
        composite = captured[0]['composite']
        self.assertIn(
            '/attempt-task', composite,
            f'Composite must contain `/attempt-task` directive when '
            f'skill is set. Got composite head: {composite[:200]!r}',
        )
        # Spec wording: the composite *begins with* the directive.
        # A regression that swaps composition order to put the directive
        # at the end (or in the middle) would still satisfy a bare
        # ``in`` check but violates the spec. The exact form is bare
        # slash with no backticks — same prose pattern the CfA engine
        # uses for project-lead skills.
        self.assertTrue(
            composite.lstrip().startswith('Run the /attempt-task'),
            f'Composite must START with the skill directive in the '
            f'engine\'s exact prose form (`Run the /<skill> skill...`, '
            f'bare slash, no backticks). Got composite head: '
            f'{composite[:200]!r}',
        )
        # Original task body is preserved.
        self.assertIn(
            'produce a report', composite,
            f'Original task body must survive prefix injection. '
            f'Got composite head: {composite[:200]!r}',
        )

    def test_skill_none_emits_no_skill_directive(self) -> None:
        """When `skill=None`, the composite must contain no `/<skill>`
        directive. Delegate-without-skill is a plain dispatch (the
        recipient processes the task directly, e.g. specialists)."""
        from teaparty.mcp.tools.messaging import delegate_handler

        captured: list = []
        self._register_capturing_spawn(captured)

        async def post(member, composite, skill):
            from teaparty.mcp.tools.messaging import _default_delegate_post
            return await _default_delegate_post(
                member, composite, skill,
            )

        _run(delegate_handler(
            member='specialist', task='small task', skill=None,
            scratch_path='/no/such/scratch',
            post_fn=post,
        ))
        composite = captured[0]['composite']
        # Broad negative-space: no skill directive of any shape may
        # appear when skill=None.  An always-fire regression that
        # rendered ``Run the /None skill...`` would not contain
        # ``/attempt-task`` but would contain the directive opener
        # ``Run the /`` — the broader pattern catches that.
        self.assertNotIn(
            '/attempt-task', composite,
            f'Composite must NOT contain `/attempt-task` when skill=None. '
            f'Got composite head: {composite[:200]!r}',
        )
        self.assertNotIn(
            'Run the /', composite,
            f'Composite must NOT contain any `Run the /<skill>...` '
            f'directive when skill=None — the prefix block must be '
            f'gated by ``if skill:``, not always-fire. '
            f'Got composite head: {composite[:200]!r}',
        )

    def test_skill_attempt_task_composite_contains_task_body(self) -> None:
        """The original task body must appear in the composite, after
        the skill directive. Without this, the recipient runs the
        skill but receives no task — workflow with no work."""
        from teaparty.mcp.tools.messaging import delegate_handler

        captured: list = []
        self._register_capturing_spawn(captured)

        async def post(member, composite, skill):
            from teaparty.mcp.tools.messaging import _default_delegate_post
            return await _default_delegate_post(
                member, composite, skill,
            )

        unique_marker = 'XYZ_TASK_MARKER_42'
        _run(delegate_handler(
            member='workgroup-lead',
            task=f'{unique_marker} the body content here',
            skill='attempt-task',
            scratch_path='/no/such/scratch',
            post_fn=post,
        ))
        composite = captured[0]['composite']
        self.assertIn(
            unique_marker, composite,
            f'Original task body marker {unique_marker!r} must be '
            f'present in the dispatched composite. The skill directive '
            f'must not consume the body. Got: {composite[:300]!r}',
        )


class DelegateInputValidationTest(unittest.TestCase):
    """The handler must reject empty member or empty task."""

    def test_empty_member_raises(self) -> None:
        from teaparty.mcp.tools.messaging import delegate_handler
        with self.assertRaisesRegex(ValueError, 'member'):
            _run(delegate_handler(member='', task='x'))

    def test_empty_task_raises(self) -> None:
        from teaparty.mcp.tools.messaging import delegate_handler
        with self.assertRaisesRegex(ValueError, 'task'):
            _run(delegate_handler(member='m', task=''))


class DelegateRoleConditionalAllowTest(unittest.TestCase):
    """Delegate is granted role-conditionally — only to agents whose
    team roster contains members of role ``project-lead`` or
    ``workgroup-lead``.  Workgroup-leads (whose members are all
    ``workgroup-agent``) and specialists must NOT get Delegate.

    Rationale: ``Delegate``'s ``skill=`` parameter prescribes the
    workflow rail at the recipient.  If the recipient runs no
    workflow, the dispatcher has no use for Delegate's distinguishing
    feature; it should use ``Send`` instead.  Making Delegate
    structurally unavailable to workgroup-leads removes the off-ramp
    that let research-lead pass ``skill='attempt-task'`` to a
    specialist in live joke-book runs.
    """

    def test_delegate_is_not_in_baseline_allow_rules(self) -> None:
        """Pin the negative: Delegate has been moved out of the
        universal baseline so role-conditional injection is the only
        path that grants it.  A regression that re-adds Delegate to
        the baseline would let workgroup-leads see it again.
        """
        from teaparty.runners.launcher import BASELINE_ALLOW_RULES
        self.assertNotIn(
            'mcp__teaparty-config__Delegate', BASELINE_ALLOW_RULES,
            'Delegate must NOT be in BASELINE_ALLOW_RULES — it is '
            'granted role-conditionally by ``_role_implied_tools``. '
            'A regression that re-adds Delegate to the baseline '
            'lets workgroup-leads dispatch with ``skill="attempt-task"``, '
            'which sends specialists down a workflow rail they '
            'cannot run.',
        )

    def _make_team_with_lead_members(self, tmp: str) -> str:
        """Build a teaparty home where ``project-lead`` heads a project
        team whose members are workgroup-leads (``researcher`` is the
        workgroup, with ``research-lead`` as its lead).
        """
        import os as _os
        import textwrap
        tp_home = _os.path.join(tmp, '.teaparty')
        # Management catalog declares the project + workgroup.
        _os.makedirs(_os.path.join(tp_home, 'management'), exist_ok=True)
        with open(_os.path.join(tp_home, 'management', 'teaparty.yaml'), 'w') as f:
            f.write(textwrap.dedent("""\
                name: Management
                description: Test
                lead: office-manager
                humans:
                  decider: tester
                projects:
                - name: TestProject
                  path: project
                  config: .teaparty/project/project.yaml
                members:
                  projects:
                  - TestProject
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
        # Workgroup with a workgroup-lead and one workgroup-agent member.
        wg_dir = _os.path.join(tp_home, 'management', 'workgroups')
        _os.makedirs(wg_dir, exist_ok=True)
        with open(_os.path.join(wg_dir, 'research.yaml'), 'w') as f:
            f.write(textwrap.dedent("""\
                name: Research
                description: Test research workgroup
                lead: research-lead
                members:
                  agents:
                  - researcher
            """))
        # Project tree: project-lead heads a team whose members are
        # workgroup-leads (Research's lead).
        proj_root = _os.path.join(tmp, 'project')
        proj_tp = _os.path.join(proj_root, '.teaparty', 'project')
        _os.makedirs(proj_tp, exist_ok=True)
        with open(_os.path.join(proj_tp, 'project.yaml'), 'w') as f:
            f.write(textwrap.dedent("""\
                name: TestProject
                description: Test project
                lead: project-lead
                humans:
                  decider: tester
                workgroups:
                - name: Research
                  config: workgroups/research.yaml
                members:
                  workgroups:
                  - Research
                  agents: []
            """))
        # Project also needs to know the workgroup config — point at
        # management's copy via path.
        proj_wg_dir = _os.path.join(proj_tp, 'workgroups')
        _os.makedirs(proj_wg_dir, exist_ok=True)
        with open(_os.path.join(proj_wg_dir, 'research.yaml'), 'w') as f:
            f.write(textwrap.dedent("""\
                name: Research
                description: Test research workgroup
                lead: research-lead
                members:
                  agents:
                  - researcher
            """))
        # Agent.md files for project-lead, research-lead, researcher.
        for name in ('project-lead', 'research-lead'):
            d = _os.path.join(tp_home, 'management', 'agents', name)
            _os.makedirs(d, exist_ok=True)
            with open(_os.path.join(d, 'agent.md'), 'w') as f:
                f.write(f'---\nname: {name}\n---\nbody\n')
            with open(_os.path.join(d, 'settings.yaml'), 'w') as f:
                f.write('permissions:\n  allow:\n  - Read\n')
        d = _os.path.join(tp_home, 'management', 'agents', 'researcher')
        _os.makedirs(d, exist_ok=True)
        with open(_os.path.join(d, 'agent.md'), 'w') as f:
            f.write('---\nname: researcher\n---\nspecialist body\n')
        with open(_os.path.join(d, 'settings.yaml'), 'w') as f:
            f.write('permissions:\n  allow:\n  - Read\n')
        return tp_home

    def test_project_lead_gets_delegate(self) -> None:
        """A project-lead's roster has workgroup-leads as members, so
        Delegate is granted via role-conditional injection."""
        import json
        import os as _os
        import tempfile
        from teaparty.runners.launcher import compose_launch_config

        with tempfile.TemporaryDirectory() as tmp:
            tp_home = self._make_team_with_lead_members(tmp)
            config_dir = _os.path.join(tmp, 'cfg-pl')
            compose_launch_config(
                config_dir=config_dir,
                agent_name='project-lead',
                scope='management',
                teaparty_home=tp_home,
            )
            with open(_os.path.join(config_dir, 'settings.json')) as f:
                composed = json.load(f)
            allow = (composed.get('permissions') or {}).get('allow') or []
            self.assertIn(
                'mcp__teaparty-config__Delegate', allow,
                f'project-lead must receive Delegate via role-conditional '
                f'injection (its roster has workgroup-lead members). '
                f'Got allow: {allow}',
            )

    def test_workgroup_lead_does_not_get_delegate(self) -> None:
        """A workgroup-lead's roster has only workgroup-agent members,
        so Delegate must NOT be granted.  Workgroup-leads dispatch to
        specialists via Send, not Delegate."""
        import json
        import os as _os
        import tempfile
        from teaparty.runners.launcher import compose_launch_config

        with tempfile.TemporaryDirectory() as tmp:
            tp_home = self._make_team_with_lead_members(tmp)
            config_dir = _os.path.join(tmp, 'cfg-wl')
            compose_launch_config(
                config_dir=config_dir,
                agent_name='research-lead',
                scope='management',
                teaparty_home=tp_home,
            )
            with open(_os.path.join(config_dir, 'settings.json')) as f:
                composed = json.load(f)
            allow = (composed.get('permissions') or {}).get('allow') or []
            self.assertNotIn(
                'mcp__teaparty-config__Delegate', allow,
                f'workgroup-lead must NOT receive Delegate — its '
                f'members are workgroup-agents (specialists), which '
                f'run no workflow skill on dispatch. Workgroup-leads '
                f'use Send for thread opening. Granting Delegate here '
                f'creates the off-ramp that lets the workgroup-lead '
                f'pass ``skill=\'attempt-task\'`` to a specialist '
                f'(observed in live joke-book runs).  Got allow: {allow}',
            )

    def test_specialist_does_not_get_delegate(self) -> None:
        """A specialist (no team) must not have Delegate."""
        import json
        import os as _os
        import tempfile
        from teaparty.runners.launcher import compose_launch_config

        with tempfile.TemporaryDirectory() as tmp:
            tp_home = self._make_team_with_lead_members(tmp)
            config_dir = _os.path.join(tmp, 'cfg-spec')
            compose_launch_config(
                config_dir=config_dir,
                agent_name='researcher',
                scope='management',
                teaparty_home=tp_home,
            )
            with open(_os.path.join(config_dir, 'settings.json')) as f:
                composed = json.load(f)
            allow = (composed.get('permissions') or {}).get('allow') or []
            self.assertNotIn(
                'mcp__teaparty-config__Delegate', allow,
                f'specialist must NOT receive Delegate — specialists '
                f'do not dispatch. Got allow: {allow}',
            )


class ToolDescriptionDisambiguationTest(unittest.TestCase):
    """Send and Delegate must describe themselves so a model picking
    between them at choice-time has unambiguous guidance.

    The bug class this guards against: a workgroup-lead with both
    Send and Delegate in its catalog defaulting to Send (its trained
    instinct) for a fresh dispatch — exactly the failure mode that
    motivated #423 at the project-lead level.  Fixing the catalog
    ontology without fixing the descriptions would leave the
    confusion vector open at every nesting level.
    """

    def test_send_docstring_scopes_to_continuation_or_peer(self) -> None:
        """Send's tool docstring must NOT describe it as opening new
        dispatch threads — that role belongs to Delegate now."""
        from teaparty.mcp.server import main as _server_main
        import inspect
        src = inspect.getsource(_server_main.create_server)
        # Locate the Send tool definition.  Fragile to refactor but
        # acceptable: the bug class is "Send still claims to dispatch."
        send_idx = src.find('async def Send(')
        self.assertGreater(send_idx, -1)
        # Read the docstring block following ``async def Send``.
        next_def = src.find('async def ', send_idx + 1)
        send_block = src[send_idx:next_def] if next_def > 0 else src[send_idx:]
        self.assertIn(
            'Continue', send_block,
            f'Send docstring must scope itself to thread continuation '
            f'or peer messaging. The old "opening or continuing" '
            f'wording leaves the dispatch role ambiguous, defeating '
            f'the verb-tool split #423 introduces.',
        )
        self.assertIn(
            'Delegate', send_block,
            f'Send docstring must point the agent at Delegate for '
            f'opening new dispatch threads. Without this redirect, '
            f'an agent picking between the two tools may default to '
            f'its trained Send-as-dispatch instinct.',
        )

    def test_delegate_docstring_describes_open_thread_role(self) -> None:
        """Delegate's tool docstring must position it as the
        open-new-thread verb, not as a generic dispatch alternative."""
        from teaparty.mcp.server import main as _server_main
        import inspect
        src = inspect.getsource(_server_main.create_server)
        delegate_idx = src.find('async def Delegate(')
        self.assertGreater(delegate_idx, -1)
        block = src[max(0, delegate_idx - 2000):delegate_idx]
        # Either ``new dispatch thread`` or ``fresh dispatch thread`` —
        # the framing is what matters, not the specific adjective.
        opens_thread = (
            'new dispatch thread' in block
            or 'fresh dispatch thread' in block
        )
        self.assertTrue(
            opens_thread,
            f'Delegate docstring must describe its role as opening a '
            f'(new|fresh) dispatch thread — the verb the issue spec '
            f'assigns to it. Without this framing, the tool-choice '
            f'signal at agent decision time is muddled.',
        )


if __name__ == '__main__':
    unittest.main()
