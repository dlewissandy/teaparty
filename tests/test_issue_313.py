"""Tests for issue #313: write_intervention_chunk raises FileNotFoundError when session directory does not exist.

Verifies:
1. write_intervention_chunk creates infra_dir if it does not exist
2. write_intervention_outcome creates infra_dir if it does not exist
"""
import os
import tempfile
import unittest


class TestWriteInterventionChunkCreatesDir(unittest.TestCase):
    """write_intervention_chunk must create infra_dir if it does not exist."""

    def test_creates_missing_infra_dir(self):
        """write_intervention_chunk must not raise when infra_dir does not exist."""
        from orchestrator.learnings import write_intervention_chunk

        with tempfile.TemporaryDirectory() as tmp:
            nonexistent = os.path.join(tmp, 'session', 'infra')
            # Directory does not exist yet
            self.assertFalse(os.path.isdir(nonexistent))

            # Must not raise FileNotFoundError
            write_intervention_chunk(
                infra_dir=nonexistent,
                content='redirect',
                senders=['human'],
                cfa_state='TASK_IN_PROGRESS',
                phase='execution',
            )

            self.assertTrue(
                os.path.isfile(os.path.join(nonexistent, '.interventions.jsonl')),
                '.interventions.jsonl must be created even when infra_dir was missing',
            )


class TestWriteInterventionOutcomeCreatesDir(unittest.TestCase):
    """write_intervention_outcome must create infra_dir if it does not exist."""

    def test_creates_missing_infra_dir(self):
        """write_intervention_outcome must not raise when infra_dir does not exist."""
        from orchestrator.learnings import write_intervention_outcome

        with tempfile.TemporaryDirectory() as tmp:
            nonexistent = os.path.join(tmp, 'session', 'infra')
            self.assertFalse(os.path.isdir(nonexistent))

            write_intervention_outcome(
                infra_dir=nonexistent,
                outcome='continue',
            )

            self.assertTrue(
                os.path.isfile(os.path.join(nonexistent, '.interventions.jsonl')),
                '.interventions.jsonl must be created even when infra_dir was missing',
            )


if __name__ == '__main__':
    unittest.main()
