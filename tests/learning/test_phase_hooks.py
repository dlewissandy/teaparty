"""Tests for ``teaparty.learning.phase_hooks``.

Currently one hook lives there: ``try_write_premortem`` runs at the
planning → execution boundary so the post-session prospective-extraction
pipeline has input.  Skill-correction archival used to live here but
moved into the planning skill itself (it owns SELECT/APPLY/RECONCILE).
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from teaparty.learning.phase_hooks import try_write_premortem


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
