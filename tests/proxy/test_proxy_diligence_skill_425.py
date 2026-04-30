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

    Two halves:
      * Forbid advisory hedges ('optionally', 'if helpful', etc.).
      * Affirm explicit imperative phrasing — the diligence rail must
        contain a sentence that calls itself out as required, not just
        steps that happen to use imperative verbs.

    A cosmetic rewrite that swaps 'walk the worktree' for 'you may walk
    the worktree' would fail both — the first by the affirmative check,
    the second by the forbidden-phrase check.
    """

    _ADVISORY_HINTS = (
        r'\bif\s+helpful\b',
        r'\bif\s+useful\b',
        r'\boptionally\b',
        r'\bmay\s+also\b',
        r'\breview\s+if\b',
    )
    # The skill bodies all carry a sentence affirming the rail's
    # mandatory status.  The exact sentence varies slightly per skill;
    # we accept any of the canonical forms.
    _IMPERATIVE_HINTS = (
        r'required,\s+not\s+advisory',
        r'this\s+is\s+required',
        r'mandatory,\s+not\s+optional',
    )

    def _check_no_advisory(self, skill: str) -> None:
        body = _load(skill)
        for pat in self._ADVISORY_HINTS:
            self.assertIsNone(
                re.search(pat, body, re.IGNORECASE),
                f'{skill}: contains advisory phrasing matching /{pat}/; '
                f'#425 diligence rail must be required, not optional',
            )

    def _check_imperative_present(self, skill: str) -> None:
        body = _load(skill)
        present = any(
            re.search(pat, body, re.IGNORECASE)
            for pat in self._IMPERATIVE_HINTS
        )
        self.assertTrue(
            present,
            f'{skill}: must contain an explicit "required, not advisory" '
            f'(or equivalent) statement on the diligence rail; the '
            f'spec mandates this phrasing so a cosmetic rewrite to '
            f'permissive language is rejected (#425)',
        )

    def test_collaborate_no_advisory_phrasing(self) -> None:
        self._check_no_advisory('collaborate.md')

    def test_escalate_no_advisory_phrasing(self) -> None:
        self._check_no_advisory('escalate.md')

    def test_delegate_no_advisory_phrasing(self) -> None:
        self._check_no_advisory('delegate.md')

    def test_collaborate_has_imperative_statement(self) -> None:
        self._check_imperative_present('collaborate.md')

    def test_escalate_has_imperative_statement(self) -> None:
        self._check_imperative_present('escalate.md')

    def test_delegate_has_imperative_statement(self) -> None:
        self._check_imperative_present('delegate.md')


class DiligenceRailNameFilesTest(unittest.TestCase):
    """Acceptance: 'The proxy's reply names specific files it inspected.'

    The skill body must instruct the proxy to name the files it
    inspected when forming its reply.  Without this instruction the
    diligence rail is invisible to the caller — a proxy that read
    everything but didn't say so is indistinguishable from one that
    read nothing.
    """

    _NAME_FILES_PATTERNS = (
        r'name\s+(the\s+)?specific\s+files',
        r'must\s+name.*files',
        r'reply\s+must\s+name.*files',
    )

    def _check(self, skill: str) -> None:
        body = _load(skill)
        present = any(
            re.search(pat, body, re.IGNORECASE)
            for pat in self._NAME_FILES_PATTERNS
        )
        self.assertTrue(
            present,
            f"{skill}: must instruct the proxy to name specific files "
            f"in its reply; without this the diligence rail is "
            f"unobservable to the caller (#425 acceptance)",
        )

    def test_collaborate_requires_naming_files(self) -> None:
        self._check('collaborate.md')

    def test_escalate_requires_naming_files(self) -> None:
        self._check('escalate.md')

    def test_delegate_requires_naming_files(self) -> None:
        self._check('delegate.md')


if __name__ == '__main__':
    unittest.main()
