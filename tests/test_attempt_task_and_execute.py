"""Specification tests for the `attempt-task` skill and the `execute`
skill's directive update (issue #423).

These pin three things at the source-content level:

1. `attempt-task` exists at the canonical path with the state graph
   `START → EXECUTE → (ASK ↔ EXECUTE) → DELIVER`.

2. `attempt-task`'s EXECUTE step prescribes `Delegate(...)` (not
   `Send`) for dispatching to its members, and prescribes
   `ListTeamMembers` as the team-discovery mechanism — within the
   EXECUTE prose, not merely incidentally in the YAML frontmatter.

3. The project-lead's `execute` skill EXECUTE step prescribes
   `mcp__teaparty-config__Delegate(member, task, skill='attempt-task')`
   for workgroup-lead dispatch with directive language. The old
   wording (*"Delegate work to team members using
   mcp__teaparty-config__Send"*) is removed — without this, project-
   lead dispatch falls back to Send and the workgroup-lead never
   invokes its workflow skill.

Section-scoped assertions (`_section_of`) prevent frontmatter or
incidental prose elsewhere in the file from satisfying a content
check that the issue spec actually targets at a specific step.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _section_of(body: str, heading: str) -> str:
    """Return the body of the section opened by ``## {heading}``.

    Slices from the heading line to the next ``## `` heading (or end
    of file).  The frontmatter block is implicitly excluded because
    it is opened by ``---``, not ``##``.  Used to scope content
    assertions to a specific step of a skill rather than to the whole
    file — without scoping, tokens that legitimately appear in the
    YAML ``allowed-tools`` list or the description satisfy assertions
    the issue spec actually targets at one specific section.
    """
    needle = f'## {heading}\n'
    start = body.find(needle)
    if start == -1:
        return ''
    after = start + len(needle)
    next_heading = body.find('\n## ', after)
    if next_heading == -1:
        return body[after:]
    return body[after:next_heading]


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
        dispatching to members. The directive must live in the EXECUTE
        prose — frontmatter ``allowed-tools:`` listing the name does
        not constitute a procedural directive.
        """
        execute = _section_of(self.SKILL_PATH.read_text(), 'EXECUTE')
        self.assertNotEqual(
            execute, '',
            f'attempt-task must have an `## EXECUTE` section — that '
            f'is the procedural rail for dispatching work.',
        )
        self.assertIn(
            'Delegate(', execute,
            f'attempt-task EXECUTE must contain the `Delegate(` call '
            f'form. A workgroup-lead that uses Send for fresh dispatch '
            f'reproduces the bug at the next nesting level. Got '
            f'EXECUTE section head: {execute[:300]!r}',
        )

    def test_execute_step_names_listteammembers(self) -> None:
        """ListTeamMembers must be the prescribed team-discovery step
        within EXECUTE prose, not merely listed in frontmatter."""
        execute = _section_of(self.SKILL_PATH.read_text(), 'EXECUTE')
        self.assertIn(
            'ListTeamMembers', execute,
            f'attempt-task EXECUTE must direct the lead to '
            f'`ListTeamMembers` as the procedural step that supplies '
            f'the roster. Without this in the EXECUTE body, the model '
            f'defers to its training and may skip the roster lookup, '
            f'then write content directly. Got EXECUTE section head: '
            f'{execute[:300]!r}',
        )

    def test_deliver_step_prescribes_reply_and_commit(self) -> None:
        """DELIVER must name both Reply (the deliverable signal) and a
        commit step (so the work merges through CloseConversation).

        Section-scoped: assertions live within the DELIVER body so
        deleting DELIVER while leaving incidental ``Reply`` / ``commit``
        usage elsewhere in the file would still flip the test.
        """
        deliver = _section_of(self.SKILL_PATH.read_text(), 'DELIVER')
        self.assertNotEqual(
            deliver, '',
            f'attempt-task must have a `## DELIVER` section — that '
            f'is the terminal step that propagates work upward.',
        )
        self.assertIn(
            'Reply', deliver,
            f'attempt-task DELIVER must name `Reply` — the dispatcher '
            f'is signaled by Reply, and without it the workflow has '
            f'no terminal output. Got DELIVER section head: '
            f'{deliver[:300]!r}',
        )
        self.assertIn(
            'git commit', deliver,
            f'attempt-task DELIVER must instruct `git commit` '
            f'before the final Reply. Without commit, the merge '
            f'through CloseConversation propagates an empty session '
            f'branch and the deliverables are stranded. Got DELIVER '
            f'section head: {deliver[:300]!r}',
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

        Section-scoped to EXECUTE so that frontmatter ``allowed-tools``
        listing the name does not satisfy the procedural directive
        requirement.
        """
        execute = _section_of(self.EXECUTE_PATH.read_text(), 'EXECUTE')
        self.assertNotEqual(
            execute, '',
            f'execute skill must have an `## EXECUTE` section.',
        )
        names_tool = (
            'mcp__teaparty-config__Delegate' in execute
            or 'Delegate(' in execute
        )
        self.assertTrue(
            names_tool,
            f'execute EXECUTE must name the `Delegate` tool by its '
            f'qualified MCP name or a call-form (`Delegate(...)`) — '
            f'the bare word "Delegate" already appears as an English '
            f'verb and does not constitute a directive to use the '
            f'new tool. EXECUTE section head: {execute[:400]!r}',
        )

    def test_execute_names_attempt_task_skill(self) -> None:
        """The Delegate call in EXECUTE must name `attempt-task` as the
        workflow skill prescribed for workgroup-leads."""
        execute = _section_of(self.EXECUTE_PATH.read_text(), 'EXECUTE')
        self.assertIn(
            'attempt-task', execute,
            f'execute EXECUTE must name `attempt-task` as the workflow '
            f'skill for workgroup-lead dispatch. The Delegate call '
            f'shape is Delegate(member, task, skill="attempt-task"). '
            f'EXECUTE section head: {execute[:400]!r}',
        )

    def test_old_send_dispatch_wording_removed(self) -> None:
        """The previous *"Delegate work to team members using
        mcp__teaparty-config__Send"* wording must be gone, AND the
        replacement directive must be present. Pinning both halves
        catches an equivalent re-introduction in different prose
        ("Delegate to team members via mcp__teaparty-config__Send")
        that the exact-phrase check alone would miss.
        """
        body = self.EXECUTE_PATH.read_text()
        self.assertNotIn(
            'Delegate work to team members using `mcp__teaparty-config__Send`',
            body,
            f'execute skill still contains the old `Send`-named '
            f'dispatch directive. The fix replaces it with a Delegate '
            f'directive; leaving both produces contradictory '
            f'instructions in the same skill body.',
        )
        # Replacement directive must be present in EXECUTE — without
        # this, a regression that drops the old wording without
        # supplying the new one (a partial revert) passes the negative
        # check vacuously.
        execute = _section_of(body, 'EXECUTE')
        self.assertIn(
            "Delegate(member, task, skill='attempt-task')", execute,
            f'execute EXECUTE must contain the explicit replacement '
            f'directive `Delegate(member, task, skill=\'attempt-task\')`. '
            f'A regression that strips the old Send wording without '
            f'supplying the new directive leaves the EXECUTE step '
            f'without dispatch guidance.',
        )


if __name__ == '__main__':
    unittest.main()
