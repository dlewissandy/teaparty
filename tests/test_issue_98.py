#!/usr/bin/env python3
"""Tests for issue #98: Open questions must be resolved during execution, not planning.

Covers:
 1. PLAN_ASSERT gate: when INTENT.md has [RESOLVE] questions, PLAN.md must
    assign each one to a workflow step. Missing assignments → escalation.
 2. PLAN_ASSERT gate: when INTENT.md has no [RESOLVE] questions, the check
    is a no-op (doesn't block plans for non-issue).
 3. PLAN_ASSERT gate: when all [RESOLVE] questions are assigned, approval
    proceeds normally.
 4. The intent-team prompt defines [RESOLVE] as an execution responsibility.
 5. The uber-team planning prompt tells the planner to assign (not resolve)
    [RESOLVE] questions to workflow steps.
"""
import asyncio
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _make_intent_with_resolve_questions(tmpdir: str, questions: list[str]) -> str:
    """Write an INTENT.md with numbered [RESOLVE] questions.

    Returns the path to INTENT.md.
    """
    lines = ['# INTENT: Test task\n\n## Open Questions\n']
    for i, q in enumerate(questions, 1):
        lines.append(f'{i}. [RESOLVE] {q}\n')
    path = os.path.join(tmpdir, 'INTENT.md')
    with open(path, 'w') as f:
        f.writelines(lines)
    return path


def _make_plan_with_assignments(tmpdir: str, assignments: dict[int, str] | None = None) -> str:
    """Write a PLAN.md. If assignments provided, include an open question
    resolution section mapping question numbers to phases.

    Returns the path to PLAN.md.
    """
    lines = ['# Plan\n\n## Objective\nDo the thing.\n']
    if assignments:
        lines.append('\n## Open question resolution\n')
        for num, phase in assignments.items():
            lines.append(f'- Question {num}: resolved during {phase}\n')
    lines.append('\n## Phases\n### Phase 1: Build\nBuild it.\n')
    path = os.path.join(tmpdir, 'plan.md')
    with open(path, 'w') as f:
        f.writelines(lines)
    return path


def _extract_resolve_questions(intent_text: str) -> list[tuple[int, str]]:
    """Extract numbered [RESOLVE] questions from INTENT.md text.

    This is the function we expect to exist in the production code.
    Returns list of (number, question_text) tuples.
    """
    # Import from production code — will fail until implemented
    from scripts.approval_gate import extract_resolve_questions
    return extract_resolve_questions(intent_text)


def _check_resolve_coverage(intent_text: str, plan_text: str) -> list[int]:
    """Check which [RESOLVE] questions from INTENT.md are NOT addressed in PLAN.md.

    Returns list of unaddressed question numbers.
    This is the function we expect to exist in the production code.
    """
    from scripts.approval_gate import check_resolve_coverage
    return check_resolve_coverage(intent_text, plan_text)


# ── Test: Extraction of [RESOLVE] questions ──────────────────────────────────

class TestExtractResolveQuestions(unittest.TestCase):
    """extract_resolve_questions must find numbered [RESOLVE] items."""

    def test_extracts_numbered_resolve_questions(self):
        intent = (
            "# INTENT: Test\n\n"
            "## Open Questions\n\n"
            "1. [RESOLVE] Should we use SQLite or PostgreSQL?\n"
            "2. [CONFIRM] Does the client want dark mode?\n"
            "3. [RESOLVE] What's the retry policy for failed API calls?\n"
        )
        questions = _extract_resolve_questions(intent)
        self.assertEqual(len(questions), 2)
        self.assertEqual(questions[0][0], 1)
        self.assertIn('SQLite or PostgreSQL', questions[0][1])
        self.assertEqual(questions[1][0], 3)
        self.assertIn('retry policy', questions[1][1])

    def test_no_resolve_questions_returns_empty(self):
        intent = (
            "# INTENT: Simple task\n\n"
            "## Open Questions\n\n"
            "1. [CONFIRM] Which color scheme?\n"
        )
        questions = _extract_resolve_questions(intent)
        self.assertEqual(len(questions), 0)

    def test_handles_missing_open_questions_section(self):
        intent = "# INTENT: Trivial task\n\nJust do the thing.\n"
        questions = _extract_resolve_questions(intent)
        self.assertEqual(len(questions), 0)


# ── Test: Coverage check (INTENT [RESOLVE] → PLAN assignments) ──────────────

class TestCheckResolveCoverage(unittest.TestCase):
    """check_resolve_coverage must identify which [RESOLVE] questions
    are NOT addressed in the plan."""

    def test_all_questions_covered(self):
        intent = (
            "## Open Questions\n\n"
            "1. [RESOLVE] Should we use SQLite?\n"
            "2. [RESOLVE] What retry policy?\n"
        )
        plan = (
            "## Open question resolution\n"
            "- Question 1: resolved during Phase 1 (Research)\n"
            "- Question 2: resolved during Phase 2 (Implementation)\n"
        )
        missing = _check_resolve_coverage(intent, plan)
        self.assertEqual(missing, [])

    def test_missing_questions_detected(self):
        intent = (
            "## Open Questions\n\n"
            "1. [RESOLVE] Should we use SQLite?\n"
            "2. [RESOLVE] What retry policy?\n"
            "3. [RESOLVE] Which auth provider?\n"
        )
        plan = (
            "## Open question resolution\n"
            "- Question 1: resolved during Phase 1\n"
            # Question 2 and 3 are missing
        )
        missing = _check_resolve_coverage(intent, plan)
        self.assertEqual(sorted(missing), [2, 3])

    def test_no_resolve_questions_means_no_missing(self):
        intent = "## Open Questions\n\n1. [CONFIRM] Color scheme?\n"
        plan = "## Phases\n### Phase 1: Build\n"
        missing = _check_resolve_coverage(intent, plan)
        self.assertEqual(missing, [])


# ── Test: PLAN_ASSERT gate enforces [RESOLVE] coverage ──────────────────────

class TestPlanAssertResolveEnforcement(unittest.TestCase):
    """At PLAN_ASSERT, the approval gate must escalate if INTENT.md has
    [RESOLVE] questions that PLAN.md doesn't assign to workflow steps."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_plan_assert_escalates_on_missing_resolve_assignments(self):
        """When INTENT.md has [RESOLVE] questions that PLAN.md doesn't
        assign to workflow steps, check_resolve_coverage flags them."""
        from scripts.approval_gate import check_resolve_coverage

        # INTENT.md with 2 [RESOLVE] questions
        intent_path = _make_intent_with_resolve_questions(self.tmpdir, [
            'Should we use SQLite or PostgreSQL?',
            'What retry policy for failed calls?',
        ])

        # PLAN.md that does NOT address the questions
        plan_path = _make_plan_with_assignments(self.tmpdir, assignments=None)

        with open(intent_path) as f:
            intent_text = f.read()
        with open(plan_path) as f:
            plan_text = f.read()

        missing = check_resolve_coverage(intent_text, plan_text)
        self.assertEqual(sorted(missing), [1, 2],
                         "Both [RESOLVE] questions should be flagged as unaddressed")

    def test_plan_assert_passes_when_all_resolve_assigned(self):
        """PLAN_ASSERT with all [RESOLVE] questions assigned should not
        force escalation (normal proxy flow)."""
        from scripts.approval_gate import check_resolve_coverage

        intent = (
            "## Open Questions\n\n"
            "1. [RESOLVE] Should we use SQLite?\n"
            "2. [RESOLVE] What retry policy?\n"
        )
        plan = (
            "## Open question resolution\n"
            "- Question 1: resolved during Research phase\n"
            "- Question 2: resolved during Implementation phase\n"
        )
        missing = check_resolve_coverage(intent, plan)
        self.assertEqual(missing, [],
                         "All questions assigned — should not flag anything")


# ── Test: Prompt semantics ───────────────────────────────────────────────────

class TestPromptSemantics(unittest.TestCase):
    """Agent prompts must reflect the execution-resolves model."""

    def test_intent_team_resolve_means_execution(self):
        """The intent-team prompt must define [RESOLVE] as an execution
        responsibility, not a planning responsibility."""
        with open(os.path.join(
            Path(__file__).parent.parent,
            'agents', 'intent-team.json'
        )) as f:
            config = json.load(f)
        prompt = config['intent-lead']['prompt']

        # Must NOT say planning resolves
        self.assertNotIn(
            'planning can and must answer this',
            prompt,
            "[RESOLVE] should not be described as a planning responsibility"
        )

    def test_uber_team_planning_assigns_not_resolves(self):
        """The uber-team planning prompt must say 'assign' [RESOLVE] questions
        to workflow steps, not 'resolve' them."""
        with open(os.path.join(
            Path(__file__).parent.parent,
            'agents', 'uber-team.json'
        )) as f:
            config = json.load(f)
        prompt = config['project-lead']['prompt']

        # The planning section should NOT contain "Resolve [RESOLVE] questions"
        # (the old instruction that told planning to answer them)
        planning_section = prompt.split('── PLANNING PHASE ──')[1].split('── EXECUTION PHASE ──')[0]
        self.assertNotIn(
            'Resolve [RESOLVE] questions',
            planning_section,
            "Planning should assign [RESOLVE] questions to phases, not resolve them"
        )

        # Should NOT have "Resolved questions" as a PLAN.md section
        self.assertNotIn(
            'Resolved questions',
            planning_section,
            "PLAN.md should not have a 'Resolved questions' section"
        )


if __name__ == '__main__':
    unittest.main()
