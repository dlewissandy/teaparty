#!/usr/bin/env python3
"""Generate a [CONFIDENCE POSTURE] block for Tier 2/3 sessions.

Reads accumulated memory/escalation context and produces a structured
five-dimension confidence posture for injection at session open.

Usage:
    generate_confidence_posture.py --task "<task>" [--context "<text>"]
"""
import argparse
import subprocess
import sys

POSTURE_PROMPT = """Generate a [CONFIDENCE POSTURE] block for an AI agent about to begin a task.

A confidence posture is a structured self-assessment derived from prior session memory —
NOT generated fresh each time. Derive ratings from the memory context provided.

Task: {task}

Prior memory and calibration context:
{context}

For each dimension below, assign HIGH, MODERATE, or LOW and give a one-line rationale.
Ground every rating in the memory context. If no memory exists for a dimension, mark MODERATE
and note "No prior signal for this task type."

Five dimensions:
- Technical: correctness/viability of the technical approach
- Preference: alignment with user's known decision patterns and style
- Register: tone, formality, format match for this context
- Scope: completeness of requirement identification (known unknowns)
- Domain: breadth and currency of subject-area knowledge

Output EXACTLY this format and nothing else:
[CONFIDENCE POSTURE]
Technical: <HIGH|MODERATE|LOW> — <one-line rationale>
Preference: <HIGH|MODERATE|LOW> — <one-line rationale>
Register: <HIGH|MODERATE|LOW> — <one-line rationale>
Scope: <HIGH|MODERATE|LOW> — <one-line rationale>
Domain: <HIGH|MODERATE|LOW> — <one-line rationale>
"""

COLD_START_POSTURE = """[CONFIDENCE POSTURE]
Technical: MODERATE — Cold start; no prior calibration for this task type.
Preference: MODERATE — Cold start; no prior signal about user preferences.
Register: MODERATE — Cold start; tone/format preferences unknown.
Scope: MODERATE — Cold start; requirement completeness unverified.
Domain: MODERATE — Cold start; domain coverage unconfirmed."""


def generate(task: str, context: str) -> str:
    if not context.strip():
        return COLD_START_POSTURE

    prompt = POSTURE_PROMPT.format(task=task, context=context)
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "claude-haiku-4-5",
             "--output-format", "text"],
            input=prompt, capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return COLD_START_POSTURE

    output = result.stdout.strip()
    if result.returncode != 0 or not output or "[CONFIDENCE POSTURE]" not in output:
        return COLD_START_POSTURE

    # Extract just the posture block
    lines = output.split('\n')
    start = next((i for i, l in enumerate(lines) if '[CONFIDENCE POSTURE]' in l), None)
    if start is None:
        return COLD_START_POSTURE
    return '\n'.join(lines[start:start+6])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate confidence posture block")
    parser.add_argument("--task", required=True)
    parser.add_argument("--context", default="", help="Memory/escalation context text")
    args = parser.parse_args()
    print(generate(args.task, args.context))
