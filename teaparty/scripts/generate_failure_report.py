#!/usr/bin/env python3
"""Generate a structured failure report for CfA orchestration failures.

Reads session artifacts (stream JSONL, session.log, CfA state, sentinels)
and produces .failure-report.md with evidence pointers rather than embedded
error dumps.  Every evidence item is a file path + line number + short label.
The report never embeds log blocks or stream JSON.

Usage:
    generate_failure_report.py \
        --session-dir <path> --stream <path> --phase <phase> \
        --agent <name> --exit-code <N> --task "<text>" \
        [--agents-file <path>] [--workdir <path>] \
        [--add-dirs <p1,p2>] [--permission-mode <mode>] \
        [--output <path>]
"""
import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Evidence pointer ────────────────────────────────────────────────────────

@dataclass
class EvidencePointer:
    """A reference to a specific location in a session artifact."""
    file: str          # relative to session dir
    line: Optional[int] = None   # 1-indexed, or None for existence-only
    line_end: Optional[int] = None  # end of range, or None for single line
    label: str = ""    # ≤60 chars: identifies WHICH error, not WHAT it said


# ── Stream scanning ─────────────────────────────────────────────────────────

def _scan_stream(stream_path: Path) -> tuple[list[EvidencePointer], str]:
    """Scan stream JSONL for error events.

    Returns (pointers, failure_type_hint) where failure_type_hint is
    'permission' if permission-related errors dominate, else ''.
    """
    pointers = []
    perm_count = 0
    total_errors = 0
    rel = stream_path.name

    if not stream_path.exists() or stream_path.stat().st_size == 0:
        return [], ""

    with open(stream_path) as f:
        for line_num, raw in enumerate(f, 1):
            try:
                ev = json.loads(raw.strip())
            except (json.JSONDecodeError, ValueError):
                continue

            # Tool result errors (permission denials, hook blocks)
            if ev.get("type") == "user":
                for block in ev.get("message", {}).get("content", []):
                    if not isinstance(block, dict) or not block.get("is_error"):
                        continue
                    text = block.get("text", "") or block.get("content", "")
                    total_errors += 1
                    is_perm = any(kw in text.lower() for kw in
                                  ("denied", "requires approval", "not allowed",
                                   "permission", "blocked"))
                    if is_perm:
                        perm_count += 1
                    label = _make_label(text, is_perm)
                    tool_id = block.get("tool_use_id", "")
                    if tool_id:
                        label = f"{label} ({tool_id[:16]})"
                    pointers.append(EvidencePointer(rel, line_num, label=label))

            # Final result with error
            if ev.get("type") == "result" and ev.get("is_error"):
                text = ev.get("error", "result error")
                pointers.append(EvidencePointer(
                    rel, line_num, label=_make_label(text, False)))

    # Select at most 5: first, last, and up to 3 most recent between
    selected = _select_pointers(pointers, max_count=5)
    hint = "permission" if perm_count > 0 and perm_count >= total_errors // 2 else ""
    return selected, hint


def _make_label(text: str, is_perm: bool) -> str:
    """Produce a ≤60-char label identifying which error, not what it said."""
    text = text.strip().replace("\n", " ")
    if is_perm:
        # Extract the tool name if present
        for prefix in ("Write blocked:", "Edit blocked:", "Bash blocked:"):
            if prefix.lower() in text.lower():
                return f"permission denied: {prefix.split(':')[0]}"
        return "permission denied"
    if len(text) <= 60:
        return text
    return text[:57] + "..."


def _select_pointers(
    pointers: list[EvidencePointer], max_count: int = 5
) -> list[EvidencePointer]:
    """Select first, last, and up to (max_count-2) most recent between."""
    if len(pointers) <= max_count:
        return pointers
    first = pointers[0]
    last = pointers[-1]
    middle = pointers[-(max_count - 1):-1]
    return [first] + middle + [last]


# ── Session log scanning ────────────────────────────────────────────────────

_FAILURE_KEYWORDS = frozenset(
    ("failure", "failed", "error", "blocked", "withdrawn", "backtrack",
     "denied", "infrastructure", "permission", "TASK_ESCALATE"))


def _scan_session_log(session_dir: Path) -> Optional[EvidencePointer]:
    """Find the line range of failure-related STATE entries in session.log."""
    log_path = session_dir / "session.log"
    if not log_path.exists():
        return None

    failure_lines = []
    with open(log_path) as f:
        for line_num, raw in enumerate(f, 1):
            lower = raw.lower()
            if any(kw in lower for kw in _FAILURE_KEYWORDS):
                failure_lines.append(line_num)

    if not failure_lines:
        return None

    # Cluster: take last contiguous group (within 5 lines of each other)
    groups = []
    current = [failure_lines[0]]
    for ln in failure_lines[1:]:
        if ln - current[-1] <= 5:
            current.append(ln)
        else:
            groups.append(current)
            current = [ln]
    groups.append(current)

    last_group = groups[-1]
    start, end = last_group[0], last_group[-1]
    return EvidencePointer("session.log", start, end)


# ── Sentinel and state files ────────────────────────────────────────────────

def _check_sentinels(session_dir: Path) -> dict[str, Optional[str]]:
    """Check for sentinel/state files.  Returns {filename: brief_note_or_None}."""
    sentinels = {}

    fr = session_dir / ".failure-reason"
    if fr.exists():
        try:
            reason = fr.read_text().strip().split("\n")[0][:80]
        except Exception:
            reason = "exists"
        sentinels[".failure-reason"] = reason

    for name in (".task-escalation.md", ".backtrack-feedback.txt",
                 ".plan-escalation.md", ".intent-escalation.md"):
        p = session_dir / name
        if p.exists():
            sentinels[name] = None  # existence only

    return sentinels


def _read_cfa_state(session_dir: Path) -> str:
    """Read current CfA state from .cfa-state.json, or return 'unknown'."""
    state_file = session_dir / ".cfa-state.json"
    if not state_file.exists():
        return "unknown"
    try:
        data = json.loads(state_file.read_text())
        return data.get("state", "unknown")
    except Exception:
        return "unknown"


# ── Subteam result scanning ─────────────────────────────────────────────────

def _scan_subteam_results(session_dir: Path) -> list[EvidencePointer]:
    """Find failed subteam .result.json files."""
    pointers = []
    for result_file in session_dir.rglob(".result.json"):
        try:
            data = json.loads(result_file.read_text())
        except Exception:
            continue
        exit_code = data.get("exit_code", 0)
        status = data.get("status", "")
        if exit_code != 0 or status in ("failed", "infrastructure_failure",
                                         "backtrack_intent", "backtrack_planning"):
            rel = str(result_file.relative_to(session_dir))
            label = f"exit={exit_code} status={status}"
            pointers.append(EvidencePointer(rel, label=label))
    return pointers


# ── Failure classification ───────────────────────────────────────────────────

def _classify_failure(
    exit_code: int,
    sentinels: dict,
    stream_hint: str,
    subteam_failures: list,
) -> str:
    """Infer failure type from available evidence."""
    if ".failure-reason" in sentinels:
        return "stall"
    if stream_hint == "permission":
        return "permission"
    if subteam_failures:
        return "subteam"
    return "infrastructure"


# ── Structural analysis (canned prose) ───────────────────────────────────────

_ANALYSES: dict[tuple[str, str], str] = {
    ("permission", "planning"): (
        "The agent could not read files or write artifacts needed to produce "
        "a trustworthy plan.  Planning without access to the relevant "
        "specifications produces plans that cannot be evaluated."
    ),
    ("permission", "execution"): (
        "The permission model and the approved plan disagree.  The plan was "
        "approved by the human, but the execution environment blocked "
        "commands the plan required."
    ),
    ("permission", "intent"): (
        "The intent agent could not read files referenced in the task.  "
        "An intent document produced without reading the source material "
        "cannot accurately represent what the human wants."
    ),
    ("stall", "execution"): (
        "The agent entered a state with no productive action for an extended "
        "period.  This typically means an unresolvable permission loop or "
        "a tool that blocked indefinitely."
    ),
    ("stall", "planning"): (
        "The planning agent stalled — no output for an extended period.  "
        "The agent may have been waiting for a tool response that never came "
        "or looping without making progress."
    ),
    ("stall", "intent"): (
        "The intent agent stalled before producing INTENT.md.  Without an "
        "approved intent, the session cannot proceed to planning."
    ),
    ("infrastructure", "intent"): (
        "The intent agent crashed before producing INTENT.md.  Without an "
        "approved intent, the session cannot proceed."
    ),
    ("infrastructure", "planning"): (
        "The planning agent crashed before completing a plan.  The session "
        "cannot proceed to execution without an approved plan."
    ),
    ("infrastructure", "execution"): (
        "The execution agent crashed during work.  Partial output may exist "
        "in the worktree."
    ),
    ("subteam", "execution"): (
        "A delegated subteam failed.  The execution lead dispatched work to "
        "a team that could not complete it.  The subteam's .result.json and "
        "stream files contain the detailed failure."
    ),
}


def _get_analysis(failure_type: str, phase: str) -> str:
    text = _ANALYSES.get((failure_type, phase))
    if text:
        return text
    return "See evidence pointers above."


# ── One-line summary generation ──────────────────────────────────────────────

_SUMMARIES: dict[tuple[str, str], str] = {
    ("permission", "planning"):    "planning blocked by permission restrictions",
    ("permission", "execution"):   "execution blocked by permission restrictions",
    ("permission", "intent"):      "intent agent blocked by permission restrictions",
    ("stall", "planning"):         "planning agent stalled",
    ("stall", "execution"):        "execution agent stalled",
    ("stall", "intent"):           "intent agent stalled",
    ("infrastructure", "intent"):  "intent agent crashed",
    ("infrastructure", "planning"): "planning agent crashed",
    ("infrastructure", "execution"): "execution agent crashed",
    ("subteam", "execution"):      "subteam dispatch failed",
}


def _get_summary(failure_type: str, phase: str, agent: str) -> str:
    base = _SUMMARIES.get((failure_type, phase),
                          f"{phase} failed ({failure_type})")
    return f"{base} — {agent}"


# ── Open questions generation ────────────────────────────────────────────────

_QUESTIONS: dict[str, list[str]] = {
    "permission": [
        "Which specific tool or path was denied, and is the restriction "
        "intentional or a configuration gap?",
        "Does the permissions.allow list in the settings file include the "
        "tools this phase needs?",
    ],
    "stall": [
        "What was the last tool invocation before the stall?  Was it "
        "waiting for a response or looping?",
        "Is the stall timeout (default 1800s) appropriate for the "
        "kind of work this agent was doing?",
    ],
    "infrastructure": [
        "Is the exit code from a signal (OOM, kill) or an application error?",
        "Did the agent produce any partial output before crashing?",
    ],
    "subteam": [
        "Which subteam failed, and did it exhaust its retry budget?",
        "Is the subteam failure an independent problem or downstream "
        "of a shared infrastructure issue (permissions, connectivity)?",
    ],
}


# ── Report rendering ─────────────────────────────────────────────────────────

def _render_report(
    summary: str,
    phase: str,
    agent: str,
    exit_code: int,
    cfa_state: str,
    session_basename: str,
    what_failed: str,
    evidence: list[EvidencePointer],
    sentinel_evidence: dict[str, Optional[str]],
    subteam_evidence: list[EvidencePointer],
    task: str,
    agents_file: str,
    workdir: str,
    add_dirs: str,
    permission_mode: str,
    analysis: str,
    questions: list[str],
) -> str:
    lines = []

    # Header
    lines.append(f"# Failure: {summary}")
    lines.append("")
    lines.append(
        f"Phase: {phase} | Agent: {agent} | Exit: {exit_code} "
        f"| State: {cfa_state}")
    lines.append(f"Session: {session_basename}")
    lines.append(
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    lines.append("")

    # What Failed
    lines.append("## What Failed")
    lines.append("")
    lines.append(what_failed)
    lines.append("")

    # Evidence
    lines.append("## Evidence")
    lines.append("")
    if not evidence and not sentinel_evidence and not subteam_evidence:
        lines.append("No evidence artifacts found.")
    else:
        for ep in evidence:
            if ep.line and ep.line_end:
                lines.append(f"- `{ep.file}` lines {ep.line}–{ep.line_end}")
            elif ep.line:
                loc = f"line {ep.line}"
                if ep.label:
                    lines.append(f"- `{ep.file}` {loc} — {ep.label}")
                else:
                    lines.append(f"- `{ep.file}` {loc}")
            elif ep.label:
                lines.append(f"- `{ep.file}` — {ep.label}")
            else:
                lines.append(f"- `{ep.file}` exists")

        for name, note in sentinel_evidence.items():
            if note:
                lines.append(f"- `{name}` — {note}")
            else:
                lines.append(f"- `{name}` exists")

        for ep in subteam_evidence:
            lines.append(f"- `{ep.file}` — {ep.label}")
    lines.append("")

    # Reproduction
    lines.append("## Reproduction")
    lines.append("")
    task_display = task[:500]
    if len(task) > 500:
        task_display += "..."
    lines.append(f'Task: "{task_display}"')
    lines.append("Command context:")
    if agents_file:
        lines.append(f"  agent_config: {agents_file} → {agent}")
    if permission_mode:
        lines.append(f"  permission_mode: {permission_mode}")
    if workdir:
        lines.append(f"  workdir: {workdir}")
    if add_dirs:
        lines.append(f"  add_dirs: {add_dirs}")
    lines.append("")

    # What This Reveals
    lines.append("## What This Reveals")
    lines.append("")
    lines.append(analysis)
    lines.append("")

    # Open Questions
    lines.append("## Open Questions")
    lines.append("")
    for q in questions:
        lines.append(f"- {q}")
    if not questions:
        lines.append("None identified from available evidence.")
    lines.append("")

    return "\n".join(lines)


# ── "What Failed" prose generation ───────────────────────────────────────────

def _compose_what_failed(
    failure_type: str,
    phase: str,
    agent: str,
    exit_code: int,
    stream_pointers: list[EvidencePointer],
    sentinels: dict,
) -> str:
    """Compose 2-3 sentences describing what happened at human-concern level."""
    parts = []

    phase_verb = {
        "intent": "gathering intent",
        "planning": "planning",
        "execution": "executing the approved plan",
    }.get(phase, phase)

    if failure_type == "permission":
        n = len(stream_pointers)
        parts.append(
            f"The {agent} agent was {phase_verb} when it hit permission "
            f"restrictions ({n} denial{'s' if n != 1 else ''} in the stream).")
        parts.append(
            "The agent could not complete its work because the execution "
            "environment blocked required operations.")
    elif failure_type == "stall":
        reason = sentinels.get(".failure-reason", "extended inactivity")
        parts.append(
            f"The {agent} agent stalled during {phase_verb}: {reason}.")
        parts.append("No forward progress was detected before the watchdog "
                      "terminated the process.")
    elif failure_type == "subteam":
        parts.append(
            f"The {agent} agent was {phase_verb} and delegated work to a "
            f"subteam that failed.")
    else:
        parts.append(
            f"The {agent} agent crashed during {phase_verb} "
            f"(exit code {exit_code}).")
        if not stream_pointers:
            parts.append("The process produced no error output before exiting.")
        else:
            parts.append(
                f"The stream contains {len(stream_pointers)} error "
                f"event{'s' if len(stream_pointers) != 1 else ''} "
                f"before the crash.")

    return "  ".join(parts)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate structured failure report for CfA failures.")
    parser.add_argument("--session-dir", required=True,
                        help="Session infra directory")
    parser.add_argument("--stream", required=True,
                        help="Path to the stream JSONL that failed")
    parser.add_argument("--phase", required=True,
                        choices=["intent", "planning", "execution"])
    parser.add_argument("--agent", required=True,
                        help="Agent name that was running")
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--task", required=True,
                        help="Original task text")
    parser.add_argument("--agents-file", default="",
                        help="Path to agents JSON (for repro context)")
    parser.add_argument("--workdir", default="",
                        help="Agent working directory")
    parser.add_argument("--add-dirs", default="",
                        help="Comma-separated --add-dir paths")
    parser.add_argument("--permission-mode", default="",
                        help="Permission mode (plan, acceptEdits, default)")
    parser.add_argument("--output", default="",
                        help="Output path (default: <session-dir>/.failure-report.md)")

    args = parser.parse_args()
    session_dir = Path(args.session_dir)
    stream_path = Path(args.stream)
    output_path = Path(args.output) if args.output else session_dir / ".failure-report.md"

    # Gather evidence
    stream_pointers, stream_hint = _scan_stream(stream_path)
    log_pointer = _scan_session_log(session_dir)
    sentinels = _check_sentinels(session_dir)
    cfa_state = _read_cfa_state(session_dir)
    subteam_pointers = (_scan_subteam_results(session_dir)
                        if args.phase == "execution" else [])

    # Classify
    failure_type = _classify_failure(
        args.exit_code, sentinels, stream_hint, subteam_pointers)

    # Assemble evidence list
    all_evidence: list[EvidencePointer] = []
    if log_pointer:
        all_evidence.append(log_pointer)
    all_evidence.extend(stream_pointers)

    # Compose sections
    summary = _get_summary(failure_type, args.phase, args.agent)
    what_failed = _compose_what_failed(
        failure_type, args.phase, args.agent, args.exit_code,
        stream_pointers, sentinels)
    analysis = _get_analysis(failure_type, args.phase)
    questions = _QUESTIONS.get(failure_type, [])

    # Render
    report = _render_report(
        summary=summary,
        phase=args.phase,
        agent=args.agent,
        exit_code=args.exit_code,
        cfa_state=cfa_state,
        session_basename=session_dir.name,
        what_failed=what_failed,
        evidence=all_evidence,
        sentinel_evidence=sentinels,
        subteam_evidence=subteam_pointers,
        task=args.task,
        agents_file=args.agents_file,
        workdir=args.workdir,
        add_dirs=args.add_dirs,
        permission_mode=args.permission_mode,
        analysis=analysis,
        questions=questions,
    )

    output_path.write_text(report)


if __name__ == "__main__":
    main()
