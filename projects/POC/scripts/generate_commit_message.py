#!/usr/bin/env python3
"""Generate an LLM-powered git commit message.

Usage:
    generate_commit_message.py --task "..." --team "coding"
        [--dispatch-log "..."] [--files "..."]

Returns a commit message on stdout. Falls back to a structured message on LLM error.
"""
import argparse
import subprocess
import sys

MAX_TASK_CHARS = 500
MAX_LOG_CHARS = 2000
MAX_FILES_CHARS = 1000

COMMIT_PROMPT = """Generate a git commit message for a software project.

Team: {team}
Task: {task}
{dispatch_log_block}
Files changed:
{files}

(These files are context only. Do NOT list or repeat them in your output — they appear in git diff already.)

Write a commit message with:
- Subject line: "{team}: <imperative summary>" (max 72 chars)
- Blank line
- Body: 2-3 lines explaining WHAT changed and WHY (purpose/impact)

Output ONLY the commit message text, nothing else."""


def build_fallback(team: str, task: str) -> str:
    """Structured fallback when LLM is unavailable."""
    subject = task.strip()[:60] if task.strip() else "dispatch"
    return f"{team}: {subject}"


def generate(task: str, team: str, dispatch_log: str = "", files: str = "") -> str:
    """Generate a commit message using the LLM, with fallback."""
    if not team.strip():
        team = "task"
    dispatch_log_block = ""
    if dispatch_log.strip():
        dispatch_log_block = f"\nSquashed commits:\n{dispatch_log.strip()[:MAX_LOG_CHARS]}\n"
    files_text = files.strip()[:MAX_FILES_CHARS] if files.strip() else "(none)"
    task_text = task.strip()[:MAX_TASK_CHARS] if task.strip() else "(no task)"

    prompt = COMMIT_PROMPT.format(
        team=team,
        task=task_text,
        dispatch_log_block=dispatch_log_block,
        files=files_text,
    )

    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "claude-haiku-4-5",
             "--output-format", "text"],
            input=prompt, capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return build_fallback(team, task)

    output = result.stdout.strip()
    if result.returncode != 0 or not output:
        return build_fallback(team, task)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate LLM-powered git commit message")
    parser.add_argument("--task", default="",
                        help="Task description")
    parser.add_argument("--team", default="task",
                        help="Team or context name (e.g. coding)")
    parser.add_argument("--dispatch-log", default="",
                        help="Squashed commit log (multi-line '- subject' format)")
    parser.add_argument("--files", default="",
                        help="Newline-separated list of changed files")
    args = parser.parse_args()
    print(generate(args.task, args.team, args.dispatch_log, args.files))
