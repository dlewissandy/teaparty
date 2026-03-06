#!/usr/bin/env python3
"""Detect the current project phase from INTENT.md using LLM classification.

Writes the detected phase to a .current-phase file. Prints "PHASE_CHANGED"
to stdout when a transition is detected so the caller can trigger retirement.

Usage:
    detect_phase.py --intent <path> --phase-file <path>

Exit codes:
    0: success (whether or not phase changed)
    1: fatal error
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

PHASES = [
    'specification', 'planning', 'design',
    'implementation', 'review', 'maintenance', 'unknown',
]

_DETECT_PROMPT = """\
Classify the current project phase based on this intent document.

Output EXACTLY one word from this list (lowercase, no punctuation):
  specification, planning, design, implementation, review, maintenance, unknown

Phase meanings:
  specification  – defining requirements, writing specs, gathering intent
  planning       – architectural planning, designing implementation strategies
  design         – designing systems, components, interfaces, data models
  implementation – writing code, building features, creating deliverables
  review         – reviewing, testing, validating, quality checking work
  maintenance    – bug fixes, optimisations, ongoing operations
  unknown        – cannot be determined from the document

Intent document:
{content}

Phase (one word):"""


def detect_phase_from_content(content: str) -> str:
    """Call claude-haiku to classify the project phase from document content.

    Returns a phase string from PHASES. Falls back to 'unknown' on any error.
    """
    if not content.strip():
        return 'unknown'

    prompt = _DETECT_PROMPT.format(content=content[:3000])
    try:
        result = subprocess.run(
            [
                'claude', '-p',
                '--model', 'claude-haiku-4-5',
                '--output-format', 'text',
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return 'unknown'

        raw = result.stdout.strip().lower()
        # Extract first token matching a known phase
        for word in re.findall(r'[a-z]+', raw):
            if word in PHASES:
                return word
        return 'unknown'

    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 'unknown'


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Detect project phase from INTENT.md and write to .current-phase'
    )
    parser.add_argument('--intent', required=True, help='Path to INTENT.md')
    parser.add_argument('--phase-file', required=True, help='Path to .current-phase state file')
    args = parser.parse_args()

    intent_path = Path(args.intent)
    phase_path = Path(args.phase_file)

    if not intent_path.is_file():
        print(f'[detect_phase] INTENT.md not found: {intent_path}', file=sys.stderr)
        return 0  # non-fatal: no intent = no phase transition

    content = intent_path.read_text(errors='replace')

    # Read the previously stored phase before overwriting
    old_phase = ''
    if phase_path.is_file():
        old_phase = phase_path.read_text().strip()

    new_phase = detect_phase_from_content(content)

    # Write updated phase (always, even if unchanged — confirms liveness)
    phase_path.write_text(new_phase + '\n')
    print(f'[detect_phase] Phase: {old_phase or "(none)"} → {new_phase}', file=sys.stderr)

    # Signal phase transition to caller via stdout
    if old_phase and old_phase != new_phase and old_phase != 'unknown':
        print('PHASE_CHANGED', flush=True)
        print(
            f'[detect_phase] Transition detected: {old_phase} → {new_phase}',
            file=sys.stderr,
        )

    return 0


if __name__ == '__main__':
    sys.exit(main())
