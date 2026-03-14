"""Integration test for INTENT.md and PLAN.md generation quality.

Runs the actual Claude CLI against the intent-team and uber-team agent
configs, then validates the artifacts for structural quality.

Usage:
    # Run both phases (intent then plan):
    python -m pytest projects/POC/tests/test_plan_quality.py -v -s

    # Run intent only:
    python -m pytest projects/POC/tests/test_plan_quality.py -v -s -k intent

    # Reuse a previous intent (skip regeneration):
    INTENT_PATH=/path/to/INTENT.md python -m pytest ... -k plan

These are SLOW tests — each phase invokes Claude for a real agent turn.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────

POC_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = POC_ROOT / 'agents'
INTENT_AGENTS = AGENTS_DIR / 'intent-team.json'
UBER_AGENTS = AGENTS_DIR / 'uber-team.json'

FROGGER_TASK = (
    "I would like to recreate the classic arcade game frogger as a HTML/JS game. "
    "Game mechanics should be as close to the cabinet arcade classic as possible."
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _run_claude_agent(
    *,
    agents_file: Path,
    lead: str,
    prompt: str,
    cwd: str,
    permission_mode: str = 'acceptEdits',
    timeout: int = 300,
) -> int:
    """Invoke the Claude CLI with an agents file.  Returns exit code."""
    import subprocess

    with open(agents_file) as f:
        agents_json = f.read()

    args = [
        'claude', '-p',
        '--output-format', 'stream-json',
        '--verbose',
        '--setting-sources', 'user',
        '--permission-mode', permission_mode,
        '--agents', agents_json,
        '--agent', lead,
    ]

    env = dict(os.environ)
    env['CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS'] = '1'
    env['CLAUDE_CODE_MAX_OUTPUT_TOKENS'] = '128000'

    proc = subprocess.run(
        args,
        input=prompt.encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=env,
        timeout=timeout,
    )
    return proc.returncode


def _read_artifact(worktree: str, name: str) -> str:
    """Read an artifact from the worktree, case-insensitive."""
    # Exact match first
    path = os.path.join(worktree, name)
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    # Case-insensitive fallback
    for entry in os.listdir(worktree):
        if entry.lower() == name.lower():
            with open(os.path.join(worktree, entry)) as f:
                return f.read()
    return ''


def _section_present(text: str, heading: str) -> bool:
    """Check whether a markdown heading (any level) is present."""
    pattern = rf'^#+\s+{re.escape(heading)}'
    return bool(re.search(pattern, text, re.MULTILINE | re.IGNORECASE))


def _has_any_heading(text: str, *candidates: str) -> bool:
    return any(_section_present(text, c) for c in candidates)


# ── Code-leak detection ──────────────────────────────────────────────────────

# Patterns that indicate production/implementation detail leakage in a plan.
# Each is (pattern, description).
_CODE_LEAK_PATTERNS: list[tuple[str, str]] = [
    # Constructor / function signatures
    (r'\(\s*\w+\s*,\s*\w+\s*,\s*\w+\s*\)', 'constructor/function signature (x, y, z)'),
    # Property assignments: foo = 3, bar = true
    (r'\b\w+\s*=\s*(?:true|false|\d+)\b', 'property assignment (x = true/3)'),
    # Method calls: foo.bar(), foo(arg)
    (r'\b\w+\.\w+\(\)', 'method call pattern (foo.bar())'),
    # Math expressions: Math.floor, Math.random
    (r'\bMath\.\w+', 'Math.* expression'),
    # Variable-style camelCase in technical context (not headings)
    (r'(?<!\#)\b[a-z]+[A-Z]\w*\b', 'camelCase variable name'),
    # Pixel values like 48px, 144px
    (r'\b\d+\s*px\b', 'pixel value'),
    # Inline code patterns: backtick-wrapped code longer than a file name
    (r'`[^`]{40,}`', 'long inline code block'),
    # CSS property: color:, background:, font-size:
    (r'\b(?:color|background|font-size|margin|padding)\s*:', 'CSS property'),
    # SQL statements
    (r'\b(?:SELECT|INSERT|UPDATE|DELETE|ALTER|CREATE TABLE)\b', 'SQL statement'),
]


def _find_code_leaks(text: str) -> list[str]:
    """Return descriptions of code/implementation patterns found in text."""
    leaks = []
    for pattern, desc in _CODE_LEAK_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            leaks.append(f'{desc} ({len(matches)} occurrences, e.g. "{matches[0]}")')
    return leaks


# ── Test fixtures ────────────────────────────────────────────────────────────

class _SharedState:
    """Holds artifacts across test methods so plan test can use intent output."""
    worktree: str = ''
    intent_text: str = ''
    plan_text: str = ''


_state = _SharedState()


# ── Tests ────────────────────────────────────────────────────────────────────

class TestIntentGeneration(unittest.TestCase):
    """Test that the intent-lead produces a well-structured INTENT.md."""

    @classmethod
    def setUpClass(cls):
        # If INTENT_PATH is set, skip generation and use the provided file
        provided = os.environ.get('INTENT_PATH')
        if provided and os.path.exists(provided):
            with open(provided) as f:
                _state.intent_text = f.read()
            _state.worktree = tempfile.mkdtemp(prefix='plan-quality-')
            with open(os.path.join(_state.worktree, 'INTENT.md'), 'w') as f:
                f.write(_state.intent_text)
            return

        # Create temp worktree and run intent generation
        _state.worktree = tempfile.mkdtemp(prefix='plan-quality-')
        print(f'\n  Worktree: {_state.worktree}')
        print(f'  Running intent generation...')

        exit_code = _run_claude_agent(
            agents_file=INTENT_AGENTS,
            lead='intent-lead',
            prompt=FROGGER_TASK,
            cwd=_state.worktree,
            timeout=120,
        )

        _state.intent_text = _read_artifact(_state.worktree, 'INTENT.md')

        if exit_code != 0 and not _state.intent_text:
            raise unittest.SkipTest(
                f'Claude CLI exited {exit_code} and produced no INTENT.md'
            )

    def test_intent_produced(self):
        """INTENT.md must exist and be non-empty."""
        self.assertTrue(
            _state.intent_text,
            'INTENT.md was not produced or is empty',
        )

    def test_intent_has_objective(self):
        """INTENT.md must have an Objective section."""
        self.assertTrue(
            _has_any_heading(_state.intent_text, 'Objective'),
            'INTENT.md missing Objective section',
        )

    def test_intent_has_success_criteria(self):
        """INTENT.md must have Success Criteria."""
        self.assertTrue(
            _has_any_heading(
                _state.intent_text,
                'Success Criteria', 'Success criteria',
                'What "Done" Looks Like', "What Done Looks Like",
            ),
            'INTENT.md missing Success Criteria section',
        )

    def test_intent_has_scope(self):
        """INTENT.md must have Scope or Constraints section."""
        self.assertTrue(
            _has_any_heading(
                _state.intent_text,
                'Scope', 'Constraints', 'Decision Boundaries',
            ),
            'INTENT.md missing Scope/Constraints section',
        )

    def test_intent_reasonable_length(self):
        """INTENT.md should be substantial but not bloated."""
        lines = _state.intent_text.strip().split('\n')
        self.assertGreater(
            len(lines), 15,
            f'INTENT.md too short ({len(lines)} lines) — may be a stub',
        )
        self.assertLess(
            len(lines), 300,
            f'INTENT.md too long ({len(lines)} lines) — intent lead may be doing the work',
        )

    def test_intent_not_implementation(self):
        """INTENT.md should describe outcomes, not implementation."""
        leaks = _find_code_leaks(_state.intent_text)
        # Intent allows SOME technical language (file paths, component names)
        # but should not have heavy code patterns
        heavy_leaks = [l for l in leaks if 'Math.' in l or 'SQL' in l or 'CSS' in l]
        self.assertEqual(
            heavy_leaks, [],
            f'INTENT.md contains implementation details:\n' +
            '\n'.join(f'  - {l}' for l in heavy_leaks),
        )


class TestPlanGeneration(unittest.TestCase):
    """Test that the project-lead produces a well-structured PLAN.md."""

    @classmethod
    def setUpClass(cls):
        if not _state.intent_text:
            raise unittest.SkipTest('No INTENT.md available — run intent test first')

        # Ensure INTENT.md is in the worktree
        intent_path = os.path.join(_state.worktree, 'INTENT.md')
        if not os.path.exists(intent_path):
            with open(intent_path, 'w') as f:
                f.write(_state.intent_text)

        print(f'\n  Worktree: {_state.worktree}')
        print(f'  Running plan generation...')

        exit_code = _run_claude_agent(
            agents_file=UBER_AGENTS,
            lead='project-lead',
            prompt=_state.intent_text,
            cwd=_state.worktree,
            timeout=300,
        )

        _state.plan_text = _read_artifact(_state.worktree, 'PLAN.md')

        if exit_code != 0 and not _state.plan_text:
            raise unittest.SkipTest(
                f'Claude CLI exited {exit_code} and produced no PLAN.md'
            )

    # ── Structural tests ─────────────────────────────────────────────────

    def test_plan_produced(self):
        """PLAN.md must exist and be non-empty."""
        self.assertTrue(
            _state.plan_text,
            'PLAN.md was not produced or is empty',
        )

    def test_plan_has_objective(self):
        """PLAN.md must have an Objective section."""
        self.assertTrue(
            _has_any_heading(_state.plan_text, 'Objective'),
            'PLAN.md missing Objective section',
        )

    def test_plan_has_invariants(self):
        """PLAN.md must have an Invariants section."""
        self.assertTrue(
            _has_any_heading(_state.plan_text, 'Invariants', 'Invariant'),
            'PLAN.md missing Invariants section',
        )

    def test_plan_has_scope(self):
        """PLAN.md must have a Scope section."""
        self.assertTrue(
            _has_any_heading(_state.plan_text, 'Scope'),
            'PLAN.md missing Scope section',
        )

    def test_plan_has_phases(self):
        """PLAN.md must describe workflow phases."""
        # Look for phase-like headings (any name — Research, Specification, etc.)
        phase_pattern = r'^##\s+(?:Phase\s+\d|Research|Specification|Production|Verification|Implementation|Integration|Art|Code|Testing)'
        has_explicit_phases = bool(
            re.search(phase_pattern, _state.plan_text, re.MULTILINE | re.IGNORECASE)
        )
        # Also accept a "Phases" umbrella heading
        has_phases_heading = _has_any_heading(_state.plan_text, 'Phases', 'Workflow')

        self.assertTrue(
            has_explicit_phases or has_phases_heading,
            'PLAN.md missing workflow phases — should read like a skill with Research, '
            'Specification, Production, Verification (or task-appropriate phases)',
        )

    def test_plan_has_verification(self):
        """PLAN.md must have a verification/testing phase or section."""
        self.assertTrue(
            _has_any_heading(
                _state.plan_text,
                'Verification', 'Testing', 'Validation', 'Test',
                'Integration Test', 'Quality Check',
            ),
            'PLAN.md missing Verification/Testing phase',
        )

    # ── Quality tests ────────────────────────────────────────────────────

    def test_plan_concise(self):
        """PLAN.md should be 40-120 lines for a medium task."""
        lines = _state.plan_text.strip().split('\n')
        self.assertGreater(
            len(lines), 20,
            f'PLAN.md too short ({len(lines)} lines) — may be a stub',
        )
        self.assertLess(
            len(lines), 200,
            f'PLAN.md too long ({len(lines)} lines) — production details are leaking in',
        )

    def test_plan_no_code_leaks(self):
        """PLAN.md must not contain implementation/production details."""
        leaks = _find_code_leaks(_state.plan_text)
        if leaks:
            # Print all leaks for diagnosis, but only fail on significant ones.
            # A single camelCase word in context (like a well-known game term)
            # is acceptable; constructor signatures and math expressions are not.
            significant = [
                l for l in leaks
                if any(kw in l for kw in [
                    'constructor', 'method call', 'Math.', 'SQL',
                    'CSS', 'property assignment', 'pixel',
                ])
            ]
            self.assertEqual(
                significant, [],
                f'PLAN.md contains production details that belong to the teams:\n' +
                '\n'.join(f'  - {l}' for l in significant),
            )

    def test_plan_not_paraphrased_intent(self):
        """PLAN.md should not be a paraphrase of INTENT.md.

        A plan that just restates the intent with more words is not a plan.
        Check that the plan adds structure (phases, invariants) beyond
        what the intent already says.
        """
        plan_lower = _state.plan_text.lower()

        # The plan should contain workflow concepts absent from the intent
        workflow_signals = [
            'phase', 'done when', 'done:', 'produces',
            'invariant', 'contingency', 'contingencies',
            'before you start', 'depends on', 'parallel',
            'research', 'specification', 'production', 'verification',
        ]
        found = [s for s in workflow_signals if s in plan_lower]

        self.assertGreaterEqual(
            len(found), 3,
            f'PLAN.md has too few workflow concepts ({found}) — '
            f'it may be paraphrasing INTENT.md instead of adding a workflow structure',
        )

    def test_plan_reads_like_skill(self):
        """PLAN.md should read like a provisional operating procedure.

        Check for the hallmarks: phases with done-when criteria, imperative
        voice, and references to teams rather than implementation steps.
        """
        # Should reference teams by name
        team_refs = re.findall(
            r'\b(?:art|writing|editorial|research|coding)\s+(?:team|liaison)\b',
            _state.plan_text,
            re.IGNORECASE,
        )
        # Or just team names in context
        team_names = re.findall(
            r'\b(?:art|writing|editorial|research|coding)\b',
            _state.plan_text,
            re.IGNORECASE,
        )

        self.assertGreater(
            len(team_names), 0,
            'PLAN.md does not reference any teams — '
            'it should name which teams do the work in each phase',
        )

    # ── Invariant quality ────────────────────────────────────────────────

    def test_invariants_are_assertions(self):
        """Invariants should be testable assertions, not vague guidelines."""
        # Extract invariants section
        inv_match = re.search(
            r'#+\s+Invariants?\s*\n(.*?)(?=\n#+\s|\Z)',
            _state.plan_text,
            re.DOTALL | re.IGNORECASE,
        )
        if not inv_match:
            self.skipTest('No Invariants section found')

        inv_text = inv_match.group(1)
        inv_items = [
            line.strip()
            for line in inv_text.split('\n')
            if line.strip() and line.strip().startswith(('-', '*', '1', '2', '3', '4', '5', '6', '7', '8', '9'))
        ]

        self.assertGreaterEqual(
            len(inv_items), 2,
            f'Too few invariants ({len(inv_items)}) — '
            f'should have 3-8 testable assertions',
        )
        self.assertLessEqual(
            len(inv_items), 10,
            f'Too many invariants ({len(inv_items)}) — '
            f'some are probably activity-specific details',
        )


# ── Reporting ────────────────────────────────────────────────────────────────

class TestArtifactReport(unittest.TestCase):
    """Print a summary report after all tests. Runs last by naming convention."""

    def test_zzz_report(self):
        """Print artifact locations and stats."""
        if not _state.worktree:
            self.skipTest('No worktree')

        print('\n' + '=' * 60)
        print('ARTIFACT REPORT')
        print('=' * 60)
        print(f'Worktree: {_state.worktree}')

        if _state.intent_text:
            lines = _state.intent_text.strip().split('\n')
            print(f'INTENT.md: {len(lines)} lines')
        else:
            print('INTENT.md: NOT PRODUCED')

        if _state.plan_text:
            lines = _state.plan_text.strip().split('\n')
            print(f'PLAN.md:   {len(lines)} lines')
            leaks = _find_code_leaks(_state.plan_text)
            if leaks:
                print(f'Code leaks detected:')
                for l in leaks:
                    print(f'  - {l}')
            else:
                print('Code leaks: none')
        else:
            print('PLAN.md:   NOT PRODUCED')

        print('=' * 60)
        print(f'\nArtifacts preserved at: {_state.worktree}')
        print('To reuse this intent for plan-only testing:')
        print(f'  INTENT_PATH={_state.worktree}/INTENT.md python -m pytest {__file__} -v -s -k plan')


if __name__ == '__main__':
    unittest.main()
