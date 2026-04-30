"""Issue #425: escalation skill bodies require a diligence rail.

Each of `collaborate.md`, `escalate.md`, `delegate.md` must mandate that the
proxy walk the worktree and read the relevant artifacts before forming its
reply.  Without this, the proxy paraphrases the question prose and approves
blind — the joke-book failure documented on the issue.

Each test pins one slice of the rail per skill so a regression names the
specific skill and the specific step that drifted.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


_SKILL_DIR = (
    Path(__file__).resolve().parents[2]
    / '.teaparty' / 'management' / 'skills' / 'escalation'
)
_SKILLS = ('collaborate.md', 'escalate.md', 'delegate.md')


def _load(skill: str) -> str:
    path = _SKILL_DIR / skill
    if not path.exists():
        raise AssertionError(f'skill {skill} missing at {path}')
    return path.read_text()


# Keywords identifying each diligence step.  The skill body may use synonyms,
# but the step must be present and identifiable.
_WALK_PATTERNS = (
    r'walk\s+the\s+worktree',
    r'walk\s+the\s+(caller|cwd)',
    r'list\s+(directories|the\s+worktree)',
)
_READ_ARTIFACTS_PATTERNS = (
    r'read\s+the\s+(relevant\s+)?(artifacts?|deliverable)',
    r'read\s+the\s+actual\s+(work|deliverable)',
)
_VERIFY_PATTERNS = (
    r'verify\s+(the\s+)?(question|claims?)',
    r'check.*against\s+the\s+artifacts',
    r'trust.{0,4}but.{0,4}verify',
)


def _matches_any(body: str, patterns: tuple[str, ...]) -> bool:
    for pat in patterns:
        if re.search(pat, body, re.IGNORECASE):
            return True
    return False


class DiligenceRailWalkStepTest(unittest.TestCase):
    """Each skill names a 'walk the worktree' step."""

    def test_collaborate_has_walk_step(self) -> None:
        body = _load('collaborate.md')
        self.assertTrue(
            _matches_any(body, _WALK_PATTERNS),
            'collaborate.md must instruct the proxy to walk the worktree '
            'before replying (#425 diligence rail step 2)',
        )

    def test_escalate_has_walk_step(self) -> None:
        body = _load('escalate.md')
        self.assertTrue(
            _matches_any(body, _WALK_PATTERNS),
            'escalate.md must instruct the proxy to walk the worktree '
            'before replying (#425 diligence rail step 2)',
        )

    def test_delegate_has_walk_step(self) -> None:
        body = _load('delegate.md')
        self.assertTrue(
            _matches_any(body, _WALK_PATTERNS),
            'delegate.md must instruct the proxy to walk the worktree '
            'before replying (#425 diligence rail step 2)',
        )


class DiligenceRailReadArtifactsTest(unittest.TestCase):
    """Each skill names a 'read the artifacts' step."""

    def test_collaborate_has_read_artifacts_step(self) -> None:
        body = _load('collaborate.md')
        self.assertTrue(
            _matches_any(body, _READ_ARTIFACTS_PATTERNS),
            'collaborate.md must instruct the proxy to read the relevant '
            'artifacts directly (#425 diligence rail step 3)',
        )

    def test_escalate_has_read_artifacts_step(self) -> None:
        body = _load('escalate.md')
        self.assertTrue(
            _matches_any(body, _READ_ARTIFACTS_PATTERNS),
            'escalate.md must instruct the proxy to read the relevant '
            'artifacts directly (#425 diligence rail step 3)',
        )

    def test_delegate_has_read_artifacts_step(self) -> None:
        body = _load('delegate.md')
        self.assertTrue(
            _matches_any(body, _READ_ARTIFACTS_PATTERNS),
            'delegate.md must instruct the proxy to read the relevant '
            'artifacts directly (#425 diligence rail step 3)',
        )


class DiligenceRailVerifyClaimsTest(unittest.TestCase):
    """Each skill names a 'verify claims against artifacts' step."""

    def test_collaborate_has_verify_step(self) -> None:
        body = _load('collaborate.md')
        self.assertTrue(
            _matches_any(body, _VERIFY_PATTERNS),
            "collaborate.md must instruct the proxy to verify the "
            "question's claims against the artifacts (#425 step 4)",
        )

    def test_escalate_has_verify_step(self) -> None:
        body = _load('escalate.md')
        self.assertTrue(
            _matches_any(body, _VERIFY_PATTERNS),
            "escalate.md must instruct the proxy to verify the "
            "question's claims against the artifacts (#425 step 4)",
        )

    def test_delegate_has_verify_step(self) -> None:
        body = _load('delegate.md')
        self.assertTrue(
            _matches_any(body, _VERIFY_PATTERNS),
            "delegate.md must instruct the proxy to verify the "
            "question's claims against the artifacts (#425 step 4)",
        )


class DiligenceRailOrderingTest(unittest.TestCase):
    """The walk/read step must precede the reply step in the skill body."""

    @staticmethod
    def _first_match_position(body: str, patterns: tuple[str, ...]) -> int:
        positions = []
        for pat in patterns:
            m = re.search(pat, body, re.IGNORECASE)
            if m:
                positions.append(m.start())
        return min(positions) if positions else -1

    @staticmethod
    def _reply_position(body: str) -> int:
        # The reply step is named via execution of `respond.md`.  In every
        # current skill body, that is the terminal action.
        m = re.search(r'execute\s+(respond|it)|read\s+`respond\.md`', body, re.IGNORECASE)
        return m.start() if m else -1

    def _check(self, skill: str) -> None:
        body = _load(skill)
        walk = self._first_match_position(body, _WALK_PATTERNS)
        reply = self._reply_position(body)
        self.assertGreaterEqual(
            walk, 0,
            f'{skill}: walk step missing (cannot check ordering)',
        )
        self.assertGreaterEqual(
            reply, 0,
            f'{skill}: reply/respond step missing (cannot check ordering)',
        )
        self.assertLess(
            walk, reply,
            f'{skill}: walk-the-worktree step (pos {walk}) must precede '
            f'the respond step (pos {reply}) — diligence rail mandates '
            f'reading before replying (#425)',
        )

    def test_collaborate_walks_before_replying(self) -> None:
        self._check('collaborate.md')

    def test_escalate_walks_before_replying(self) -> None:
        self._check('escalate.md')

    def test_delegate_walks_before_replying(self) -> None:
        self._check('delegate.md')


class DiligenceRailMandatoryLanguageTest(unittest.TestCase):
    """The rail must be required, not advisory.

    Words like 'optionally', 'if helpful', 'review if useful' undermine the
    rail.  The issue says: 'The skill body names these steps as required,
    not advisory.'
    """

    _ADVISORY_HINTS = (
        r'\bif\s+helpful\b',
        r'\bif\s+useful\b',
        r'\boptionally\b',
        r'\bmay\s+also\b',
        r'\breview\s+if\b',
    )

    def _check(self, skill: str) -> None:
        body = _load(skill)
        for pat in self._ADVISORY_HINTS:
            self.assertIsNone(
                re.search(pat, body, re.IGNORECASE),
                f'{skill}: contains advisory phrasing matching /{pat}/; '
                f'#425 diligence rail must be required, not optional',
            )

    def test_collaborate_no_advisory_phrasing(self) -> None:
        self._check('collaborate.md')

    def test_escalate_no_advisory_phrasing(self) -> None:
        self._check('escalate.md')

    def test_delegate_no_advisory_phrasing(self) -> None:
        self._check('delegate.md')


if __name__ == '__main__':
    unittest.main()
