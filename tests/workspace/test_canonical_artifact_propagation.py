"""Canonical CfA artifacts propagate to dispatched worker worktrees.

INTENT.md, PLAN.md, WORK_SUMMARY.md, and IDEA.md are gitignored — they
describe the work, they are not the work — so git worktree branching
alone does not carry them.  ``create_subchat_worktree`` copies them
explicitly at spawn time, so every dispatched worker boots with the
parent's *current* version (whatever the parent has revised in place).

The skill prompts forbid renaming on edit (``REVISED_PLAN.md``,
``APPROVED_PLAN.md``, etc.) because the copy is by canonical name —
a rename defeats it.

This test pins the contract: when the parent has these files at the
worktree root, ``create_subchat_worktree`` copies them; when missing,
it doesn't fail.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.workspace.worktree import (
    CANONICAL_ARTIFACT_NAMES,
    create_subchat_worktree,
)


def _git(*args, cwd: str) -> None:
    subprocess.run(
        ['git', *args], cwd=cwd, check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


class CanonicalArtifactPropagationTest(unittest.TestCase):
    """Each gitignored canonical artifact in the parent reaches the child."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='canon-artifact-')
        self.repo = os.path.join(self._tmp, 'repo')
        os.makedirs(self.repo)
        _git('init', '-q', '-b', 'main', cwd=self.repo)
        _git('config', 'user.email', 'test@test', cwd=self.repo)
        _git('config', 'user.name', 'Test', cwd=self.repo)
        # First commit so HEAD is valid.
        with open(os.path.join(self.repo, 'README.md'), 'w') as f:
            f.write('# repo\n')
        _git('add', '.', cwd=self.repo)
        _git('commit', '-q', '-m', 'init', cwd=self.repo)
        # Parent worktree on its own branch so it can stay checked out.
        self.parent_wt = os.path.join(self._tmp, 'parent-wt')
        _git(
            'worktree', 'add', '-q', '-b', 'parent', self.parent_wt, 'main',
            cwd=self.repo,
        )

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _create_child(self, child_path: str, branch: str) -> None:
        asyncio.run(create_subchat_worktree(
            source_repo=self.parent_wt,
            source_ref='HEAD',
            dest_path=child_path,
            branch_name=branch,
            parent_worktree=self.parent_wt,
        ))

    def test_canonical_artifact_set_is_known(self) -> None:
        """The list is what we expect."""
        self.assertEqual(
            set(CANONICAL_ARTIFACT_NAMES),
            {'IDEA.md', 'INTENT.md', 'PLAN.md', 'WORK_SUMMARY.md'},
        )

    def test_plan_md_copies_to_child(self) -> None:
        """Parent's PLAN.md ends up at the same path in the child."""
        with open(os.path.join(self.parent_wt, 'PLAN.md'), 'w') as f:
            f.write('# Plan v3 — current\n\n- step one\n')
        child = os.path.join(self._tmp, 'child-wt')
        self._create_child(child, 'session/test')
        with open(os.path.join(child, 'PLAN.md')) as f:
            self.assertIn('Plan v3 — current', f.read())

    def test_all_four_canonical_artifacts_copy(self) -> None:
        """Every name in the canonical set is propagated when present."""
        for name in CANONICAL_ARTIFACT_NAMES:
            with open(os.path.join(self.parent_wt, name), 'w') as f:
                f.write(f'# {name}\n')
        child = os.path.join(self._tmp, 'child-wt')
        self._create_child(child, 'session/all')
        for name in CANONICAL_ARTIFACT_NAMES:
            self.assertTrue(
                os.path.isfile(os.path.join(child, name)),
                f'{name} should propagate to child',
            )

    def test_revised_plan_md_overrides_old(self) -> None:
        """The user's reported scenario, fixed.

        Parent revises PLAN.md in place.  Child sees the revision,
        not the prior version.  (The previous version is gone — git
        history preserves it on the parent's branch, but the
        propagation copy uses whatever's on disk now.)
        """
        # First version.
        plan = os.path.join(self.parent_wt, 'PLAN.md')
        with open(plan, 'w') as f:
            f.write('# Plan v1\n')
        # Revise in place.
        with open(plan, 'w') as f:
            f.write('# Plan v2 — revised\n')
        child = os.path.join(self._tmp, 'child-wt')
        self._create_child(child, 'session/revised')
        with open(os.path.join(child, 'PLAN.md')) as f:
            content = f.read()
        self.assertIn('Plan v2 — revised', content)
        self.assertNotIn('Plan v1', content)

    def test_renamed_file_does_not_propagate(self) -> None:
        """The failure mode the skill prompts forbid.

        If the parent writes APPROVED_PLAN.md instead of editing
        PLAN.md in place, the canonical-name copy can't pick it up.
        Documenting this here makes the contract testable.
        """
        with open(os.path.join(self.parent_wt, 'APPROVED_PLAN.md'), 'w') as f:
            f.write('# the actually approved plan\n')
        child = os.path.join(self._tmp, 'child-wt')
        self._create_child(child, 'session/rename')
        # APPROVED_PLAN.md is not in the canonical set, so it doesn't
        # arrive.  PLAN.md (which the parent never wrote) also doesn't
        # arrive.  The child has no plan.
        self.assertFalse(
            os.path.isfile(os.path.join(child, 'APPROVED_PLAN.md')),
        )
        self.assertFalse(
            os.path.isfile(os.path.join(child, 'PLAN.md')),
        )

    def test_missing_artifact_does_not_fail(self) -> None:
        """Parents that haven't written every artifact yet still spawn."""
        # No artifact files in parent.
        child = os.path.join(self._tmp, 'child-wt')
        # Should not raise.
        self._create_child(child, 'session/none')
        for name in CANONICAL_ARTIFACT_NAMES:
            self.assertFalse(
                os.path.isfile(os.path.join(child, name)),
            )


if __name__ == '__main__':
    unittest.main()
