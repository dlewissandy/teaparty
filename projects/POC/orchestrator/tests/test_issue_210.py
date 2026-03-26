#!/usr/bin/env python3
"""Tests for issue #210: CfA state file write must be atomic.

Covers:
 1. save_state uses atomic write (tmpfile + os.replace), not direct json.dump.
 2. A crash (simulated IOError) mid-write does not corrupt the existing state file.
 3. load_state still reads the file correctly after an atomic save.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.scripts.cfa_state import (
    CfaState,
    load_state,
    save_state,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_cfa(**overrides) -> CfaState:
    """Create a CfaState for testing (no transition needed)."""
    defaults = dict(
        phase='intent', state='PROPOSAL', actor='agent',
        history=[], backtrack_count=0, task_id='test-210',
        parent_id='', team_id='', depth=0,
    )
    defaults.update(overrides)
    return CfaState(**defaults)


class TestSaveStateAtomic(unittest.TestCase):
    """save_state must use atomic tmpfile + os.replace pattern."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = os.path.join(self.tmpdir, '.cfa-state.json')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_state_uses_os_replace(self):
        """save_state must call os.replace to atomically swap the file."""
        cfa = _make_cfa()
        with patch('projects.POC.scripts.cfa_state.os.replace', wraps=os.replace) as mock_replace:
            save_state(cfa, self.state_path)
            mock_replace.assert_called_once()
            # The target of os.replace must be the state path
            args = mock_replace.call_args
            self.assertEqual(args[0][1], self.state_path)

    def test_crash_mid_write_preserves_existing_state(self):
        """If writing fails mid-stream, the previous state file must survive intact."""
        # Write initial good state
        cfa_v1 = _make_cfa(team_id='v1')
        save_state(cfa_v1, self.state_path)

        # Verify v1 is on disk
        loaded_v1 = load_state(self.state_path)
        self.assertEqual(loaded_v1.team_id, 'v1')

        # Simulate a crash during the write of v2 by making json.dump raise
        cfa_v2 = _make_cfa(team_id='v2')
        with patch('projects.POC.scripts.cfa_state.json.dump', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                save_state(cfa_v2, self.state_path)

        # The original v1 state must still be intact
        loaded_after_crash = load_state(self.state_path)
        self.assertEqual(loaded_after_crash.team_id, 'v1')

    def test_no_tmp_file_left_after_successful_write(self):
        """After a successful save, no .tmp file should remain."""
        cfa = _make_cfa()
        save_state(cfa, self.state_path)

        tmp_path = self.state_path + '.tmp'
        self.assertFalse(os.path.exists(tmp_path),
                         f"Temp file {tmp_path} should not exist after successful write")

    def test_no_tmp_file_left_after_failed_write(self):
        """After a failed save, no .tmp file should remain."""
        cfa = _make_cfa()
        with patch('projects.POC.scripts.cfa_state.json.dump', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                save_state(cfa, self.state_path)

        tmp_path = self.state_path + '.tmp'
        self.assertFalse(os.path.exists(tmp_path),
                         f"Temp file {tmp_path} should not exist after failed write")

    def test_roundtrip_after_atomic_save(self):
        """load_state must correctly read what save_state wrote."""
        cfa = _make_cfa(team_id='roundtrip-test', depth=3)
        save_state(cfa, self.state_path)
        loaded = load_state(self.state_path)
        self.assertEqual(loaded.state, cfa.state)
        self.assertEqual(loaded.phase, cfa.phase)
        self.assertEqual(loaded.team_id, 'roundtrip-test')
        self.assertEqual(loaded.depth, 3)


if __name__ == '__main__':
    unittest.main()
