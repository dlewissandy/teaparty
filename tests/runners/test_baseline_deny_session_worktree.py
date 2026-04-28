"""Regression: baseline deny rules must not catch session worktree paths.

The deny list protects load-bearing TeaParty config — agent
definitions, skill bodies, workgroup rosters, top-level YAMLs.  An
earlier, broader form of the rules used ``*/.teaparty/management/**``
and ``*/.teaparty/project/**`` patterns, which also matched
dispatched-task worktrees living under
``.teaparty/management/sessions/<sid>/worktree/`` and the equivalent
under ``project``.  When an agent tried to write its own deliverable
inside its own worktree, the broad pattern fired and Claude Code
surfaced a permission prompt to the user, blocking the task.

This test pins the contract: the deny list catches the catalog files
and the top-level YAMLs, and *misses* anything under ``sessions/`` or
``jobs/``.  Pattern matching here mirrors Claude Code's permission
glob semantics: ``**`` crosses directory boundaries, ``*`` does not.
"""
from __future__ import annotations

import fnmatch
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.runners.launcher import BASELINE_DENY_RULES


def _matches_any_deny_rule(tool: str, path: str) -> bool:
    """True iff a ``Tool(path)`` invocation is denied by the baseline.

    Translates the rule's glob (after stripping ``Tool(`` / ``)``) to a
    regex that interprets ``**`` as "any number of path segments" and
    ``*`` as "any characters except path separators" — Claude Code's
    permission semantics.  A simple ``fnmatch`` wouldn't work because
    fnmatch's ``*`` greedily matches ``/`` too.
    """
    prefix = f'{tool}('
    for rule in BASELINE_DENY_RULES:
        if not rule.startswith(prefix) or not rule.endswith(')'):
            continue
        glob = rule[len(prefix):-1]
        if _glob_match(glob, path):
            return True
    return False


def _glob_match(glob: str, path: str) -> bool:
    """Match ``path`` against a Claude-Code-style permission glob.

    Claude Code's permission matcher treats both ``*`` and ``**`` as
    crossing path separators in this context — observed empirically:
    the previously-broad ``Write(*/.teaparty/management/**)`` rule did
    block writes to ``/Users/.../teaparty/.teaparty/management/...``
    despite the leading prefix containing several ``/`` segments.  The
    wildcards are effectively interchangeable for permission patterns
    that anchor on a substring of the absolute path.
    """
    parts = re.split(r'(\*\*|\*)', glob)
    pieces: list[str] = []
    for part in parts:
        if part in ('*', '**'):
            pieces.append('.*')
        else:
            pieces.append(re.escape(part))
    pattern = '^' + ''.join(pieces) + '$'
    return re.match(pattern, path) is not None


class BaselineDenyTest(unittest.TestCase):
    """The deny list must protect config without trapping worktrees."""

    # ── Worktree paths must NOT be denied ─────────────────────────────────

    def test_management_session_worktree_write_allowed(self) -> None:
        """The reported research-lead failure: writing inside a
        management-scope dispatched-task worktree must not be denied.
        """
        path = (
            '/Users/darrell/git/teaparty/.teaparty/management/sessions/'
            '2796a395922f/worktree/research/corpus.md'
        )
        self.assertFalse(
            _matches_any_deny_rule('Write', path),
            f'Write to in-worktree file must not be denied: {path}',
        )
        self.assertFalse(_matches_any_deny_rule('Edit', path))

    def test_project_session_metadata_write_allowed(self) -> None:
        """Project-scope session directories aren't worktrees, but the
        deny list still must not block writes to them as a class.
        """
        path = (
            '/Users/darrell/git/joke-book/.teaparty/project/sessions/'
            '20260422-134807-242266/metadata.json'
        )
        self.assertFalse(_matches_any_deny_rule('Write', path))

    def test_cfa_job_worktree_write_allowed(self) -> None:
        """CfA-job worktrees live at ``.teaparty/jobs/<job>/worktree/``."""
        path = (
            '/Users/darrell/git/joke-book/.teaparty/jobs/'
            'job-20260427-183123-506824--i-would-like-a-book-on-the-uni/'
            'worktree/INTENT.md'
        )
        self.assertFalse(_matches_any_deny_rule('Write', path))
        self.assertFalse(_matches_any_deny_rule('Edit', path))

    def test_management_session_nested_write_allowed(self) -> None:
        """Deeply nested writes inside a session worktree must be allowed."""
        path = (
            '/Users/darrell/git/teaparty/.teaparty/management/sessions/'
            'abc123/worktree/.scratch/research-brief.md'
        )
        self.assertFalse(_matches_any_deny_rule('Write', path))

    # ── Catalog paths MUST be denied ──────────────────────────────────────

    def test_management_agent_definition_denied(self) -> None:
        path = '/repo/.teaparty/management/agents/office-manager/agent.md'
        self.assertTrue(_matches_any_deny_rule('Write', path))
        self.assertTrue(_matches_any_deny_rule('Edit', path))

    def test_management_skill_definition_denied(self) -> None:
        path = '/repo/.teaparty/management/skills/planning/SKILL.md'
        self.assertTrue(_matches_any_deny_rule('Write', path))
        self.assertTrue(_matches_any_deny_rule('Edit', path))

    def test_management_workgroup_config_denied(self) -> None:
        path = '/repo/.teaparty/management/workgroups/coding.yaml'
        self.assertTrue(_matches_any_deny_rule('Write', path))

    def test_management_top_level_yaml_denied(self) -> None:
        for name in (
            'teaparty.yaml',
            'settings.yaml',
            'external-projects.yaml',
        ):
            with self.subTest(name=name):
                path = f'/repo/.teaparty/management/{name}'
                self.assertTrue(_matches_any_deny_rule('Write', path))

    def test_project_agent_definition_denied(self) -> None:
        path = '/repo/.teaparty/project/agents/lead/agent.md'
        self.assertTrue(_matches_any_deny_rule('Write', path))

    def test_project_skill_definition_denied(self) -> None:
        path = '/repo/.teaparty/project/skills/foo/SKILL.md'
        self.assertTrue(_matches_any_deny_rule('Write', path))

    def test_project_workgroup_config_denied(self) -> None:
        path = '/repo/.teaparty/project/workgroups/coding.yaml'
        self.assertTrue(_matches_any_deny_rule('Write', path))

    def test_project_yaml_denied(self) -> None:
        path = '/repo/.teaparty/project/project.yaml'
        self.assertTrue(_matches_any_deny_rule('Write', path))

    def test_top_level_teaparty_yaml_denied(self) -> None:
        path = '/repo/.teaparty/teaparty.yaml'
        self.assertTrue(_matches_any_deny_rule('Write', path))


if __name__ == '__main__':
    unittest.main()
