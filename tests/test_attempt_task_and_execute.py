"""Specification tests for the `attempt-task` skill and the `execute`
skill's directive update (issue #423).

These pin three things at the source-content level:

1. `attempt-task` exists at the canonical path with the state graph
   `START → EXECUTE → (ASK ↔ EXECUTE) → DELIVER`.

2. `attempt-task`'s EXECUTE step prescribes `Delegate(...)` (not
   `Send`) for dispatching to its members, and prescribes
   `ListTeamMembers` as the team-discovery mechanism.

3. The project-lead's `execute` skill EXECUTE step prescribes
   `mcp__teaparty-config__Delegate(member, task, skill='attempt-task')`
   for workgroup-lead dispatch with directive language. The old
   wording (*"Delegate work to team members using
   mcp__teaparty-config__Send"*) is removed — without this, project-
   lead dispatch falls back to Send and the workgroup-lead never
   invokes its workflow skill.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))


class AttemptTaskSkillExistsTest(unittest.TestCase):
    """The skill file must exist at the canonical path."""

    SKILL_PATH = REPO_ROOT / '.teaparty/management/skills/attempt-task/SKILL.md'

    def test_skill_file_exists(self) -> None:
        self.assertTrue(
            self.SKILL_PATH.is_file(),
            f'attempt-task skill must exist at {self.SKILL_PATH}. '
            f'Without it, compose-time staging has nothing to copy '
            f'and `/attempt-task` invocations on workgroup-leads fail.',
        )

    def test_state_graph_present(self) -> None:
        """All four state names must appear as headings or strong markers."""
        body = self.SKILL_PATH.read_text()
        for state in ('START', 'EXECUTE', 'ASK', 'DELIVER'):
            self.assertIn(
                state, body,
                f'State {state!r} must appear in the skill body — the '
                f'skill encodes the state graph START → EXECUTE → '
                f'(ASK ↔ EXECUTE) → DELIVER. Missing state collapses '
                f'the workflow.',
            )

    def test_execute_step_prescribes_delegate_not_send(self) -> None:
        """The EXECUTE step must direct the lead to use Delegate for
        dispatching to members. Send is for thread continuation, not
        for opening dispatch threads."""
        body = self.SKILL_PATH.read_text()
        self.assertIn(
            'Delegate', body,
            f'attempt-task EXECUTE must name `Delegate` as the dispatch '
            f'verb. A workgroup-lead that uses Send for fresh dispatch '
            f'reproduces the bug at the next nesting level.',
        )

    def test_execute_step_names_listteammembers(self) -> None:
        """ListTeamMembers must be the prescribed team-discovery step."""
        body = self.SKILL_PATH.read_text()
        self.assertIn(
            'ListTeamMembers', body,
            f'attempt-task must direct the lead to `ListTeamMembers` '
            f'as the procedural step that supplies the roster — without '
            f'this, the model defers to its training and may skip the '
            f'roster lookup, then write content directly.',
        )

    def test_deliver_step_prescribes_reply_and_commit(self) -> None:
        """DELIVER must name both Reply (the deliverable signal) and a
        commit step (so the work merges through CloseConversation)."""
        body = self.SKILL_PATH.read_text()
        self.assertIn(
            'Reply', body,
            f'attempt-task DELIVER must name `Reply` — the dispatcher '
            f'is signaled by Reply, and without it the workflow has '
            f'no terminal output.',
        )
        # Some marker for "commit" — git commit, commit the assembled,
        # etc. The exact wording is flexible; the requirement is that
        # the skill instructs committing before Reply.
        body_lower = body.lower()
        self.assertIn(
            'commit', body_lower,
            f'attempt-task DELIVER must instruct the lead to commit '
            f'the assembled state before Reply. Without commit, the '
            f'merge through CloseConversation propagates an empty '
            f'session branch and the deliverables are stranded.',
        )


class ExecuteSkillDirectiveTest(unittest.TestCase):
    """The project-lead's `execute` skill must prescribe `Delegate`."""

    EXECUTE_PATH = REPO_ROOT / '.teaparty/management/skills/execute/SKILL.md'

    def test_execute_skill_exists(self) -> None:
        self.assertTrue(
            self.EXECUTE_PATH.is_file(),
            f'execute skill must exist at {self.EXECUTE_PATH}',
        )

    def test_execute_names_delegate_for_dispatch(self) -> None:
        """The EXECUTE step must name `Delegate` as the dispatch *tool*,
        not merely use `delegate` as an English verb. The qualified
        tool name `mcp__teaparty-config__Delegate` (or a `Delegate(`
        call form) distinguishes the directive from the existing
        `"Delegate work to team members"` prose.
        """
        body = self.EXECUTE_PATH.read_text()
        names_tool = (
            'mcp__teaparty-config__Delegate' in body
            or 'Delegate(' in body
        )
        self.assertTrue(
            names_tool,
            f'execute skill must name the `Delegate` tool by its '
            f'qualified MCP name or a call-form (`Delegate(...)`) — '
            f'the bare word "Delegate" already appears as an English '
            f'verb in the existing body and does not constitute a '
            f'directive to use the new tool.',
        )

    def test_execute_names_attempt_task_skill(self) -> None:
        """The Delegate call must name `attempt-task` as the workflow
        skill prescribed for workgroup-leads."""
        body = self.EXECUTE_PATH.read_text()
        self.assertIn(
            'attempt-task', body,
            f'execute skill must name `attempt-task` as the workflow '
            f'skill for workgroup-lead dispatch. The Delegate call '
            f'shape is Delegate(member, task, skill="attempt-task").',
        )

    def test_old_send_dispatch_wording_removed(self) -> None:
        """The previous *"Delegate work to team members using
        mcp__teaparty-config__Send"* wording must be gone — leaving it
        creates a contradictory instruction in the same skill body."""
        body = self.EXECUTE_PATH.read_text()
        self.assertNotIn(
            'Delegate work to team members using `mcp__teaparty-config__Send`',
            body,
            f'execute skill still contains the old `Send`-named '
            f'dispatch directive. The fix replaces it with a Delegate '
            f'directive; leaving both produces contradictory '
            f'instructions in the same skill body.',
        )


if __name__ == '__main__':
    unittest.main()
