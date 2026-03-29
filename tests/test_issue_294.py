"""Tests for issue #294: stats page skill path correction.

The bridge was reading from `.claude/skills/` (non-existent) instead of
`{project_dir}/skills/` and `{project_dir}/teams/{team_name}/skills/`.

Acceptance criteria:
1. stats.md Data Sources table references {project_dir}/skills/ and
   {project_dir}/teams/{name}/skills/ — not .claude/skills/
2. _count_skills() globs {project_dir}/skills/*.md and
   {project_dir}/teams/{team_name}/skills/*.md — reads zero from .claude/skills/
"""
import os
import shutil
import tempfile
import unittest


def _make_tmpdir():
    return tempfile.mkdtemp()


class TestStatsDocPaths(unittest.TestCase):
    """Stats spec must reference the real skill file paths."""

    _STATS_MD = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'docs', 'proposals', 'ui-redesign', 'references', 'stats.md',
    )

    def _read_stats_md(self):
        with open(self._STATS_MD) as f:
            return f.read()

    def test_stats_md_references_project_skills_dir(self):
        content = self._read_stats_md()
        self.assertIn('{project_dir}/skills/', content,
                      'stats.md must reference {project_dir}/skills/ in Data Sources table')

    def test_stats_md_references_team_skills_dir(self):
        content = self._read_stats_md()
        self.assertIn('{project_dir}/teams/', content,
                      'stats.md must reference team-scoped skill directories')

    def test_stats_md_does_not_reference_claude_skills(self):
        content = self._read_stats_md()
        self.assertNotIn('.claude/skills/', content,
                         'stats.md must not reference .claude/skills/ — that path does not exist')


class TestCountSkillsCorrectPaths(unittest.TestCase):
    """_count_skills must read from per-project skill directories."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _count(self):
        from projects.POC.bridge.stats import _count_skills
        return _count_skills(self.tmpdir)

    def test_dot_claude_skills_not_counted(self):
        # Place files in .claude/skills/ (the old wrong path) — should not be counted
        wrong_dir = os.path.join(self.tmpdir, '.claude', 'skills')
        os.makedirs(wrong_dir, exist_ok=True)
        open(os.path.join(wrong_dir, 'skill.md'), 'w').close()
        self.assertEqual(self._count(), 0,
                         '.claude/skills/ must not be counted — that path is not written by the orchestrator')

    def test_project_skills_dir_counted(self):
        skills_dir = os.path.join(self.tmpdir, 'POC', 'skills')
        os.makedirs(skills_dir, exist_ok=True)
        open(os.path.join(skills_dir, 'fix-bug.md'), 'w').close()
        open(os.path.join(skills_dir, 'refactor.md'), 'w').close()
        self.assertEqual(self._count(), 2)

    def test_team_scoped_skills_counted(self):
        team_dir = os.path.join(self.tmpdir, 'POC', 'teams', 'coding', 'skills')
        os.makedirs(team_dir, exist_ok=True)
        open(os.path.join(team_dir, 'optimize.md'), 'w').close()
        self.assertEqual(self._count(), 1)

    def test_project_and_team_skills_counted_together(self):
        skills_dir = os.path.join(self.tmpdir, 'POC', 'skills')
        os.makedirs(skills_dir, exist_ok=True)
        open(os.path.join(skills_dir, 'fix-bug.md'), 'w').close()

        team1 = os.path.join(self.tmpdir, 'POC', 'teams', 'coding', 'skills')
        os.makedirs(team1, exist_ok=True)
        open(os.path.join(team1, 'optimize.md'), 'w').close()

        team2 = os.path.join(self.tmpdir, 'POC', 'teams', 'writing', 'skills')
        os.makedirs(team2, exist_ok=True)
        open(os.path.join(team2, 'summarize.md'), 'w').close()

        self.assertEqual(self._count(), 3)

    def test_non_md_files_not_counted(self):
        skills_dir = os.path.join(self.tmpdir, 'POC', 'skills')
        os.makedirs(skills_dir, exist_ok=True)
        open(os.path.join(skills_dir, 'fix-bug.md'), 'w').close()
        open(os.path.join(skills_dir, 'notes.txt'), 'w').close()
        self.assertEqual(self._count(), 1)

    def test_zero_when_no_skills_dirs_exist(self):
        os.makedirs(os.path.join(self.tmpdir, 'POC', '.sessions'), exist_ok=True)
        self.assertEqual(self._count(), 0)


if __name__ == '__main__':
    unittest.main()
