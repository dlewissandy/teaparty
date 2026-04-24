"""Tests for ``teaparty.learning.phase_hooks``.

Cut 21 extracted two phase-completion hooks out of engine.py:

- ``archive_skill_correction`` — archives a corrected skill-derived
  plan when planning produced something different from the template.
- ``try_write_premortem`` — writes a premortem at planning→execution,
  swallowing all errors so a learning failure can't abort the session.

These tests pin down the behavioral contract — particularly the no-op
branches (no active skill, no PLAN.md, plan unchanged from template),
the boolean return signaling "consumed the active skill", and the
swallow-errors invariant on ``try_write_premortem``.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from teaparty.learning.phase_hooks import (
    archive_skill_correction,
    try_write_premortem,
)


# ── archive_skill_correction ───────────────────────────────────────────────

class TestArchiveSkillCorrection(unittest.TestCase):
    """Behavior of the planning-phase skill-correction archive hook."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._wt = os.path.join(self._tmp, 'session-wt')
        self._infra = os.path.join(self._tmp, 'infra')
        self._project = os.path.join(self._tmp, 'project')
        for d in (self._wt, self._infra, self._project):
            os.makedirs(d)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_plan(self, content: str) -> None:
        with open(os.path.join(self._wt, 'PLAN.md'), 'w') as f:
            f.write(content)

    def _call(self, *, active_skill, **overrides) -> bool:
        kwargs = dict(
            active_skill=active_skill,
            session_worktree=self._wt,
            infra_dir=self._infra,
            project_workdir=self._project,
            task='test task',
            session_id='sess-1',
        )
        kwargs.update(overrides)
        return archive_skill_correction(**kwargs)

    def test_no_active_skill_returns_false_immediately(self):
        """No active skill → nothing to archive.  Must not touch disk."""
        with patch(
            'teaparty.learning.procedural.learning.archive_skill_candidate',
        ) as mock_archive:
            self.assertFalse(self._call(active_skill=None))
            mock_archive.assert_not_called()

    def test_no_plan_md_returns_false(self):
        """Active skill but no PLAN.md → can't compare; no archive."""
        with patch(
            'teaparty.learning.procedural.learning.archive_skill_candidate',
        ) as mock_archive:
            result = self._call(active_skill={
                'name': 'foo', 'template': 'whatever',
            })
            self.assertFalse(result)
            mock_archive.assert_not_called()

    def test_plan_matches_template_returns_false_no_archive(self):
        """Plan unchanged from template → not a correction.  No archive."""
        template = '## Step 1\nDo a thing.\n'
        self._write_plan(template)
        with patch(
            'teaparty.learning.procedural.learning.archive_skill_candidate',
        ) as mock_archive:
            result = self._call(active_skill={
                'name': 'foo', 'template': template,
            })
            self.assertFalse(result)
            mock_archive.assert_not_called()

    def test_plan_matches_template_modulo_whitespace(self):
        """Trailing/leading whitespace mustn't trigger a false correction."""
        template = '## Step 1\nDo a thing.'
        self._write_plan(f'\n  {template}  \n\n')
        with patch(
            'teaparty.learning.procedural.learning.archive_skill_candidate',
        ) as mock_archive:
            self.assertFalse(self._call(active_skill={
                'name': 'foo', 'template': template,
            }))
            mock_archive.assert_not_called()

    def test_plan_diverged_archives_and_returns_true(self):
        """Plan differs from template → archive + signal "consumed"."""
        template = '## Step 1\nOriginal plan.\n'
        self._write_plan('## Step 1\nCorrected plan.\n## Step 2\nNew step.\n')

        with patch(
            'teaparty.learning.procedural.learning.archive_skill_candidate',
            return_value=True,
        ) as mock_archive:
            result = self._call(active_skill={
                'name': 'foo', 'template': template,
            })

        self.assertTrue(
            result,
            'Returning True signals the engine to clear active_skill — '
            'the skill has been consumed regardless of archive outcome.',
        )
        mock_archive.assert_called_once()
        kwargs = mock_archive.call_args.kwargs
        self.assertEqual(kwargs['corrects_skill'], 'foo')
        self.assertEqual(kwargs['session_id'], 'sess-1-correction')
        self.assertEqual(kwargs['project_dir'], self._project)

    def test_archive_failure_still_returns_true(self):
        """Even if archive_skill_candidate raises, the skill is consumed.

        The contract is: if the plan diverged from the template, the
        skill should not influence later phases.  Returning False on
        archive failure would leave a stale ``active_skill`` slot,
        which could mis-attribute work later.  Log + swallow + return
        True.
        """
        template = '## Step 1\nOriginal.\n'
        self._write_plan('## Different\n')

        with patch(
            'teaparty.learning.procedural.learning.archive_skill_candidate',
            side_effect=RuntimeError('boom'),
        ):
            result = self._call(active_skill={
                'name': 'foo', 'template': template,
            })
            self.assertTrue(result)

    def test_passes_skill_category_when_path_provided(self):
        """When ``path`` is set, frontmatter is parsed for category."""
        template = '## T\n'
        self._write_plan('## Different\n')

        skill_path = os.path.join(self._tmp, 'some-skill.md')
        with open(skill_path, 'w') as f:
            f.write('---\nname: foo\ncategory: planning\n---\n# body\n')

        with patch(
            'teaparty.learning.procedural.learning.archive_skill_candidate',
            return_value=True,
        ) as mock_archive:
            self._call(active_skill={
                'name': 'foo', 'template': template, 'path': skill_path,
            })

        kwargs = mock_archive.call_args.kwargs
        self.assertEqual(kwargs['category'], 'planning')

    def test_missing_skill_path_just_drops_category(self):
        """A non-existent skill path → empty category, no exception."""
        template = '## T\n'
        self._write_plan('## Different\n')

        with patch(
            'teaparty.learning.procedural.learning.archive_skill_candidate',
            return_value=True,
        ) as mock_archive:
            self._call(active_skill={
                'name': 'foo', 'template': template,
                'path': '/nonexistent/path.md',
            })

        kwargs = mock_archive.call_args.kwargs
        self.assertEqual(kwargs['category'], '')


# ── try_write_premortem ────────────────────────────────────────────────────

class TestTryWritePremortem(unittest.TestCase):
    """Behavior of the planning→execution premortem hook."""

    def test_calls_through_to_extract_write_premortem(self):
        with patch(
            'teaparty.learning.extract.write_premortem',
        ) as mock_write:
            try_write_premortem(infra_dir='/tmp/foo', task='build a thing')

        mock_write.assert_called_once_with(
            infra_dir='/tmp/foo', task='build a thing',
        )

    def test_swallows_all_exceptions(self):
        """A learning failure must not abort the session.

        Premortem generation can fail in plenty of ways — missing
        PLAN.md, network error talking to the LLM, write error.  The
        contract: try, log, swallow.  The engine does not get an
        exception.
        """
        with patch(
            'teaparty.learning.extract.write_premortem',
            side_effect=RuntimeError('LLM unreachable'),
        ):
            # Must not raise.
            try_write_premortem(infra_dir='/tmp/foo', task='whatever')

    def test_swallows_oserror_too(self):
        with patch(
            'teaparty.learning.extract.write_premortem',
            side_effect=OSError('disk full'),
        ):
            try_write_premortem(infra_dir='/tmp/foo', task='whatever')


if __name__ == '__main__':
    unittest.main()
