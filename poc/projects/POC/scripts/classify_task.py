#!/usr/bin/env python3
"""Classify a task into a project slug and tier using LLM-based intent classification.

Lists existing project directories and asks claude-haiku to match the task
to an existing project or derive a new slug, and assign a tier (0-3).

Usage:
    classify_task.py --task "..." --projects-dir <path>

Returns slug<TAB>tier on stdout (e.g., "multidimensional-travellers-handbook\t2").
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


CLASSIFY_PROMPT = """You are a task classifier for an AI agent workflow. Output EXACTLY one line with two tab-separated fields: the project slug and the tier number.

Task: {task}

Existing projects: {projects}

Memory context (prior learnings and escalation calibrations):
{memory_context}

--- PROJECT SLUG RULES ---
1. If the task clearly belongs to an existing project, return that slug exactly.
2. If new, derive a short kebab-case slug (2-5 words) from the task description.
3. The slug names the PROJECT (larger body of work), not the specific task.
4. Focus on what is being CREATED, not the action being taken.

--- TIER CLASSIFICATION ---
Tier 0 — Conversational: status queries, "what is X", clarifications, no file changes.
Tier 1 — Simple Task: single-file or bounded edit, fully reversible, no ambiguity, known pattern.
Tier 2 — Standard Task: multi-file changes, some ambiguity (words like "feel", "style", "better", "improve"), or needs confirmation.
Tier 3 — Complex Project: multi-team coordination, evolving/unclear requirements, or prior memory shows this task class caused escalations.

BIAS RULE: When between two tiers, choose the higher. Misclassifying Tier 3 as Tier 1 is catastrophic; misclassifying Tier 0 as Tier 2 is merely annoying.

MEMORY WARM-START: If ESCALATION.md shows "Escalate more" for this domain, push tier up. If it shows "More autonomous", pull tier down (never below Tier 1 for tasks touching files).

--- OUTPUT ---
Return EXACTLY one line: <slug><TAB><tier>
No explanation. No quotes. No punctuation. Only slug, tab, digit 0-3.

Examples:
tea-brewing-handbook\t2
POC\t1
dark-energy-research\t3"""


def classify(task: str, projects_dir: str) -> str:
    """Call claude-haiku to classify the task into a project slug and tier."""
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
        return "default\t2"
    except subprocess.TimeoutExpired:
        print("[classify] claude call timed out, using 'default'", file=sys.stderr)
        return "default\t2"

    if result.returncode != 0 or not result.stdout.strip():
        print(f"[classify] claude returned {result.returncode}", file=sys.stderr)
        if result.stderr:
            print(f"[classify] stderr: {result.stderr[:200]}", file=sys.stderr)
        return "default\t2"

    output = result.stdout.strip()

    # Parse tab-separated output
    parts = output.split('\t', 1)
    if len(parts) != 2:
        # Fallback: treat whole output as slug, default to tier 2
        slug = re.sub(r'[^a-z0-9-]', '-', output.lower())
        slug = re.sub(r'-+', '-', slug).strip('-') or "default"
        return f"{slug}\t2"

    slug_raw, tier_raw = parts[0].strip(), parts[1].strip()
    slug = re.sub(r'[^a-z0-9-]', '-', slug_raw.lower())
    slug = re.sub(r'-+', '-', slug).strip('-') or "default"
    tier = tier_raw if tier_raw in ('0', '1', '2', '3') else '2'

    return f"{slug}\t{tier}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Classify task into a project and tier")
    parser.add_argument("--task", required=True, help="Task description")
    parser.add_argument("--projects-dir", required=True, help="Path to projects directory")
    args = parser.parse_args()

    print(classify(args.task, args.projects_dir))
