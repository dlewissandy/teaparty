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
MAX_CONTEXT_CHARS = 2000

MAX_FALLBACK_LINES = 5

# ── Prompt templates keyed by CfA state ──
#
# Each approval gate is framed as an alignment validation question:
# the reviewer must decide whether the artifact faithfully represents
# the human's intent at that stage of the pipeline.

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
    "WORK_ASSERT": {
        "template": "work_assert",
        "noun": "deliverables",
    },
}

ASSERT_PROMPT = """You are presenting an intent document for alignment validation.
The reviewer must decide: do they recognize this as their idea, completely and
accurately articulated?

Write 2-3 sentences that frame the review as an alignment question. The reviewer
should engage critically — asking questions, suggesting changes, or flagging
concerns — before deciding whether to approve, correct, or withdraw.

Rules:
- Frame as alignment validation: "Do you recognize this as your idea?"
- Include the file path: {file_path}
- Summarize what the document captures so the reviewer can compare against their intent
- Do NOT reproduce the document content — the reviewer will read it themselves
- No markdown, no bullet points, no headers — just plain conversational text
- 2-3 sentences maximum
- End with: "Think carefully about this. If you are wrong, it creates a permanent record of your failure."

Task: {task}

Document content (for your understanding only — do not reproduce):
{content}"""

PLAN_ASSERT_PROMPT = """You are presenting a plan for alignment validation.
The reviewer must decide: do they recognize this as a strategic plan to
operationalize their idea well?

Write 2-3 sentences that frame the review as an alignment question. The reviewer
has the approved intent document below for comparison — they should verify that
the plan faithfully operationalizes the intent.

Rules:
- Frame as alignment validation: "Do you recognize this as a plan to operationalize your idea well?"
- Include the file path: {file_path}
- Summarize the plan's approach so the reviewer can compare against the intent
- Do NOT reproduce the plan content — the reviewer will read it themselves
- No markdown, no bullet points, no headers — just plain conversational text
- 2-3 sentences maximum
- End with: "Think carefully about this. If you are wrong, it creates a permanent record of your failure."

Task: {task}

Plan content (for your understanding only — do not reproduce):
{content}

Intent document (approved upstream — compare the plan against this):
{intent_context}"""

WORK_ASSERT_PROMPT = """You are presenting completed deliverables for alignment validation.
The reviewer must decide: do they recognize the deliverables and project files
as their idea, completely and well implemented?

Write 2-3 sentences that frame the review as an alignment question. The reviewer
has both the approved intent and the approved plan below for comparison — they
should verify the full chain: intent → plan → execution.

Rules:
- Frame as alignment validation: "Do you recognize these deliverables as your idea, well implemented?"
- Include the file path: {file_path}
- Summarize what was produced so the reviewer can compare against intent and plan
- Do NOT reproduce the full output or list individual files — just the essence
- No markdown, no bullet points, no headers — just plain conversational text
- 2-3 sentences maximum
- End with: "Think carefully about this. If you are wrong, it creates a permanent record of your failure."

Task: {task}

Work summary (for your understanding only — do not reproduce):
{content}

Intent document (approved upstream — compare deliverables against this):
{intent_context}

Plan document (approved upstream — compare deliverables against this):
{plan_context}"""

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


_FALLBACK_QUESTIONS = {
    "INTENT_ASSERT": "Do you recognize this intent document as your idea, completely and accurately articulated?",
    "PLAN_ASSERT": "Do you recognize this plan as a strategic plan to operationalize your idea well?",
    "WORK_ASSERT": "Do you recognize the deliverables as your idea, completely and well implemented?",
}


def fallback_bridge(file_path: str, state: str) -> str:
    """Static fallback when LLM is unavailable."""
    config = STATE_CONFIG.get(state, {"noun": "document"})
    noun = config["noun"]

    question = _FALLBACK_QUESTIONS.get(state, '')
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
    parts = []
    if question:
        parts.append(question)
    parts.append(f"Review {noun} at: {file_path}")
    if preview:
        parts.append(preview + "\n...")
    return '\n'.join(parts)



def generate(
    file_path: str, state: str, task: str,
    intent_context: str = '', plan_context: str = '',
) -> str:
    """Generate a conversational bridge for the given CfA state.

    For PLAN_ASSERT, intent_context should contain the approved INTENT.md
    so the reviewer can compare plan against intent.

    For WORK_ASSERT, both intent_context and plan_context should be provided
    so the reviewer can evaluate the full chain: intent → plan → execution.
    """
    content = read_file_content(file_path)
    if not content:
        return fallback_bridge(file_path, state)

    config = STATE_CONFIG.get(state)
    if config is None:
        # Unknown state — use assert template as default
        config = {"template": "assert", "noun": "document"}

    template = TEMPLATES[config["template"]]

    # Build format kwargs — only include context slots that the template expects
    fmt = {
        'file_path': file_path,
        'task': task or "(no task description)",
        'content': content,
    }
    if '{intent_context}' in template:
        fmt['intent_context'] = (intent_context or '(not available)')[:MAX_CONTEXT_CHARS]
    if '{plan_context}' in template:
        fmt['plan_context'] = (plan_context or '(not available)')[:MAX_CONTEXT_CHARS]

    prompt = template.format(**fmt)

    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "claude-haiku-4-5",
             "--output-format", "text"],
            input=prompt, capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return fallback_bridge(file_path, state)

    output = result.stdout.strip()
    if result.returncode != 0 or not output:
        return fallback_bridge(file_path, state)

    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate CfA review bridge")
    parser.add_argument("--file", required=True, help="Path to the document")
    parser.add_argument("--state", required=True, help="CfA state name")
    parser.add_argument("--task", default="", help="Task description")
    args = parser.parse_args()
    print(generate(args.file, args.state, args.task))
