#!/usr/bin/env python3
"""Run a pre-mortem risk assessment before task execution.

Generates a structured risk document identifying what could go wrong.

Usage:
    run_premortem.py --task "<task>" --output <premortem.md> [--context-file <path>]
"""
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PREMORTEM_PROMPT = """You are conducting a pre-mortem risk assessment for an AI agent task that has NOT yet started.

Task: {task}

Prior context (project memory, escalation history):
{context}

Imagine the task was completed and it went badly wrong. What happened?

Identify 3-6 specific, concrete risks. For each risk:
1. Name it specifically (not "communication problems" but "writing team produces content in wrong register because audience was not specified in the task brief")
2. Rate likelihood: High / Medium / Low
3. Rate impact if it occurs: High / Medium / Low
4. Give a concrete mitigation the executing agent can apply proactively NOW

Format as:

# Pre-Mortem Risk Assessment
Task: {task_short}
Generated: {timestamp}

## Risk 1: <concrete name>
**Likelihood:** High | Medium | Low
**Impact:** High | Medium | Low
**Description:** <what specifically could go wrong>
**Mitigation:** <concrete action the agent can take before or during execution>

[repeat for each risk, numbered sequentially]

Output ONLY the pre-mortem document. No preamble or meta-commentary."""


def run_premortem(task: str, output_path: str, context: str) -> int:
    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    task_short = task[:80] + ("..." if len(task) > 80 else "")

    prompt = PREMORTEM_PROMPT.format(
        task=task,
        task_short=task_short,
        context=context or "(no prior memory)",
        timestamp=timestamp,
    )

    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "claude-haiku-4-5",
             "--output-format", "text"],
            input=prompt, capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        print("[premortem] claude CLI not found, skipping.", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print("[premortem] claude call timed out, skipping.", file=sys.stderr)
        return 1

    if result.returncode != 0 or not result.stdout.strip():
        return 1

    output = result.stdout.strip()
    if "# Pre-Mortem" not in output and "## Risk" not in output:
        print("[premortem] Output did not match expected format, skipping.", file=sys.stderr)
        return 1

    Path(output_path).write_text(output + "\n")
    print(f"[premortem] Written to {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run pre-mortem risk assessment")
    parser.add_argument("--task", required=True)
    parser.add_argument("--output", required=True, help="Path to write premortem.md")
    parser.add_argument("--context-file", dest="context_file", default=None)
    args = parser.parse_args()

    context = ""
    if args.context_file:
        p = Path(args.context_file)
        if p.is_file():
            context = p.read_text()[:4000]

    sys.exit(run_premortem(args.task, args.output, context))
