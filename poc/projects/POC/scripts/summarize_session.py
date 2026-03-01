#!/usr/bin/env python3
"""Extract durable learnings from an agent session stream.

Reads a .exec-stream.jsonl or .intent-stream.jsonl file, extracts the
conversation, and calls claude-haiku to produce structured learning entries.
Appends results to a target markdown file.

Usage:
    summarize_session.py --stream <stream.jsonl> --output <MEMORY.md> [--context <file>...] [--scope <level>]

Scope levels control what kind of learnings are extracted:
    team         — how the team worked (default, used by relay.sh per dispatch)
    team-rollup  — aggregate dispatch learnings into team-level patterns
    session      — team-agnostic coordination learnings (from team MEMORYs)
    project      — project-relevant patterns from accumulated session learnings
    global       — cross-project insights only; excludes domain knowledge
    observations — human-preference signals from the intent stream (primary)
    escalation   — autonomy calibration signals from the intent stream (primary)
    intent-alignment — compare INTENT.md against execution outcomes
"""
import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path


def extract_human_turns(stream_path: str, max_chars: int = 12000) -> str:
    """Extract human-authored text from an intent stream.

    The intent stream records the full multi-agent conversation. Human speech
    appears in two forms:
    1. The initial task prompt injected into the first system/init event's
       surrounding context (captured via the first user-role text block).
    2. Follow-on human replies: type=="user" events whose content contains a
       text block (not a tool_result) with parent_tool_use_id == null.

    Agent-to-agent traffic (Task spawns, tool results, SendMessage) is excluded.
    """
    parts = []
    total = 0
    initial_task_captured = False

    try:
        with open(stream_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ev_type = ev.get("type", "")

                # Capture the initial task from the first user message
                # (type=="user", content is a text block, no parent tool)
                if ev_type == "user" and not initial_task_captured:
                    msg = ev.get("message", {})
                    content = msg.get("content", [])
                    parent = ev.get("parent_tool_use_id")
                    # The very first human text turn has no parent tool and
                    # content is a list with a text block (not a tool_result)
                    if not parent and isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text = block.get("text", "").strip()
                                if text:
                                    parts.append(f"[Human task/input]: {text}")
                                    total += len(text)
                                    initial_task_captured = True
                                    break

                # Capture follow-on human replies (no parent tool, text content)
                elif ev_type == "user" and initial_task_captured:
                    parent = ev.get("parent_tool_use_id")
                    if parent is not None:
                        # Tool result — skip, this is agent-to-agent traffic
                        continue
                    msg = ev.get("message", {})
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text = block.get("text", "").strip()
                                if text:
                                    parts.append(f"[Human]: {text}")
                                    total += len(text)
                                    break
                    elif isinstance(content, str):
                        text = content.strip()
                        if text:
                            parts.append(f"[Human]: {text}")
                            total += len(text)

                if total > max_chars:
                    break

    except FileNotFoundError:
        print(f"[summarize] Stream file not found: {stream_path}", file=sys.stderr)
        return ""

    return "\n\n".join(parts)[:max_chars]


def extract_conversation(stream_path: str, max_chars: int = 10000) -> str:
    """Pull assistant text and tool-use summaries from a stream-json file.

    Used for exec-stream scopes (team, session, project, global,
    intent-alignment). For intent-stream scopes, use extract_human_turns().
    """
    parts = []
    total = 0

    try:
        with open(stream_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ev_type = ev.get("type", "")

                if ev_type == "assistant":
                    content = ev.get("message", {}).get("content", [])
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        bt = block.get("type", "")
                        if bt == "text" and block.get("text", "").strip():
                            parts.append(block["text"])
                            total += len(block["text"])
                        elif bt == "tool_use":
                            name = block.get("name", "")
                            inp = block.get("input", {})
                            # Summarize tool calls concisely
                            if name == "Write":
                                fp = inp.get("file_path", "?")
                                parts.append(f"[Write: {fp}]")
                            elif name == "SendMessage":
                                recip = inp.get("recipient", "?")
                                summary = inp.get("summary", "")
                                parts.append(f"[SendMessage @{recip}: {summary}]")
                            elif name == "Task":
                                desc = inp.get("description", "")
                                agent = inp.get("name", "")
                                parts.append(f"[Task @{agent}: {desc}]")
                            elif name == "Bash":
                                cmd = inp.get("command", "")[:100]
                                parts.append(f"[Bash: {cmd}]")

                if total > max_chars:
                    break
    except FileNotFoundError:
        print(f"[summarize] Stream file not found: {stream_path}", file=sys.stderr)
        return ""

    return "\n".join(parts)[:max_chars]


def read_context_files(paths: list[str]) -> str:
    """Read optional context files (e.g. team MEMORY.md files)."""
    parts = []
    for p in paths:
        path = Path(p)
        if path.is_file() and path.stat().st_size > 0:
            text = path.read_text().strip()
            if text:
                parts.append(f"--- {path.name} ({path.parent.name}) ---\n{text}")
    return "\n\n".join(parts)


# Scope-specific extraction prompts
PROMPTS = {
    "team": """Review this agent team session and extract 3-5 durable learnings.

Only include learnings that are:
- Likely to apply in future sessions (not one-off)
- Actionable (suggest a concrete change in behavior or approach)
- About HOW to work effectively (coordination, tool usage, patterns) not WHAT was produced

If no learnings meet the quality bar, output nothing. Do not explain why or state that there are no learnings. Silence is correct.

Format each learning as:

## [{date}] Session Learning
**Context:** <what we were doing when this came up>
**Learning:** <the specific insight>
**Action:** <what to do differently next time>

{context_section}

Session conversation:
{conversation}
""",

    "team-rollup": """Review the dispatch-level learnings below for a single team across multiple dispatches in one session.

Extract patterns that recur across dispatches:
- Common tool/coordination patterns this team uses
- Recurring problems or workarounds
- Team-specific workflow optimizations

Deduplicate: if multiple dispatches learned the same thing, consolidate into one entry.

If no learnings meet the quality bar, output nothing. Do not explain why or state that there are no learnings. Silence is correct.

Format each learning as:

## [{date}] Team Learning
**Context:** <pattern observed across dispatches>
**Learning:** <the specific insight>
**Action:** <what to do differently next time>

{context_section}

Session conversation:
{conversation}
""",

    "session": """Review the team-level learnings and uber-level coordination below. Extract learnings that are NOT specific to any single team.

Focus on:
- Cross-team coordination patterns that worked or failed
- Delegation strategies (task decomposition, sequencing, parallelism)
- Information flow between teams (what summaries were useful, what was missing)
- Resource allocation decisions

EXCLUDE:
- Anything specific to how one team works internally (that stays at team level)
- Domain-specific content (what was written, drawn, researched)

If no learnings meet the quality bar, output nothing. Do not explain why or state that there are no learnings. Silence is correct.

Format each learning as:

## [{date}] Session Learning
**Context:** <what we were doing when this came up>
**Learning:** <the specific insight>
**Action:** <what to do differently next time>

{context_section}

Session conversation:
{conversation}
""",

    "project": """Review the session learnings below and extract patterns relevant to this project.

Focus on:
- Patterns that will recur in future sessions of this same project
- Project-specific workflow optimizations
- Domain knowledge about this project's subject matter that aids future work
- Team compositions or delegation strategies that worked well for this project

Deduplicate with any existing project learnings in the context.

If no learnings meet the quality bar, output nothing. Do not explain why or state that there are no learnings. Silence is correct.

Format each learning as:

## [{date}] Project Learning
**Context:** <what we were doing when this came up>
**Learning:** <the specific insight>
**Action:** <what to do differently next time>

{context_section}

Session conversation:
{conversation}
""",

    "global": """Review the project learnings below and extract ONLY insights that apply across ALL projects.

This is a strict filter. Only include learnings about:
- General-purpose agent coordination strategies
- Tool usage patterns (relay.sh, plan-execute lifecycle, etc.)
- Process improvements (how to decompose tasks, when to parallelize)
- Communication patterns between team levels

EXCLUDE:
- Any domain-specific knowledge (tea, handbooks, dark energy, etc.)
- Project-specific workflow decisions
- Content-related insights

IMPORTANT: Do NOT reference specific project names in global learnings. Use generic terms ("a previous project", "one session") rather than naming specific projects.

If nothing qualifies as truly cross-project, output nothing.

Format each learning as:

## [{date}] Global Learning
**Context:** <what we were doing when this came up>
**Learning:** <the specific insight>
**Action:** <what to do differently next time>

{context_section}

Session conversation:
{conversation}
""",

    "observations": """You are reading the raw text of what a human typed during an intent-gathering session with an AI agent system. The session was a dialog to clarify and document the human's intent before the agents began work.

Your task: extract ONLY durable, specific human-preference signals from what the human said.

SOURCE: The lines prefixed with [Human task/input] and [Human] are the human's actual words. Everything else is agent output — ignore it for preference extraction.

WHAT COUNTS AS SIGNAL:
- Explicit statements about what the human wants or does not want
- Corrections where the human redirected the agent
- Pushback or disagreement with agent suggestions
- Statements about working style, values, quality bar, autonomy preference
- What the human emphasized or repeated
- Stated vs. revealed divergences (human said X then corrected toward Y)

WHAT DOES NOT COUNT:
- The human simply providing task information or answering agent questions
- The human confirming the agent understood correctly
- Generic approval ("looks good", "yes")
- Task-specific decisions that won't recur (what color to use for this one logo)

QUALITY BAR: Each observation must be specific enough that a new agent with no prior context could apply it immediately. "The human values quality" is too generic. "The human explicitly rejected first-person agent narration in deliverables" is actionable.

If the human's words contain no meaningful preference signal — only task description and factual answers — output nothing. Silence is correct.

Format each observation as:

## [{date}] Observation
**Category:** Values | Preferences | Corrections | Stated vs. Revealed
**Signal:** <the specific preference signal, quoted or paraphrased from the human's words>
**Implication:** <how a future agent should behave differently because of this>

{context_section}

Intent stream (human turns only — read [Human task/input] and [Human] lines):
{conversation}
""",

    "escalation": """You are reading the raw text of what a human typed during an intent-gathering session with an AI agent system.

Your task: extract ONLY signals about where the human wants agents to act autonomously vs. escalate for human input. These are domain-indexed calibration entries.

SOURCE: The lines prefixed with [Human task/input] and [Human] are the human's actual words. Agent output is not relevant here.

WHAT COUNTS AS ESCALATION SIGNAL:
- Explicit statements about agent autonomy ("just do it", "don't ask me about X", "always check before Y")
- Statements revealing risk tolerance for specific decision types
- Statements about what would make the human want to stop and review
- Corrections that reveal the agent misjudged the autonomy threshold (acted when it should have asked, or asked when it should have acted)
- Statements about cost or irreversibility thresholds

WHAT DOES NOT COUNT:
- Generic task delegation ("go ahead and build this")
- Approval of a plan that was explicitly presented for approval
- Task-specific decisions with no recurrence value

If the human's words contain no autonomy-calibration signal, output nothing. Do not invent escalation entries from generic approval.

Each entry must name a DOMAIN (the specific area of work this calibration applies to), a DIRECTION (more autonomous or more escalation), and cite the SPECIFIC SIGNAL.

Format each observation as:

## [{date}] Escalation Calibration
**Domain:** <specific area — e.g., file naming conventions, architecture decisions, cost decisions, API key selection>
**Direction:** More autonomous | Escalate more
**Signal:** <what the human said that produced this calibration>
**Threshold:** <what would trigger escalation in this domain going forward>

{context_section}

Intent stream (human turns only — read [Human task/input] and [Human] lines):
{conversation}
""",

    "intent-alignment": """Compare the intent specification (in context below) against the work that was done (in the conversation).

Extract observations about how well the executed work aligned with the stated intent:
- Which success criteria were addressed by the deliverables?
- Which success criteria were NOT addressed or only partially addressed?
- Where did agents deviate from the intent's decision boundaries?
- What corrections during execution reveal gaps in the intent specification?
- What preferences were revealed that the intent did not capture?

Focus on actionable observations that improve future intent gathering.

Format each observation as:

## [{date}] Alignment Observation
**Category:** Success Criteria Met | Success Criteria Missed | Boundary Deviation | Intent Gap
**Signal:** <what was observed>
**Implication:** <what to ask about or capture in the next intent gathering session>

{context_section}

Session conversation:
{conversation}
""",
}

# These scopes use the intent stream and need human-turn extraction
INTENT_STREAM_SCOPES = {"observations", "escalation"}


def summarize(stream_path: str, output_path: str, context_files: list[str], scope: str):
    """Extract learnings and append to the target file."""
    # Use the correct extraction function for the scope
    if scope in INTENT_STREAM_SCOPES:
        conversation = extract_human_turns(stream_path)
    else:
        conversation = extract_conversation(stream_path)

    context = read_context_files(context_files)

    # For project and global scopes, context is the primary source (stream may be empty)
    if not conversation.strip() and not context.strip():
        print("[summarize] No conversation or context content found, skipping.", file=sys.stderr)
        return 1

    # For intent-stream scopes: if no human turns were found, skip — silence is correct
    if scope in INTENT_STREAM_SCOPES and not conversation.strip():
        print(f"[summarize] No human turns found in intent stream for {scope}, skipping.", file=sys.stderr)
        return 0

    context_section = ""
    if context:
        context_section = f"Additional context (accumulated learnings):\n{context}\n"

    today = date.today().isoformat()
    prompt_template = PROMPTS.get(scope, PROMPTS["team"])
    prompt = prompt_template.format(
        date=today,
        conversation=conversation if conversation.strip() else "(no stream conversation available — use context above)",
        context_section=context_section,
    )

    print(f"[summarize] Extracting {scope}-level learnings from {stream_path}...", file=sys.stderr)

    try:
        result = subprocess.run(
            [
                "claude",
                "-p",
                "--model", "claude-haiku-4-5",
                "--max-turns", "2",
                "--output-format", "text",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        print("[summarize] claude CLI not found, skipping.", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print("[summarize] claude call timed out, skipping.", file=sys.stderr)
        return 1

    if result.returncode != 0 or not result.stdout.strip():
        print(f"[summarize] claude returned {result.returncode}", file=sys.stderr)
        if result.stderr:
            print(f"[summarize] stderr: {result.stderr[:200]}", file=sys.stderr)
        return 1

    learnings = result.stdout.strip()

    # Filter out claude CLI error messages that leak into stdout
    if learnings.startswith("Error: Reached max turns"):
        print(f"[summarize] Claude hit max turns, skipping.", file=sys.stderr)
        return 1

    # Reject outputs that contain no properly-formatted entries.
    # A valid learning entry must start with "## [". Pure prose output
    # (meta-commentary, explanations of why nothing qualifies) must be
    # discarded and must never be persisted to memory files.
    if learnings and not any(line.strip().startswith("## [") for line in learnings.splitlines()):
        print(f"[summarize] No formatted entries found in output (meta-commentary?), skipping.", file=sys.stderr)
        return 0

    # If haiku produced nothing (silence is valid for intent-stream scopes), skip
    if not learnings:
        print(f"[summarize] No {scope} entries extracted (correct if no signal present).", file=sys.stderr)
        return 0

    # Append to output file
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with open(output, "a") as f:
        f.write("\n\n" + learnings + "\n")

    print(f"[summarize] Appended {scope}-level learnings to {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract session learnings")
    parser.add_argument("--stream", required=True, help="Path to .exec-stream.jsonl or .intent-stream.jsonl")
    parser.add_argument("--output", required=True, help="Path to target markdown file")
    parser.add_argument("--context", nargs="*", default=[], help="Additional context files")
    parser.add_argument("--scope", default="team",
                        choices=["team", "team-rollup", "session", "project", "global",
                                 "observations", "escalation", "intent-alignment"],
                        help="Extraction scope")
    args = parser.parse_args()

    sys.exit(summarize(args.stream, args.output, args.context, args.scope))
