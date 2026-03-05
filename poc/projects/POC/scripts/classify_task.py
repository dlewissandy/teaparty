#!/usr/bin/env python3
"""Classify a task into a project slug and mode (workflow|conversational).

Lists existing project directories and asks claude-haiku to match the task
to an existing project or derive a new slug, and determine the task mode.

Usage:
    classify_task.py --task "..." --projects-dir <path>

Returns slug<TAB>mode on stdout (e.g., "multidimensional-travellers-handbook\tworkflow").
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


def read_memory_context(projects_dir: str, slug: str) -> str:
    """Read ESCALATION.md and MEMORY.md for warm-start context. Truncate to 2000 chars each."""
    parts = []
    for fname in ["ESCALATION.md", "MEMORY.md"]:
        for dirpath in [os.path.join(projects_dir, slug), projects_dir]:
            fpath = os.path.join(dirpath, fname)
            if os.path.isfile(fpath):
                try:
                    text = open(fpath).read(2000).strip()
                    if text:
                        parts.append(f"--- {fname} ---\n{text}")
                except Exception:
                    pass
                break
    return "\n\n".join(parts)


CLASSIFY_PROMPT = """You are a task classifier for an AI agent workflow. Output EXACTLY one line with two tab-separated fields: the project slug and the task mode.

Task: {task}

Existing projects: {projects}

Memory context (prior learnings and escalation calibrations):
{memory_context}

--- PROJECT SLUG RULES ---
1. If the task clearly belongs to an existing project, return that slug exactly.
2. If new, derive a short kebab-case slug (2-5 words) from the task description.
3. The slug names the PROJECT (larger body of work), not the specific task.
4. Focus on what is being CREATED, not the action being taken.

--- MODE CLASSIFICATION ---
conversational — Status queries, "what is X", clarifications, questions requiring NO file changes and only a short answer. Protect this mode: misclassifying a simple question as workflow erodes trust.
workflow — Everything else: file changes, code, writing, research, creative work, builds, fixes, any sustained effort.

--- OUTPUT ---
Return EXACTLY one line: <slug><TAB><mode>
No explanation. No quotes. No punctuation. Only slug, tab, then either "workflow" or "conversational".

Examples:
tea-brewing-handbook\tworkflow
POC\tworkflow
POC\tconversational
default\tconversational"""


def classify(task: str, projects_dir: str) -> str:
    """Call claude-haiku to classify the task into a project slug and mode."""
    existing = list_existing_projects(projects_dir)
    projects_str = ", ".join(existing) if existing else "(none — this will be the first project)"

    # Memory warm-start: derive slug guess for context lookup
    slug_guess = existing[0] if len(existing) == 1 else "default"
    memory_context = read_memory_context(projects_dir, slug_guess)

    prompt = CLASSIFY_PROMPT.format(
        task=task,
        projects=projects_str,
        memory_context=memory_context or "(no prior memory)",
    )

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
        return "default\tworkflow"
    except subprocess.TimeoutExpired:
        print("[classify] claude call timed out, using 'default'", file=sys.stderr)
        return "default\tworkflow"

    if result.returncode != 0 or not result.stdout.strip():
        print(f"[classify] claude returned {result.returncode}", file=sys.stderr)
        if result.stderr:
            print(f"[classify] stderr: {result.stderr[:200]}", file=sys.stderr)
        return "default\tworkflow"

    output = result.stdout.strip()

    # Parse tab-separated output
    parts = output.split('\t', 1)
    if len(parts) != 2:
        # Fallback: treat whole output as slug, default to workflow
        slug = re.sub(r'[^a-z0-9-]', '-', output.lower())
        slug = re.sub(r'-+', '-', slug).strip('-') or "default"
        return f"{slug}\tworkflow"

    slug_raw, mode_raw = parts[0].strip(), parts[1].strip().lower()
    slug = re.sub(r'[^a-z0-9-]', '-', slug_raw.lower())
    slug = re.sub(r'-+', '-', slug).strip('-') or "default"
    mode = mode_raw if mode_raw in ('workflow', 'conversational') else 'workflow'

    return f"{slug}\t{mode}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Classify task into a project and mode")
    parser.add_argument("--task", required=True, help="Task description")
    parser.add_argument("--projects-dir", required=True, help="Path to projects directory")
    args = parser.parse_args()

    print(classify(args.task, args.projects_dir))
