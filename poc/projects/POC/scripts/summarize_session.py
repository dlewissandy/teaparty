#!/usr/bin/env python3
"""Extract durable learnings from an agent session stream.

Reads a .exec-stream.jsonl file, extracts the conversation, and calls
claude-haiku to produce structured learning entries. Appends results
to a target MEMORY.md file.

Usage:
    summarize_session.py --stream <stream.jsonl> --output <MEMORY.md> [--context <file>...] [--scope <level>]

Scope levels control what kind of learnings are extracted:
    team         — how the team worked (default, used by relay.sh per dispatch)
    team-rollup  — aggregate dispatch learnings into team-level patterns
    session      — team-agnostic coordination learnings (from team MEMORYs)
    project      — project-relevant patterns from accumulated session learnings
    global       — cross-project insights only; excludes domain knowledge
"""
import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path


def extract_conversation(stream_path: str, max_chars: int = 10000) -> str:
    """Pull assistant text and tool-use summaries from a stream-json file."""
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

    "observations": """Review this conversation and extract observations about the human's preferences, values, and working style.

Focus on:
- Explicit preference statements ("I want X", "I prefer Y over Z")
- Implicit value signals (what the human emphasized, repeated, or pushed back on)
- Corrections that reveal preferences (human changed the agent's understanding)
- Stated vs. revealed preference divergences (human says one thing but corrects toward another)

Only include observations that are durable (likely to apply in future sessions).

Format each observation as:

## [{date}] Observation
**Category:** Values | Preferences | Corrections | Stated vs. Revealed
**Signal:** <what was observed>
**Implication:** <what this means for future intent gathering>

{context_section}

Session conversation:
{conversation}
""",

    "escalation": """Review this conversation and extract escalation-relevant observations.

Focus on:
- Explicit preferences about where agents should use their own judgment vs. stop and consult the human
- Decisions about risk tolerance for specific domains or decision types
- Autonomous actions that were accepted (calibrate toward autonomy) or corrected (calibrate toward escalation)
- Statements like "you should have just done that" (threshold too high) or corrections after autonomous action (threshold too low)

Format each observation as:

## [{date}] Escalation Observation
**Domain:** <what area this applies to (e.g., code style, factual claims, design choices)>
**Signal:** <what was observed>
**Calibration:** <should agents escalate more or less in this domain?>

{context_section}

Session conversation:
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


def summarize(stream_path: str, output_path: str, context_files: list[str], scope: str):
    """Extract learnings and append to MEMORY.md."""
    conversation = extract_conversation(stream_path)
    context = read_context_files(context_files)

    # For project and global scopes, context is the primary source (stream may be empty)
    if not conversation.strip() and not context.strip():
        print("[summarize] No conversation or context content found, skipping.", file=sys.stderr)
        return 1

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
                "--max-turns", "1",
                "--output-format", "text",
                "--tools", "",
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

    # Append to MEMORY.md
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with open(output, "a") as f:
        f.write("\n\n" + learnings + "\n")

    print(f"[summarize] Appended {scope}-level learnings to {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract session learnings")
    parser.add_argument("--stream", required=True, help="Path to .exec-stream.jsonl")
    parser.add_argument("--output", required=True, help="Path to target MEMORY.md")
    parser.add_argument("--context", nargs="*", default=[], help="Additional context files")
    parser.add_argument("--scope", default="team",
                        choices=["team", "team-rollup", "session", "project", "global",
                                 "observations", "escalation", "intent-alignment"],
                        help="Extraction scope (team, team-rollup, session, project, global, "
                             "observations, escalation, intent-alignment)")
    args = parser.parse_args()

    sys.exit(summarize(args.stream, args.output, args.context, args.scope))
