#!/usr/bin/env python3
"""Generate an agent-voice dialog response during CfA review.

When the human asks a question at a review point (ASSERT or ESCALATE),
this script generates a conversational response from the agent's perspective
so the human can make an informed decision.

Usage:
    generate_dialog_response.py --state <STATE> --question "<text>"
        [--artifact PATH] [--exec-stream PATH]
        [--task "<text>"] [--dialog-history "<text>"]

Returns plain text response on stdout (2-4 sentences, first person).
"""
import argparse
import subprocess
import sys

MAX_ARTIFACT_CHARS = 4000
MAX_EXEC_CHARS = 2000
MAX_OUTPUT_CHARS = 600

FALLBACK_RESPONSE = (
    "I'm not sure I can answer that right now. "
    "Could you rephrase, or let me know your decision?"
)

# ── Prompt template ──

DIALOG_PROMPT = """You are an AI agent in a review session with the human who assigned your task. The human has asked a question or made a comment during their review of your work. Answer from the agent's perspective — first person ("I did...", "Yes, I tested...").

--- CfA STATE ---
{state}

--- TASK ---
{task}

--- DELIVERABLE ---
{artifact_content}
{extra_context}
{dialog_history_block}
--- HUMAN'S QUESTION ---
{question}

--- INSTRUCTIONS ---
- Answer the question directly and concisely (2-4 sentences)
- First person voice — you ARE the agent being reviewed
- If you don't know the answer based on the context provided, say so honestly
- Do not make decisions for the human — answer the question, then wait for their decision
- No markdown formatting — plain conversational text"""


def read_file_content(path: str, max_chars: int = MAX_ARTIFACT_CHARS) -> str:
    """Read file content, truncated to max_chars."""
    try:
        with open(path, "r") as f:
            return f.read(max_chars)
    except (FileNotFoundError, PermissionError, OSError):
        return ""


def read_exec_stream(path: str, max_chars: int = MAX_EXEC_CHARS) -> str:
    """Extract result text from an exec stream JSONL file."""
    try:
        result = subprocess.run(
            ["python3", "-c",
             f"import sys; sys.path.insert(0,'.'); "
             f"exec(open('{path}').read()[-{max_chars}:])"],
            capture_output=True, text=True, timeout=5,
        )
        # Fallback: just read last N chars of the file directly
    except Exception:
        pass
    # Simple fallback: read last max_chars of the file
    try:
        with open(path, "r") as f:
            f.seek(0, 2)  # seek to end
            size = f.tell()
            start = max(0, size - max_chars)
            f.seek(start)
            return f.read()
    except (FileNotFoundError, PermissionError, OSError):
        return ""


def truncate_output(text: str, max_chars: int = MAX_OUTPUT_CHARS) -> str:
    """Truncate output to max chars, breaking at sentence boundaries."""
    if len(text) <= max_chars:
        return text.strip()
    truncated = text[:max_chars]
    # Try to break at last sentence boundary
    for sep in [". ", "! ", "? "]:
        idx = truncated.rfind(sep)
        if idx > max_chars // 2:
            return truncated[:idx + 1].strip()
    return truncated.strip()


def build_context(state: str, artifact_path: str = "",
                  exec_stream_path: str = "", task: str = "",
                  dialog_history: str = "") -> dict:
    """Build context dict for the prompt."""
    artifact_content = ""
    if artifact_path:
        artifact_content = read_file_content(artifact_path)
    if not artifact_content:
        artifact_content = "(no artifact content available)"

    extra_context = ""
    if exec_stream_path and state == "WORK_ASSERT":
        stream_tail = read_exec_stream(exec_stream_path)
        if stream_tail:
            extra_context = (
                "\n--- EXECUTION LOG (recent) ---\n"
                f"{stream_tail}\n"
            )

    dialog_history_block = ""
    if dialog_history and dialog_history.strip():
        dialog_history_block = (
            "\n--- PRIOR DIALOG ---\n"
            f"{dialog_history.strip()}\n"
        )

    return {
        "artifact_content": artifact_content,
        "extra_context": extra_context,
        "dialog_history_block": dialog_history_block,
        "task": task or "(no task description)",
    }


def generate(state: str, question: str,
             artifact_path: str = "", exec_stream_path: str = "",
             task: str = "", dialog_history: str = "") -> str:
    """Generate an agent-voice response to the human's question."""
    if not question or not question.strip():
        return FALLBACK_RESPONSE

    ctx = build_context(state, artifact_path, exec_stream_path,
                        task, dialog_history)

    prompt = DIALOG_PROMPT.format(
        state=state,
        question=question,
        **ctx,
    )

    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "claude-haiku-4-5",
             "--output-format", "text"],
            input=prompt, capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return FALLBACK_RESPONSE

    if result.returncode != 0 or not result.stdout.strip():
        return FALLBACK_RESPONSE

    return truncate_output(result.stdout.strip())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate agent-voice dialog response")
    parser.add_argument("--state", required=True, help="CfA state name")
    parser.add_argument("--question", required=True,
                        help="Human's question text")
    parser.add_argument("--artifact", default="",
                        help="Path to primary artifact file")
    parser.add_argument("--exec-stream", default="",
                        help="Path to exec stream JSONL file")
    parser.add_argument("--task", default="",
                        help="Original task description")
    parser.add_argument("--dialog-history", default="",
                        help="Prior Q&A turns (HUMAN:/AGENT: lines)")
    args = parser.parse_args()
    print(generate(args.state, args.question, args.artifact,
                   args.exec_stream, args.task, args.dialog_history))
