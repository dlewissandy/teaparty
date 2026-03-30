"""Tests for issue #327: Skills resolution — filesystem discovery, org registration, and precedence.

Acceptance criteria:
1. Global config Skill Catalog shows skills discovered from {teaparty_home}/.claude/skills/,
   not from the YAML skills: list alone.
2. Project config Skills card shows local skills from {project_dir}/.claude/skills/ plus
   registered org skills from project.yaml skills:, with local/shared source badges.
3. A local skill with the same name as an org skill displays as local; the org version is not shown.
4. A skill declared in project.yaml skills: that does not exist in the org catalog is flagged
   (source='missing'), not silently omitted.
5. Workgroup-level skills: (catalog) and agent-level skills: (allowlist) are unaffected.
6. discover_skills() returns [] when the directory does not exist (graceful fallback).
"""
import os
import tempfile
import unittest

from orchestrator.config_reader import discover_skills


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_skill(skills_dir: str, name: str) -> None:
    """Create a valid skill directory with SKILL.md under skills_dir."""
    skill_path = os.path.join(skills_dir, name)
    os.makedirs(skill_path, exist_ok=True)
    with open(os.path.join(skill_path, 'SKILL.md'), 'w') as f:
        f.write(f'# {name}\n')


def _make_dir_without_skill_md(skills_dir: str, name: str) -> None:
    """Create a directory under skills_dir that has no SKILL.md (not a valid skill)."""
    os.makedirs(os.path.join(skills_dir, name), exist_ok=True)


def _make_bridge(teaparty_home: str, static_dir: str):
    """Instantiate TeaPartyBridge with test paths, skipping the FileNotFoundError on static_dir."""
    from bridge.server import TeaPartyBridge
    os.makedirs(static_dir, exist_ok=True)
    return TeaPartyBridge(teaparty_home=teaparty_home, static_dir=static_dir)


# ── Criterion 1 & 6: discover_skills function ────────────────────────────────

class TestDiscoverSkillsReturnsNamesFromFilesystem(unittest.TestCase):
    """discover_skills() scans a .claude/skills/ directory and returns skill names."""

    def test_returns_names_of_subdirectories_containing_skill_md(self):
        """Skills with SKILL.md are discovered; their names are returned."""
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = os.path.join(tmp, '.claude', 'skills')
            os.makedirs(skills_dir)
            _make_skill(skills_dir, 'fix-issue')
            _make_skill(skills_dir, 'audit')
            result = discover_skills(skills_dir)
            self.assertIn('fix-issue', result)
            self.assertIn('audit', result)

    def test_excludes_subdirectories_without_skill_md(self):
        """A subdirectory without SKILL.md is not a skill and must not appear."""
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = os.path.join(tmp, '.claude', 'skills')
            os.makedirs(skills_dir)
            _make_skill(skills_dir, 'real-skill')
            _make_dir_without_skill_md(skills_dir, 'not-a-skill')
            result = discover_skills(skills_dir)
            self.assertIn('real-skill', result)
            self.assertNotIn('not-a-skill', result)

    def test_returns_empty_list_when_directory_does_not_exist(self):
        """discover_skills must return [] gracefully when the directory is absent."""
        result = discover_skills('/nonexistent/path/.claude/skills')
        self.assertEqual(result, [])

    def test_returns_empty_list_for_empty_directory(self):
        """discover_skills must return [] for an existing but empty directory."""
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = os.path.join(tmp, '.claude', 'skills')
            os.makedirs(skills_dir)
            result = discover_skills(skills_dir)
            self.assertEqual(result, [])

    def test_result_contains_only_strings(self):
        """Each element in the returned list must be a string (the skill name)."""
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = os.path.join(tmp, '.claude', 'skills')
            os.makedirs(skills_dir)
            _make_skill(skills_dir, 'research')
            result = discover_skills(skills_dir)
            for item in result:
                self.assertIsInstance(item, str,
                    f'discover_skills must return list[str], got {type(item).__name__}: {item!r}')


# ── Criterion 1: management team serializer uses discovered skills ────────────

class TestManagementTeamSerializerUsesDiscoveredSkills(unittest.TestCase):
    """_serialize_management_team must return discovered skills, not the raw YAML list."""

    def _make_management_team(self, yaml_skills):
        """Return a ManagementTeam stub with the given yaml-declared skills list."""
        from orchestrator.config_reader import ManagementTeam
        return ManagementTeam(name='Test', skills=yaml_skills)

    def test_returns_discovered_skills_when_provided(self):
        """When discovered_skills is passed, management team skills must match the discovered list."""
        with tempfile.TemporaryDirectory() as tmp:
            bridge = _make_bridge(tmp, os.path.join(tmp, 'static'))
        team = self._make_management_team(yaml_skills=['yaml-only-skill'])
        discovered = ['filesystem-skill-a', 'filesystem-skill-b']
        result = bridge._serialize_management_team(team, discovered_skills=discovered)
        result_names = [s['name'] if isinstance(s, dict) else s for s in result['skills']]
        self.assertEqual(
            result_names, discovered,
            'management team skills must be the filesystem-discovered list, not the YAML list',
        )

    def test_discovered_skills_are_not_filtered_by_yaml_list(self):
        """A skill installed on disk but not in YAML must appear in the catalog."""
        with tempfile.TemporaryDirectory() as tmp:
            bridge = _make_bridge(tmp, os.path.join(tmp, 'static'))
        team = self._make_management_team(yaml_skills=['registered-skill'])
        # installed-but-not-registered appears on disk but not in YAML
        discovered = ['registered-skill', 'installed-but-not-registered']
        result = bridge._serialize_management_team(team, discovered_skills=discovered)
        result_names = [s['name'] if isinstance(s, dict) else s for s in result['skills']]
        self.assertIn(
            'installed-but-not-registered', result_names,
            'Skills installed on disk but not in YAML must appear in the catalog',
        )


# ── Criterion 2: project config returns merged local + shared skills ──────────

class TestProjectTeamSerializerMergesLocalAndOrgSkills(unittest.TestCase):
    """_serialize_project_team must merge local-discovered and registered-org skills."""

    def _make_project_team(self, yaml_skills):
        """Return a ProjectTeam stub with the given yaml-declared skills list."""
        from orchestrator.config_reader import ProjectTeam
        return ProjectTeam(name='TestProject', skills=yaml_skills)

    def _make_bridge(self, tmp):
        return _make_bridge(tmp, os.path.join(tmp, 'static'))

    def test_local_skill_appears_with_local_source(self):
        """Skills discovered from the project's .claude/skills/ must have source='local'."""
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self._make_bridge(tmp)
        team = self._make_project_team(yaml_skills=[])
        result = bridge._serialize_project_team(
            team,
            local_skills=['my-local-skill'],
            registered_org_skills=[],
            org_catalog_skills=[],
        )
        skill_map = {s['name']: s['source'] for s in result['skills']}
        self.assertIn('my-local-skill', skill_map)
        self.assertEqual(skill_map['my-local-skill'], 'local',
            'Locally installed skill must have source="local"')

    def test_registered_org_skill_present_in_catalog_appears_with_shared_source(self):
        """An org skill registered in project.yaml and installed in org catalog
        must appear with source='shared'."""
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self._make_bridge(tmp)
        team = self._make_project_team(yaml_skills=['fix-issue'])
        result = bridge._serialize_project_team(
            team,
            local_skills=[],
            registered_org_skills=['fix-issue'],
            org_catalog_skills=['fix-issue', 'audit'],
        )
        skill_map = {s['name']: s['source'] for s in result['skills']}
        self.assertIn('fix-issue', skill_map)
        self.assertEqual(skill_map['fix-issue'], 'shared',
            'Org skill registered in project.yaml and installed in org catalog must be source="shared"')


# ── Criterion 3: local skill takes precedence over org skill on collision ─────

class TestLocalSkillOverridesOrgSkillOnNameCollision(unittest.TestCase):
    """When a local skill and a registered org skill share the same name,
    only the local version appears (source='local')."""

    def _make_bridge(self, tmp):
        return _make_bridge(tmp, os.path.join(tmp, 'static'))

    def _make_project_team(self, yaml_skills):
        from orchestrator.config_reader import ProjectTeam
        return ProjectTeam(name='TestProject', skills=yaml_skills)

    def test_local_skill_wins_on_name_collision(self):
        """When local and org both have 'fix-issue', only the local entry appears."""
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self._make_bridge(tmp)
        team = self._make_project_team(yaml_skills=['fix-issue'])
        result = bridge._serialize_project_team(
            team,
            local_skills=['fix-issue'],
            registered_org_skills=['fix-issue'],
            org_catalog_skills=['fix-issue'],
        )
        entries = [s for s in result['skills'] if s['name'] == 'fix-issue']
        self.assertEqual(len(entries), 1,
            'Only one entry for fix-issue must appear when both local and org have it')
        self.assertEqual(entries[0]['source'], 'local',
            'The single entry must be source="local" when local overrides org')

    def test_colliding_skill_does_not_appear_as_shared(self):
        """The org version of a colliding skill must not appear as shared."""
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self._make_bridge(tmp)
        team = self._make_project_team(yaml_skills=['fix-issue'])
        result = bridge._serialize_project_team(
            team,
            local_skills=['fix-issue'],
            registered_org_skills=['fix-issue'],
            org_catalog_skills=['fix-issue'],
        )
        shared_entries = [s for s in result['skills']
                         if s['name'] == 'fix-issue' and s.get('source') == 'shared']
        self.assertEqual(len(shared_entries), 0,
            'The org version must not appear as shared when local takes precedence')


# ── Criterion 4: missing org skill is flagged, not silently omitted ───────────

class TestMissingOrgSkillIsFlagged(unittest.TestCase):
    """A skill declared in project.yaml skills: that does not exist in the org catalog
    must appear with source='missing', not be silently dropped."""

    def _make_bridge(self, tmp):
        return _make_bridge(tmp, os.path.join(tmp, 'static'))

    def _make_project_team(self, yaml_skills):
        from orchestrator.config_reader import ProjectTeam
        return ProjectTeam(name='TestProject', skills=yaml_skills)

    def test_registered_but_uninstalled_org_skill_gets_missing_source(self):
        """A skill in project.yaml skills: absent from org catalog must have source='missing'."""
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self._make_bridge(tmp)
        team = self._make_project_team(yaml_skills=['ghost-skill'])
        result = bridge._serialize_project_team(
            team,
            local_skills=[],
            registered_org_skills=['ghost-skill'],
            org_catalog_skills=[],  # ghost-skill not installed in org
        )
        skill_map = {s['name']: s['source'] for s in result['skills']}
        self.assertIn('ghost-skill', skill_map,
            'Unresolvable org skill must appear in the result (not silently omitted)')
        self.assertEqual(skill_map['ghost-skill'], 'missing',
            'Unresolvable org skill must have source="missing" to flag the broken reference')

    def test_missing_skill_is_not_silently_dropped(self):
        """The skills list must contain the flagged entry, not drop it."""
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self._make_bridge(tmp)
        team = self._make_project_team(yaml_skills=['ghost-skill'])
        result = bridge._serialize_project_team(
            team,
            local_skills=[],
            registered_org_skills=['ghost-skill'],
            org_catalog_skills=[],
        )
        names = [s['name'] for s in result['skills']]
        self.assertIn('ghost-skill', names,
            'Missing skill must not be silently dropped — it must appear with source="missing"')


# ── Criterion 5: workgroup-level skills unaffected ────────────────────────────

class TestWorkgroupLevelSkillsUnaffected(unittest.TestCase):
    """Workgroup-level skills: (catalog declaration) must continue to load from YAML unchanged."""

    def test_workgroup_skills_load_from_yaml_unchanged(self):
        """load_workgroup() must still return the skills: list from YAML as-is."""
        with tempfile.TemporaryDirectory() as tmp:
            wg_yaml = os.path.join(tmp, 'coding.yaml')
            import yaml
            with open(wg_yaml, 'w') as f:
                yaml.dump({
                    'name': 'Coding',
                    'description': 'test workgroup',
                    'skills': ['fix-issue', 'code-cleanup'],
                }, f)
            from orchestrator.config_reader import load_workgroup
            wg = load_workgroup(wg_yaml)
            self.assertEqual(wg.skills, ['fix-issue', 'code-cleanup'],
                'Workgroup skills must be loaded from YAML unchanged — '
                'the discovery model must not touch workgroup-level skills')


# ── Criterion 1 (integration): discover_skills wired into management team path ─

class TestDiscoverSkillsIntegrationWithOrgPath(unittest.TestCase):
    """discover_skills must scan {teaparty_home}/.claude/skills/ correctly."""

    def test_skills_discovered_from_teaparty_home_dot_claude_skills(self):
        """Skill directories with SKILL.md under {teaparty_home}/.claude/skills/ are discovered."""
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = os.path.join(tmp, '.claude', 'skills')
            os.makedirs(skills_dir)
            _make_skill(skills_dir, 'sprint-plan')
            _make_skill(skills_dir, 'audit')
            result = discover_skills(skills_dir)
            self.assertIn('sprint-plan', result)
            self.assertIn('audit', result)
            self.assertEqual(len(result), 2)

    def test_files_at_skills_dir_root_are_not_returned_as_skill_names(self):
        """Regular files (not directories) at the skills_dir root must not be returned."""
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = os.path.join(tmp, '.claude', 'skills')
            os.makedirs(skills_dir)
            _make_skill(skills_dir, 'real-skill')
            # A file (not a directory) at root level
            with open(os.path.join(skills_dir, 'README.md'), 'w') as f:
                f.write('# Skills\n')
            result = discover_skills(skills_dir)
            self.assertNotIn('README.md', result)
            self.assertIn('real-skill', result)


if __name__ == '__main__':
    unittest.main()
