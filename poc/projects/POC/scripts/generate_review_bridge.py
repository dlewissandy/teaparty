#!/usr/bin/env python3
"""Generate a conversational bridge for CfA review points.

Instead of dumping full documents to the terminal, this produces a 2-3
sentence first-person summary that references the file path and captures
the essence of the document. The terminal stays conversational; the
document is on disk for review.

Usage:
    generate_review_bridge.py --file <path> --state <CFA_STATE> [--task "<task>"]
"""
import argparse
import subprocess
import sys

MAX_FILE_CHARS = 4000
MAX_OUTPUT_CHARS = 800
MAX_FALLBACK_LINES = 5

# ── Prompt templates keyed by CfA state ──

STATE_CONFIG = {
    "INTENT_ASSERT": {
        "template": "assert",
        "noun": "intent document",
    },
    "PLAN_ASSERT": {
        "template": "plan_assert",
        "noun": "plan",
    },
    "INTENT_ESCALATE": {
        "template": "escalate",
        "noun": "intent",
    },
    "PLANNING_ESCALATE": {
        "template": "escalate",
        "noun": "plan",
    },
    "TASK_ESCALATE": {
        "template": "escalate",
        "noun": "task",
    },
    "WORK_ASSERT": {
        "template": "work_assert",
        "noun": "work",
    },
}

ASSERT_PROMPT = """You are an AI agent speaking directly to the human you're working with.
You have just drafted an intent document and saved it to disk. Write 2-3 sentences
that tell the human what you've captured and where to find it.

Rules:
- First person voice ("I've drafted...", "I believe...")
- Include the file path: {file_path}
- Summarize the core problem/objective in one sentence
- Do NOT reproduce the document content — the human will read it themselves
- No markdown, no bullet points, no headers — just plain conversational text
- 2-3 sentences maximum

Task: {task}

Document content (for your understanding only — do not reproduce):
{content}"""

PLAN_ASSERT_PROMPT = """You are an AI agent speaking directly to the human you're working with.
You have just drafted a plan and saved it to disk. Write 2-3 sentences
that tell the human what the plan covers and where to find it.

Rules:
- First person voice ("I've drafted...", "The plan covers...")
- Include the file path: {file_path}
- Summarize the approach in one sentence
- Do NOT reproduce the plan content — the human will read it themselves
- No markdown, no bullet points, no headers — just plain conversational text
- 2-3 sentences maximum

Task: {task}

Plan content (for your understanding only — do not reproduce):
{content}"""

ESCALATE_PROMPT = """You are an AI agent speaking directly to the human you're working with.
You've hit a point where you need the human's input before you can proceed.
You've written your questions to a file. Write 2-3 sentences that tell the human
what you're stuck on and where to find the details.

Rules:
- First person voice ("I need your help with...", "I've hit a point where...")
- Include the file path: {file_path}
- Name the specific blocker or gap in one sentence
- Do NOT reproduce the questions — the human will read them in the file
- No markdown, no bullet points, no headers — just plain conversational text
- 2-3 sentences maximum

Task: {task}

Questions/escalation content (for your understanding only — do not reproduce):
{content}"""

WORK_ASSERT_PROMPT = """You are an AI agent speaking directly to the human you're working with.
You have just completed execution work and are asserting that it is done.
Write 2-3 sentences that tell the human what was accomplished and invite them
to review the result.

Rules:
- First person voice ("I've completed...", "I believe the work is done...")
- Summarize what was accomplished in one concise sentence
- Invite review — the human should verify the changes meet their intent
- Do NOT reproduce the full output or list individual files — just the essence
- No markdown, no bullet points, no headers — just plain conversational text
- 2-3 sentences maximum

Task: {task}

Execution result (for your understanding only — do not reproduce):
{content}"""

TEMPLATES = {
    "assert": ASSERT_PROMPT,
    "plan_assert": PLAN_ASSERT_PROMPT,
    "escalate": ESCALATE_PROMPT,
    "work_assert": WORK_ASSERT_PROMPT,
}


def read_file_content(file_path: str) -> str:
    """Read file content, truncated to MAX_FILE_CHARS."""
    try:
        with open(file_path, 'r') as f:
            content = f.read(MAX_FILE_CHARS)
        if len(content) == MAX_FILE_CHARS:
            content += "\n[... truncated ...]"
        return content
    except (OSError, IOError):
        return ""


def fallback_bridge(file_path: str, state: str) -> str:
    """Static fallback when LLM is unavailable."""
    config = STATE_CONFIG.get(state, {"noun": "document"})
    noun = config["noun"]
    lines = []
    try:
        with open(file_path, 'r') as f:
            for i, line in enumerate(f):
                if i >= MAX_FALLBACK_LINES:
                    break
                lines.append(line.rstrip())
    except (OSError, IOError):
        pass

    preview = '\n'.join(lines)
    if preview:
        return f"[{state}] Review {noun} at: {file_path}\n{preview}\n..."
    return f"[{state}] Review {noun} at: {file_path}"


def truncate_output(text: str) -> str:
    """If output exceeds MAX_OUTPUT_CHARS, truncate to first 3 sentences."""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    # Find first 3 sentence endings
    count = 0
    for i, ch in enumerate(text):
        if ch in '.!?' and i + 1 < len(text) and text[i + 1] in ' \n':
            count += 1
            if count >= 3:
                return text[:i + 1]
    # If we can't find 3 sentences, hard truncate
    return text[:MAX_OUTPUT_CHARS]


def generate(file_path: str, state: str, task: str) -> str:
    """Generate a conversational bridge for the given CfA state."""
    content = read_file_content(file_path)
    if not content:
        return fallback_bridge(file_path, state)

    config = STATE_CONFIG.get(state)
    if config is None:
        # Unknown state — use assert template as default
        config = {"template": "assert", "noun": "document"}

    template = TEMPLATES[config["template"]]
    prompt = template.format(
        file_path=file_path,
        task=task or "(no task description)",
        content=content,
    )

    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "claude-haiku-4-5",
             "--max-turns", "1", "--output-format", "text"],
            input=prompt, capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return fallback_bridge(file_path, state)

    output = result.stdout.strip()
    if result.returncode != 0 or not output:
        return fallback_bridge(file_path, state)

    return truncate_output(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate CfA review bridge")
    parser.add_argument("--file", required=True, help="Path to the document")
    parser.add_argument("--state", required=True, help="CfA state name")
    parser.add_argument("--task", default="", help="Task description")
    args = parser.parse_args()
    print(generate(args.file, args.state, args.task))
