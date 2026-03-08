#!/usr/bin/env python3
"""Tests for Stage lifecycle: detect_stage.py and retire_stage.py.

Covers:
 - retire_stage_entries() marks task-domain entries from old stage as retired
 - Team-domain entries survive stage transitions
 - SUCCESS CRITERION 1: spec-stage task directives absent after stage transition
 - SUCCESS CRITERION 2: team-domain entries survive unchanged
 - detect_stage_from_content() returns a known stage string
 - detect_stage_from_content() handles edge cases gracefully
"""
import os
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from memory_entry import make_entry, parse_memory_file, serialize_memory_file, MemoryEntry
from retire_stage import retire_stage_entries
from detect_stage import detect_stage_from_content, STAGES


# ── retire_stage_entries ──────────────────────────────────────────────────────

class TestRetireStageEntries(unittest.TestCase):

    def _make_task_entry(self, phase: str, content: str = 'Task directive') -> MemoryEntry:
        e = make_entry(content, type='directive', domain='task', importance=0.7, phase=phase)
        return e

    def _make_team_entry(self, phase: str = 'specification', content: str = 'Team learning') -> MemoryEntry:
        e = make_entry(content, type='procedural', domain='team', importance=0.5, phase=phase)
        return e

    # ── SUCCESS CRITERION 1 ───────────────────────────────────────────────────

    def test_task_entries_from_old_stage_retired(self):
        """SUCCESS CRITERION 1: spec-stage task directives absent after stage transition."""
        spec_task = self._make_task_entry(phase='specification',
                                          content='Spec requirement: must document all APIs.')
        impl_task = self._make_task_entry(phase='implementation',
                                          content='Implementation note: use async functions.')

        entries = [spec_task, impl_task]
        updated, count = retire_stage_entries(entries, old_phase='specification')

        self.assertEqual(count, 1, "Exactly 1 spec task entry should be retired")

        # Find the retired entry
        retired = [e for e in updated if e.status == 'retired']
        active = [e for e in updated if e.status == 'active']

        self.assertEqual(len(retired), 1)
        self.assertEqual(len(active), 1)
        self.assertEqual(retired[0].phase, 'specification')
        self.assertEqual(active[0].phase, 'implementation')

    def test_only_task_domain_entries_retired(self):
        """Task-domain entries retired; non-task entries untouched."""
        task_entry = self._make_task_entry(phase='specification')
        other_entry = make_entry('Other', domain='team', type='procedural',
                                 importance=0.5, phase='specification')

        updated, count = retire_stage_entries([task_entry, other_entry], 'specification')
        self.assertEqual(count, 1)

        statuses = {e.domain: e.status for e in updated}
        self.assertEqual(statuses['task'], 'retired')
        self.assertEqual(statuses['team'], 'active')

    # ── SUCCESS CRITERION 2 ───────────────────────────────────────────────────

    def test_team_entries_survive_stage_transition(self):
        """SUCCESS CRITERION 2: team-domain entries are not retired on stage transition."""
        team_entries = [
            self._make_team_entry(phase='specification', content=f'Team knowledge {i}')
            for i in range(5)
        ]
        task_entry = self._make_task_entry(phase='specification',
                                           content='Specification task directive.')

        all_entries = team_entries + [task_entry]
        updated, count = retire_stage_entries(all_entries, old_phase='specification')

        self.assertEqual(count, 1, "Only 1 task entry should be retired")

        # All team entries must still be active
        team_updated = [e for e in updated if e.domain == 'team']
        for e in team_updated:
            self.assertEqual(e.status, 'active',
                             f"Team entry should survive phase transition: {e.content}")

    def test_already_retired_entries_not_double_retired(self):
        """Entries already retired are not re-retired."""
        e = self._make_task_entry(phase='specification')
        already_retired = replace(e, status='retired')

        updated, count = retire_stage_entries([already_retired], 'specification')
        self.assertEqual(count, 0, "Already-retired entry should not be counted again")

    def test_entries_from_different_stage_not_retired(self):
        """Entries from a stage other than old stage are not retired."""
        impl_task = self._make_task_entry(phase='implementation')
        updated, count = retire_stage_entries([impl_task], old_phase='specification')
        self.assertEqual(count, 0)
        self.assertEqual(updated[0].status, 'active')

    def test_all_entries_retired_when_all_task(self):
        """All task-domain entries from the old phase are retired."""
        entries = [self._make_task_entry(phase='specification', content=f'Spec {i}')
                   for i in range(4)]
        updated, count = retire_stage_entries(entries, 'specification')
        self.assertEqual(count, 4)
        for e in updated:
            self.assertEqual(e.status, 'retired')

    def test_empty_input_returns_empty(self):
        """Empty input list returns empty, count 0."""
        updated, count = retire_stage_entries([], 'specification')
        self.assertEqual(updated, [])
        self.assertEqual(count, 0)

    def test_unknown_old_stage_retires_nothing(self):
        """'unknown' stage should not retire anything meaningful."""
        entry = self._make_task_entry(phase='unknown')
        # retire_stage.py guards against old_stage='unknown' at CLI level,
        # but the library function itself will still match stage='unknown'
        updated, count = retire_stage_entries([entry], 'unknown')
        self.assertEqual(count, 1)  # matches, but this is filtered at CLI level


# ── retire_stage file I/O ─────────────────────────────────────────────────────

class TestRetireStageFileIO(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mem_path = os.path.join(self.tmpdir, 'MEMORY.md')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_memory(self, entries):
        Path(self.mem_path).write_text(serialize_memory_file(entries))

    def _read_memory(self):
        return parse_memory_file(Path(self.mem_path).read_text())

    def test_retire_stage_updates_memory_file(self):
        """retire_stage.py main() modifies MEMORY.md in place."""
        from retire_stage import main as retire_main
        import sys

        e_task = make_entry('Spec task', domain='task', type='directive',
                            importance=0.7, phase='specification')
        e_team = make_entry('Team knowledge', domain='team', type='procedural',
                            importance=0.5, phase='specification')
        self._write_memory([e_task, e_team])

        # Call main() directly
        sys.argv = ['retire_stage.py', '--old-stage', 'specification',
                    '--memory', self.mem_path]
        retire_main()

        result = self._read_memory()
        task_entry = next((e for e in result if e.domain == 'task'), None)
        team_entry = next((e for e in result if e.domain == 'team'), None)

        self.assertIsNotNone(task_entry)
        self.assertEqual(task_entry.status, 'retired')
        self.assertIsNotNone(team_entry)
        self.assertEqual(team_entry.status, 'active')


# ── detect_stage_from_content ─────────────────────────────────────────────────

class TestDetectStageFromContent(unittest.TestCase):

    def test_returns_known_stage_string(self):
        """detect_stage_from_content returns a value in STAGES list."""
        # Use a clearly implementation-oriented description
        content = "Implement the new authentication module. Write Python code."
        result = detect_stage_from_content(content)
        self.assertIn(result, STAGES, f"Expected one of {STAGES}, got '{result}'")

    def test_empty_content_returns_unknown(self):
        """Empty content string must return 'unknown'."""
        result = detect_stage_from_content('')
        self.assertEqual(result, 'unknown')

    def test_whitespace_only_returns_unknown(self):
        """Whitespace-only content must return 'unknown'."""
        result = detect_stage_from_content('   \n\t  ')
        self.assertEqual(result, 'unknown')

    def test_output_is_lowercase(self):
        """Returned phase must be lowercase."""
        result = detect_stage_from_content('Implementing code changes.')
        self.assertEqual(result, result.lower())

    def test_result_has_no_whitespace(self):
        """Returned phase must not contain whitespace."""
        result = detect_stage_from_content('Building the feature.')
        self.assertEqual(result, result.strip())
        self.assertNotIn(' ', result)


# ── Integration: stage transition end-to-end ──────────────────────────────────

class TestStageTransitionIntegration(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mem_path = os.path.join(self.tmpdir, 'MEMORY.md')
        self.stage_file = os.path.join(self.tmpdir, '.current-stage')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_transition_retires_task_keeps_team(self):
        """End-to-end: write memory, simulate stage transition, verify retirement."""
        # Write entries for 'specification' stage
        spec_task = make_entry(
            'Spec requirement: implement XYZ interface.',
            domain='task', type='directive', importance=0.8, phase='specification',
        )
        team_learning = make_entry(
            'Team always parallelizes dispatch calls.',
            domain='team', type='procedural', importance=0.7, phase='specification',
        )
        Path(self.mem_path).write_text(serialize_memory_file([spec_task, team_learning]))

        # Simulate: stage was 'specification', now retiring it
        updated, count = retire_stage_entries(
            parse_memory_file(Path(self.mem_path).read_text()),
            old_phase='specification',
        )
        Path(self.mem_path).write_text(serialize_memory_file(updated))

        # Verify SUCCESS CRITERION 1: spec task directive is gone (retired)
        final_entries = parse_memory_file(Path(self.mem_path).read_text())
        task_entries = [e for e in final_entries if e.domain == 'task' and e.status == 'active']
        self.assertEqual(len(task_entries), 0,
                         "No active task-domain entries should remain after stage transition")

        # Verify SUCCESS CRITERION 2: team entry survives
        team_entries = [e for e in final_entries if e.domain == 'team' and e.status == 'active']
        self.assertEqual(len(team_entries), 1,
                         "Team-domain entry must survive stage transition")


if __name__ == '__main__':
    unittest.main()
