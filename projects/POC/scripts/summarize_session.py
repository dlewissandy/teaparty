#!/usr/bin/env python3
"""Extract durable learnings from an agent session stream.

Reads a .exec-stream.jsonl or .intent-stream.jsonl file, extracts the
conversation, and calls claude-haiku to produce structured learning entries.
Appends results to a target markdown file.

Usage:
    summarize_session.py --stream <stream.jsonl> --output <MEMORY.md> [--context <file>...] [--scope <level>]

Scope levels control what kind of learnings are extracted:
    team         — how the team worked (default, used by dispatch.sh per dispatch)
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
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

# ── Memory entry wrapping (Phase 1 integration) ───────────────────────────────
# Importance by scope — Section 8 confidence schedule:
#   corrective: 0.8  (direct evidence of model error)
#   observations/escalation: 0.95  (explicitly human-stated)
#   all others: 0.5  (single observation, unconfirmed)
_SCOPE_IMPORTANCE = {
    "team": 0.5,
    "team-rollup": 0.5,
    "team-rollup-institutional": 0.5,
    "team-rollup-tasks": 0.5,
    "session": 0.5,
    "session-institutional": 0.5,
    "session-tasks": 0.5,
    "project": 0.5,
    "project-institutional": 0.5,
    "project-tasks": 0.5,
    "global": 0.5,
    "global-institutional": 0.5,
    "global-tasks": 0.5,
    "observations": 0.95,
    "escalation": 0.95,
    "intent-alignment": 0.5,
    "prospective": 0.5,
    "in-flight": 0.5,
    "corrective": 0.8,
}

# Domain by scope — 'team' for coordination learnings, 'task' for project-specific
_SCOPE_DOMAIN = {
    "team": "team",
    "team-rollup": "team",
    "team-rollup-institutional": "team",
    "team-rollup-tasks": "team",
    "session": "team",
    "session-institutional": "team",
    "session-tasks": "team",
    "global": "team",
    "global-institutional": "team",
    "global-tasks": "team",
    "project": "task",
    "project-institutional": "task",
    "project-tasks": "task",
    "observations": "task",
    "escalation": "task",
    "intent-alignment": "task",
    "prospective": "task",
    "in-flight": "task",
    "corrective": "task",
}


def _wrap_learnings_with_frontmatter(
    learnings: str,
    scope: str,
    phase: str = "unknown",
    domain: str = None,
) -> str:
    """Wrap each '## [' entry block in YAML frontmatter.

    Falls back to returning learnings unchanged if memory_entry import fails.
    The '## [date] Learning' header is preserved inside the content field.
    Includes session_id and session_task from environment when available,
    so entries are structurally tied to their originating session.
    """
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _sys.path.insert(0, str(_Path(__file__).parent))
        from memory_entry import make_entry, serialize_entry
    except ImportError:
        return learnings  # graceful degradation

    importance = _SCOPE_IMPORTANCE.get(scope, 0.5)
    effective_domain = domain or _SCOPE_DOMAIN.get(scope, "team")

    # Extract session context from environment for provenance tracking
    session_dir = os.environ.get("POC_SESSION_DIR", "")
    session_id = ""
    if session_dir:
        session_id = "session-" + os.path.basename(session_dir)
    # First line of original task (before intent/posture prepending)
    session_task = ""
    original_task = os.environ.get("ORIGINAL_TASK", "")
    if not original_task:
        # Fallback: check if task was passed; take first meaningful line
        original_task = os.environ.get("POC_TASK", "")
    if original_task:
        session_task = original_task.split("\n")[0].strip()[:200]

    # Split on '## [' boundaries to get individual entry blocks
    import re as _re
    parts = _re.split(r'(?=## \[)', learnings)

    wrapped_parts = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        try:
            entry = make_entry(
                content=part,
                type="procedural",
                domain=effective_domain,
                importance=importance,
                phase=phase,
                session_id=session_id,
                session_task=session_task,
            )
            wrapped_parts.append(serialize_entry(entry))
        except Exception:
            wrapped_parts.append(part)  # fallback: keep raw

    return "\n\n".join(wrapped_parts) if wrapped_parts else learnings


def extract_human_turns(stream_path: str, max_chars: int = 12000) -> str:
    """Extract human-authored text from an intent stream.

    The intent stream records the full multi-agent conversation. In practice,
    ALL user events in the stream contain tool_result blocks — human approvals,
    corrections, and instructions arrive this way. Text blocks (type=="text")
    are rare or absent.

    Human-authored content is distinguished from agent-to-agent traffic by:
    1. Event-level parent_tool_use_id is None (not a sub-agent response).
    2. Content is short — human approvals ("approve"), corrections, and
       instructions are typically under 500 chars. File reads, command output,
       and other agent traffic is much longer.

    Agent-to-agent traffic (parent_tool_use_id set) is excluded entirely.
    """
    # Threshold: tool_result content longer than this is likely agent traffic
    # (file reads, command output, etc.), not human-authored text.
    HUMAN_CONTENT_MAX_LEN = 500

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

                if ev_type != "user":
                    continue

                parent = ev.get("parent_tool_use_id")
                if parent is not None:
                    # Sub-agent response — skip
                    continue

                msg = ev.get("message", {})
                content = msg.get("content", [])
                if isinstance(content, str):
                    text = content.strip()
                    if text:
                        label = "[Human task/input]" if not initial_task_captured else "[Human]"
                        parts.append(f"{label}: {text}")
                        total += len(text)
                        initial_task_captured = True
                elif isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        block_type = block.get("type", "")

                        if block_type == "text":
                            text = block.get("text", "").strip()
                            if text:
                                label = "[Human task/input]" if not initial_task_captured else "[Human]"
                                parts.append(f"{label}: {text}")
                                total += len(text)
                                initial_task_captured = True
                                break

                        elif block_type == "tool_result":
                            text = block.get("content", "")
                            if isinstance(text, str):
                                text = text.strip()
                            else:
                                # Content can be a list of blocks (e.g. images) — skip
                                continue
                            if text and len(text) <= HUMAN_CONTENT_MAX_LEN:
                                label = "[Human task/input]" if not initial_task_captured else "[Human]"
                                parts.append(f"{label}: {text}")
                                total += len(text)
                                initial_task_captured = True
                                break

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
    """Read optional context files (e.g. team MEMORY.md files or .jsonl checkpoints)."""
    parts = []
    for p in paths:
        path = Path(p)
        if path.is_file() and path.stat().st_size > 0:
            text = path.read_text().strip()
            if text:
                if path.suffix == '.jsonl':
                    parts.append(f"--- {path.name} (checkpoint records) ---\n{text}")
                else:
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
- Tool usage patterns (dispatch.sh, plan-execute lifecycle, etc.)
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

    "prospective": """You are reading a pre-mortem risk assessment written BEFORE a task began, alongside the execution stream that followed.

Extract learnings about predictive accuracy and risk identification quality.

FOCUS ON:
- Risks correctly identified in the pre-mortem that actually materialized — and how they were handled
- Risks that materialized but were NOT identified in the pre-mortem (missed risks)
- Risks identified but that did NOT materialize (false alarms)
- Whether the pre-mortem process added value to execution planning

QUALITY BAR: Only extract learnings likely to improve future pre-mortems for similar tasks. Do not extract one-off environmental accidents.

If no signal meets the quality bar, output nothing. Silence is correct.

Format each learning as:

## [{date}] Prospective Learning
**Pre-mortem Risk:** <the risk that was or wasn't identified>
**Outcome:** Materialized | Did not materialize | Not anticipated
**Learning:** <what this tells us about pre-mortem quality or risk identification>
**Action:** <how to improve pre-mortem assessments for similar tasks>

{context_section}

Pre-mortem and execution stream:
{conversation}
""",

    "in-flight": """You are reading milestone assumption checkpoint records (JSONL format) alongside the execution stream.

Each checkpoint record has this shape:
{{"milestone": "...", "timestamp": "...", "assumptions": {{"complexity": "...", "approach_viability": "...", "preference_model": "...", "scope": "..."}}, "recommendation": "..."}}

Extract durable learnings about how assumptions evolved during execution.

FOCUS ON:
- Which assumption types (complexity, approach viability, preference model, scope) were most often wrong
- Whether checkpoint recommendations (continue/notify/escalate) were appropriate
- Patterns in scope expansion or contraction
- Whether mandatory trigger conditions (2x time overrun, 20% scope expansion) fired appropriately

If no patterns meet the quality bar, output nothing. Silence is correct.

Format each learning as:

## [{date}] In-Flight Learning
**Assumption Type:** Complexity | Approach Viability | Preference Model | Scope
**Pattern:** <what was consistently over/underestimated>
**Learning:** <the specific calibration insight>
**Action:** <how to improve planning estimates or checkpoint triggers>

{context_section}

Checkpoint records and execution stream:
{conversation}
""",

    "corrective": """You are reading an execution stream. Extract learnings from errors, retries, corrections, and recoveries.

LOOK FOR:
- Tool call failures and how the agent recovered
- Assumptions that had to be corrected mid-execution
- Cases where the agent undid work and redid it
- Explicit error messages in bash tool outputs
- Agent narration of mistakes ("I tried X but it failed because Y")
- Retries that succeeded or failed

QUALITY BAR: Only extract corrections likely to recur in future sessions. One-off environment errors (network timeout, missing file) do not qualify. Systematic mistakes in approach, tool usage, or sequencing do qualify.

If no qualifying errors are present, output nothing. Silence is correct.

Format each learning as:

## [{date}] Corrective Learning
**Error Pattern:** <what went wrong>
**Recovery:** <how it was fixed>
**Root Cause:** <why it happened>
**Prevention:** <how to avoid this in future sessions>

{context_section}

Execution stream:
{conversation}
""",

    # ── Typed-store variants (institutional vs. task-based) ───────────────────

    "team-rollup-institutional": """Review the dispatch-level learnings for a single team.

Extract ONLY stable coordination NORMS: how this team organizes its work, consistent patterns of tool use, structural conventions that hold across dispatches.

Do NOT extract task procedures, one-off decisions, or debugging steps.

If no durable norms are present, output nothing. Silence is correct.

Format each norm as:

## [{date}] Team Norm
**Pattern:** <the stable norm or convention>
**Why it holds:** <why this is durable, not just session-specific>

{context_section}

Session conversation:
{conversation}
""",

    "team-rollup-tasks": """Review the dispatch-level learnings for a single team across multiple dispatches.

Extract patterns that recur across dispatches:
- Common tool/coordination patterns this team uses
- Recurring problems or workarounds
- Team-specific workflow optimizations

Deduplicate: if multiple dispatches learned the same thing, consolidate into one entry.

If no learnings meet the quality bar, output nothing. Silence is correct.

Format each learning as:

## [{date}] Team Learning
**Context:** <pattern observed across dispatches>
**Learning:** <the specific insight>
**Action:** <what to do differently next time>

{context_section}

Session conversation:
{conversation}
""",

    "session-institutional": """Review the team-level learnings from this session.

Extract ONLY cross-team coordination NORMS: structural conventions governing how teams hand off work, sequencing rules that hold regardless of task type, information-flow patterns proven reliable.

Do NOT extract team-specific internal practices, domain knowledge, or one-off session decisions.

If no durable cross-team norms are present, output nothing. Silence is correct.

Format each norm as:

## [{date}] Session Norm
**Pattern:** <the stable coordination norm>
**Why it holds:** <why this generalizes across sessions>

{context_section}

Session conversation:
{conversation}
""",

    "session-tasks": """Review the team-level learnings and session coordination below.

Extract learnings NOT specific to any single team:
- Cross-team coordination patterns that worked or failed
- Delegation strategies (task decomposition, sequencing, parallelism)
- Information flow between teams
- Resource allocation decisions

EXCLUDE anything specific to how one team works internally.

If no learnings meet the quality bar, output nothing. Silence is correct.

Format each learning as:

## [{date}] Session Learning
**Context:** <what we were doing when this came up>
**Learning:** <the specific insight>
**Action:** <what to do differently next time>

{context_section}

Session conversation:
{conversation}
""",

    "project-institutional": """Review the session learnings for this project.

Extract ONLY durable project-level NORMS: how this project is organized, naming conventions, architectural decisions governing future work, structural patterns holding across all future sessions.

Do NOT extract task procedures, one-off decisions, or debugging notes.

If no durable project-level norms are present, output nothing. Silence is correct.

Format each norm as:

## [{date}] Project Convention
**Convention:** <the stable norm or architectural decision>
**Applies to:** <what future work this governs>

{context_section}

Session conversation:
{conversation}
""",

    "project-tasks": """Review the session learnings below and extract patterns relevant to this project.

Focus on:
- Patterns that will recur in future sessions of this same project
- Project-specific workflow optimizations
- Domain knowledge aiding future work
- Team compositions or delegation strategies that worked for this project

Deduplicate with existing project learnings in the context.

If no learnings meet the quality bar, output nothing. Silence is correct.

Format each learning as:

## [{date}] Project Learning
**Context:** <what we were doing when this came up>
**Learning:** <the specific insight>
**Action:** <what to do differently next time>

{context_section}

Session conversation:
{conversation}
""",

    "global-institutional": """Review the project learnings below.

Extract ONLY cross-project NORMS: general-purpose agent coordination principles, structural patterns for team organization, conventions proven stable across different project domains.

This is a strict filter. Must be project-agnostic. Do NOT reference specific project names.

If nothing qualifies as truly cross-project institutional knowledge, output nothing.

Format each norm as:

## [{date}] Global Norm
**Norm:** <the cross-project coordination principle>
**Evidence:** <what pattern of observations supports this>

{context_section}

Session conversation:
{conversation}
""",

    "global-tasks": """Review the project learnings below and extract ONLY insights applying across ALL projects.

Strict filter. Only include:
- General-purpose agent coordination strategies
- Tool usage patterns (dispatch.sh, plan-execute lifecycle)
- Process improvements (task decomposition, parallelization)
- Communication patterns between team levels

EXCLUDE: domain-specific knowledge, project-specific decisions, content insights.
Do NOT reference specific project names.

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
}

# These scopes use the intent stream and need human-turn extraction
INTENT_STREAM_SCOPES = {"observations", "escalation"}


def summarize(stream_path: str, output_path: str, context_files: list[str], scope: str,
              phase: str = "unknown", domain: str = None):
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

    # Wrap each learning entry in YAML frontmatter (Phase 1 structured entries)
    wrapped_learnings = _wrap_learnings_with_frontmatter(
        learnings, scope=scope, phase=phase, domain=domain
    )

    # Append to output file
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with open(output, "a") as f:
        f.write("\n\n" + wrapped_learnings + "\n")

    print(f"[summarize] Appended {scope}-level learnings to {output_path}", file=sys.stderr)
    return 0


def promote(
    scope: str,
    session_dir: str,
    project_dir: str,
    output_dir: str,
    *,
    stream_path: str = "",
    context_files: list[str] | None = None,
    premortem_file: str = "",
    assumptions_file: str = "",
) -> int:
    """Importable entry point for the 7 promote_learnings.sh scope implementations.

    Mirrors the logic of promote_learnings.sh for each scope. Writes to the
    appropriate output location and returns 0 on success (including skip/no-op
    cases where there is nothing to promote), and a non-zero code on error.

    Args:
        scope: One of 'team', 'session', 'project', 'global', 'prospective',
               'in-flight', 'corrective'.
        session_dir: Path to the session infra directory (POC_SESSION_DIR).
        project_dir: Path to the project directory (POC_PROJECT_DIR).
        output_dir: Root output directory (POC_OUTPUT_DIR / projects dir for global).
        stream_path: Optional exec stream path. Falls back to session_dir exec stream.
        context_files: Optional explicit context file list (overrides auto-discovery).
        premortem_file: Path to pre-mortem file for prospective scope.
        assumptions_file: Path to assumptions checkpoint for in-flight scope.
    """
    from datetime import datetime as _dt

    ts = _dt.now().strftime('%Y%m%d-%H%M%S')

    def _exec_stream() -> str:
        """Return session exec stream path if present, else empty string."""
        if stream_path:
            return stream_path
        if not session_dir:
            # Avoid accidentally resolving a relative './.exec-stream.jsonl'
            # when session_dir is empty; treat this as "no exec stream".
            return ""
        candidate = os.path.join(session_dir, '.exec-stream.jsonl')
        if os.path.exists(candidate) and os.path.getsize(candidate) > 0:
            return candidate
        return ""

    def _context_args(paths: list[str]) -> list[str]:
        """Filter to non-empty existing files."""
        return [p for p in paths if os.path.isfile(p) and os.path.getsize(p) > 0]

    from projects.POC.orchestrator.phase_config import get_team_names
    TEAM_NAMES = list(get_team_names())

    if scope == 'team':
        # Dispatch MEMORY.md files → team institutional.md + team/tasks/<ts>.md
        if not session_dir:
            print("[promote] session_dir not set, skipping team rollup.", file=sys.stderr)
            return 1

        promoted = 0
        for team_name in TEAM_NAMES:
            team_dir = os.path.join(session_dir, team_name)
            if not os.path.isdir(team_dir):
                continue

            # Collect dispatch MEMORY.md files
            dispatch_mems = []
            for entry in os.scandir(team_dir):
                if entry.is_dir():
                    mem = os.path.join(entry.path, 'MEMORY.md')
                    if os.path.isfile(mem) and os.path.getsize(mem) > 0:
                        dispatch_mems.append(mem)

            if not dispatch_mems:
                continue

            # Find a dispatch exec stream for conversation context
            exec_stream = ""
            for entry in os.scandir(team_dir):
                if entry.is_dir():
                    candidate = os.path.join(entry.path, '.exec-stream.jsonl')
                    if os.path.isfile(candidate):
                        exec_stream = candidate
                        break

            if not exec_stream:
                exec_stream = os.devnull

            ctx = _context_args(dispatch_mems)
            tasks_dir = os.path.join(session_dir, team_name, 'tasks')
            os.makedirs(tasks_dir, exist_ok=True)

            # Institutional pass
            summarize(
                exec_stream,
                os.path.join(session_dir, team_name, 'institutional.md'),
                ctx,
                'team-rollup-institutional',
            )
            # Tasks pass
            summarize(
                exec_stream,
                os.path.join(tasks_dir, f'{ts}.md'),
                ctx,
                'team-rollup-tasks',
            )
            promoted += 1

        if not promoted:
            print("[promote] No dispatch MEMORYs found for team rollup.", file=sys.stderr)
        return 0

    elif scope == 'session':
        # Team typed files → session institutional.md + session/tasks/<ts>.md
        if not session_dir:
            print("[promote] session_dir not set, skipping session rollup.", file=sys.stderr)
            return 1

        if context_files is not None:
            ctx = _context_args(context_files)
        else:
            ctx = []
            for team_name in TEAM_NAMES:
                inst = os.path.join(session_dir, team_name, 'institutional.md')
                legacy = os.path.join(session_dir, team_name, 'MEMORY.md')
                if os.path.isfile(inst) and os.path.getsize(inst) > 0:
                    ctx.append(inst)
                elif os.path.isfile(legacy) and os.path.getsize(legacy) > 0:
                    ctx.append(legacy)
                tasks_path = os.path.join(session_dir, team_name, 'tasks')
                if os.path.isdir(tasks_path):
                    for f in os.listdir(tasks_path):
                        fp = os.path.join(tasks_path, f)
                        if fp.endswith('.md') and os.path.getsize(fp) > 0:
                            ctx.append(fp)

        if not ctx:
            print("[promote] No team learnings found for session rollup.", file=sys.stderr)
            return 0

        exec_s = _exec_stream()
        tasks_dir = os.path.join(session_dir, 'tasks')
        os.makedirs(tasks_dir, exist_ok=True)

        summarize(exec_s, os.path.join(session_dir, 'institutional.md'), ctx, 'session-institutional')
        summarize(exec_s, os.path.join(tasks_dir, f'{ts}.md'), ctx, 'session-tasks')

        # Compact to prevent monotonic growth
        _try_compact(os.path.join(session_dir, 'institutional.md'))
        return 0

    elif scope == 'project':
        # Session typed files → project institutional.md + project/tasks/<ts>.md
        if not session_dir or not project_dir:
            print("[promote] session_dir or project_dir not set, skipping project rollup.", file=sys.stderr)
            return 1

        if context_files is not None:
            ctx = _context_args(context_files)
        else:
            ctx = []
            inst = os.path.join(session_dir, 'institutional.md')
            legacy = os.path.join(session_dir, 'MEMORY.md')
            if os.path.isfile(inst) and os.path.getsize(inst) > 0:
                ctx.append(inst)
            elif os.path.isfile(legacy) and os.path.getsize(legacy) > 0:
                ctx.append(legacy)
            tasks_path = os.path.join(session_dir, 'tasks')
            if os.path.isdir(tasks_path):
                for f in os.listdir(tasks_path):
                    fp = os.path.join(tasks_path, f)
                    if fp.endswith('.md') and os.path.getsize(fp) > 0:
                        ctx.append(fp)

        if not ctx:
            print("[promote] No session learnings found for project rollup.", file=sys.stderr)
            return 0

        exec_s = _exec_stream()
        tasks_dir = os.path.join(project_dir, 'tasks')
        os.makedirs(tasks_dir, exist_ok=True)

        summarize(exec_s, os.path.join(project_dir, 'institutional.md'), ctx, 'project-institutional')
        summarize(exec_s, os.path.join(tasks_dir, f'{ts}.md'), ctx, 'project-tasks')

        _try_compact(os.path.join(project_dir, 'institutional.md'))
        return 0

    elif scope == 'global':
        # Project institutional.md → projects/ institutional.md + projects/tasks/<ts>.md
        if not project_dir:
            print("[promote] project_dir not set, skipping global rollup.", file=sys.stderr)
            return 1

        projects_dir = output_dir or os.path.dirname(project_dir)

        if context_files is not None:
            ctx = _context_args(context_files)
        else:
            ctx = []
            inst = os.path.join(project_dir, 'institutional.md')
            legacy = os.path.join(project_dir, 'MEMORY.md')
            if os.path.isfile(inst) and os.path.getsize(inst) > 0:
                ctx.append(inst)
            elif os.path.isfile(legacy) and os.path.getsize(legacy) > 0:
                ctx.append(legacy)

        if not ctx:
            print("[promote] No project learnings found for global rollup.", file=sys.stderr)
            return 0

        exec_s = _exec_stream()
        tasks_dir = os.path.join(projects_dir, 'tasks')
        os.makedirs(tasks_dir, exist_ok=True)

        summarize(exec_s, os.path.join(projects_dir, 'institutional.md'), ctx, 'global-institutional')
        summarize(exec_s, os.path.join(tasks_dir, f'{ts}.md'), ctx, 'global-tasks')

        _try_compact(os.path.join(projects_dir, 'institutional.md'))
        return 0

    elif scope == 'prospective':
        # Pre-mortem file + exec stream → project/tasks/<ts>-prospective.md
        if not session_dir or not project_dir:
            print("[promote] session_dir or project_dir not set, skipping prospective.", file=sys.stderr)
            return 1

        premortem = premortem_file or os.path.join(session_dir, '.premortem.md')
        if not os.path.isfile(premortem) or os.path.getsize(premortem) == 0:
            print("[promote] No pre-mortem file found, skipping prospective.", file=sys.stderr)
            return 0

        exec_s = _exec_stream()
        tasks_dir = os.path.join(project_dir, 'tasks')
        os.makedirs(tasks_dir, exist_ok=True)

        summarize(
            exec_s,
            os.path.join(tasks_dir, f'{ts}-prospective.md'),
            [premortem],
            'prospective',
        )
        return 0

    elif scope == 'in-flight':
        # Assumption checkpoint file + exec stream → project/tasks/<ts>-inflight.md
        if not session_dir or not project_dir:
            print("[promote] session_dir or project_dir not set, skipping in-flight.", file=sys.stderr)
            return 1

        assumptions = assumptions_file or os.path.join(session_dir, '.assumptions.jsonl')
        if not os.path.isfile(assumptions) or os.path.getsize(assumptions) == 0:
            print("[promote] No assumptions checkpoint file found, skipping in-flight.", file=sys.stderr)
            return 0

        exec_s = _exec_stream()
        tasks_dir = os.path.join(project_dir, 'tasks')
        os.makedirs(tasks_dir, exist_ok=True)

        summarize(
            exec_s,
            os.path.join(tasks_dir, f'{ts}-inflight.md'),
            [assumptions],
            'in-flight',
        )
        return 0

    elif scope == 'corrective':
        # Exec stream → project/tasks/<ts>-corrective.md
        if not session_dir or not project_dir:
            print("[promote] session_dir or project_dir not set, skipping corrective.", file=sys.stderr)
            return 1

        exec_s = _exec_stream()
        if not exec_s:
            print("[promote] No exec stream found, skipping corrective.", file=sys.stderr)
            return 0

        tasks_dir = os.path.join(project_dir, 'tasks')
        os.makedirs(tasks_dir, exist_ok=True)

        summarize(
            exec_s,
            os.path.join(tasks_dir, f'{ts}-corrective.md'),
            [],
            'corrective',
        )
        return 0

    else:
        print(f"[promote] Unknown scope: {scope}", file=sys.stderr)
        return 1


def _try_compact(path: str) -> None:
    """Compact a memory file in-place, silently skipping if unavailable."""
    try:
        from pathlib import Path as _Path
        import sys as _sys
        _sys.path.insert(0, str(_Path(__file__).parent))
        from compact_memory import compact_file
        compact_file(path)
    except Exception:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract session learnings")
    parser.add_argument("--stream", required=True, help="Path to .exec-stream.jsonl or .intent-stream.jsonl")
    parser.add_argument("--output", required=True, help="Path to target markdown file")
    parser.add_argument("--context", nargs="*", default=[], help="Additional context files")
    parser.add_argument("--scope", default="team",
                        choices=[
                            "team", "team-rollup", "team-rollup-institutional", "team-rollup-tasks",
                            "session", "session-institutional", "session-tasks",
                            "project", "project-institutional", "project-tasks",
                            "global", "global-institutional", "global-tasks",
                            "observations", "escalation", "intent-alignment",
                            "prospective", "in-flight", "corrective",
                        ],
                        help="Extraction scope")
    parser.add_argument("--phase", default="unknown",
                        help="Project phase to tag entries with (e.g. 'specification', 'implementation')")
    parser.add_argument("--domain", default=None, choices=["task", "team"],
                        help="Domain override ('task' or 'team'); inferred from scope if omitted")
    args = parser.parse_args()

    sys.exit(summarize(args.stream, args.output, args.context, args.scope,
                       phase=args.phase, domain=args.domain))
