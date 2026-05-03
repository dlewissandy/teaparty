"""Regression: a worker that stalls on permission is not accepted as done.

When an agent's claude exits cleanly but its final reply text
indicates it gave up on a permission prompt — *"I'm blocked on
permission for X"*, *"haven't granted it yet"*, etc. — the dispatch
should not treat that string as the deliverable.  Without this
detection the parent's ``asyncio.gather`` collects the error string
as the worker's reply and propagates it upward as if it were work.
The dispatch tree appears to make progress but is actually delivering
diagnostics, and the operator never finds out the worker was stuck.

The detector is a small regex pass over the agent's final result
text.  Matching strings route through ``on_failure``, the same path
that handles subprocess crashes — tier-specific code can decide to
retry (in case the operator just granted permission), abort, or
substitute a clearer message.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.messaging.child_dispatch import _looks_like_permission_stall


class PermissionStallDetectorTest(unittest.TestCase):
    """The detector matches the failure modes seen in live jobs."""

    def test_blocked_on_permission_phrase(self) -> None:
        """The exact phrasing observed in joke-book's stalled writing-leads."""
        text = (
            "I'm blocked on write permission for `VOICE-SWATCH.md`. Please "
            "grant the write permission and I'll write the file."
        )
        self.assertTrue(_looks_like_permission_stall(text))

    def test_havent_granted_phrase(self) -> None:
        """The phrasing Claude Code uses when surfacing a permission prompt."""
        text = (
            "Claude requested permissions to write to /path/to/file, but "
            "you haven't granted it yet."
        )
        self.assertTrue(_looks_like_permission_stall(text))

    def test_curly_apostrophe_havent(self) -> None:
        """Some renderings use a curly apostrophe."""
        text = "I haven’t granted that yet"
        self.assertTrue(_looks_like_permission_stall(text))

    def test_please_grant_permission(self) -> None:
        text = "Please grant the write permission and I'll proceed."
        self.assertTrue(_looks_like_permission_stall(text))

    def test_normal_reply_is_not_a_stall(self) -> None:
        """Healthy replies must not be flagged as stalls."""
        normal_replies = (
            'Done. Wrote SOURCES.md with 87 entries across 5 eras.',
            'I finished the outline. The file is at BOOK-MAP.md.',
            "I've completed the work and committed the result.",
            'The voice swatch is ready for review.',
        )
        for text in normal_replies:
            self.assertFalse(
                _looks_like_permission_stall(text),
                f'False positive: {text!r} should not be a stall',
            )

    def test_empty_text_is_not_a_stall(self) -> None:
        self.assertFalse(_looks_like_permission_stall(''))
        self.assertFalse(_looks_like_permission_stall(None))  # type: ignore

    def test_partial_match_anywhere_in_text(self) -> None:
        """A long reply with the stall pattern buried inside still trips."""
        text = (
            "I got most of the way through. Here's a summary of progress. "
            "I read INTENT.md and PLAN.md, drafted three voice specimens, "
            "and tried to save them. The Write tool needs explicit "
            "permission to create VOICE-SWATCH.md — I'm blocked on permission. "
            "Once granted I can land the file in seconds."
        )
        self.assertTrue(_looks_like_permission_stall(text))


if __name__ == '__main__':
    unittest.main()
