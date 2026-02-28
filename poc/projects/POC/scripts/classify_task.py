#!/usr/bin/env python3
"""Classify a task into a project slug using LLM-based intent classification.

Lists existing project directories and asks claude-haiku to match the task
to an existing project or derive a new slug.

Usage:
    classify_task.py --task "..." --projects-dir <path>

Returns a kebab-case slug on stdout (e.g., "multidimensional-travellers-handbook").
"""
import argparse
import os
import re
import subprocess
import sys


def list_existing_projects(projects_dir: str) -> list[str]:
    """List existing project directory names."""
    if not os.path.isdir(projects_dir):
        return []
    return sorted(
        d for d in os.listdir(projects_dir)
        if os.path.isdir(os.path.join(projects_dir, d))
    )


CLASSIFY_PROMPT = """Given this task description and the list of existing projects, determine which project this task belongs to.

Task: {task}

Existing projects: {projects}

Rules:
1. If the task clearly belongs to an existing project, return that project's slug exactly.
2. If the task is for a new project, derive a short kebab-case slug (2-5 words) from the task description.
3. The slug should name the PROJECT (the larger body of work), not the specific task.
4. Focus on what's being CREATED, not the action being taken.

Examples:
- "Write chapter 1 of the tea brewing handbook" → "tea-brewing-handbook"
- "Revise the first chapter of the multidimensional traveller's handbook to reflect dark energy research" → "multidimensional-travellers-handbook"
- "Research dark energy for the handbook" → could be the handbook project if one exists, or "dark-energy-research" if standalone

Return ONLY the slug on a single line. No explanation, no quotes, no punctuation."""


def classify(task: str, projects_dir: str) -> str:
    """Call claude-haiku to classify the task into a project slug."""
    existing = list_existing_projects(projects_dir)
    projects_str = ", ".join(existing) if existing else "(none — this will be the first project)"

    prompt = CLASSIFY_PROMPT.format(task=task, projects=projects_str)

    try:
        result = subprocess.run(
            [
                "claude",
                "-p",
                "--model", "claude-haiku-4-5",
                "--max-turns", "1",
                "--output-format", "text",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        print("[classify] claude CLI not found, using 'default'", file=sys.stderr)
        return "default"
    except subprocess.TimeoutExpired:
        print("[classify] claude call timed out, using 'default'", file=sys.stderr)
        return "default"

    if result.returncode != 0 or not result.stdout.strip():
        print(f"[classify] claude returned {result.returncode}", file=sys.stderr)
        if result.stderr:
            print(f"[classify] stderr: {result.stderr[:200]}", file=sys.stderr)
        return "default"

    slug = result.stdout.strip().lower()

    # Sanitize: keep only alphanumeric and hyphens
    slug = re.sub(r'[^a-z0-9-]', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')

    if not slug:
        return "default"

    return slug


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Classify task into a project")
    parser.add_argument("--task", required=True, help="Task description")
    parser.add_argument("--projects-dir", required=True, help="Path to projects directory")
    args = parser.parse_args()

    slug = classify(args.task, args.projects_dir)
    print(slug)
