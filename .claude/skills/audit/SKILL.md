---
name: audit
description: Multidimensional code audit using an ensemble of specialized reviewers as parallel subagents. Findings are deduplicated, triaged, and filed as GitHub issues.
argument-hint: [topic] [--dry-run]
user-invocable: true
---

# Code Audit

Multidimensional code review that surfaces consequential issues through an ensemble of specialized reviewers. Each reviewer runs as an independent subagent with a fresh context window. Findings are deduplicated, triaged against existing issues, and filed as GitHub backlog items.

**This pipeline does not modify any source code.** All scratch output goes to `audit/` (gitignored).

Every role runs as an independent subagent with a fresh context window. Roles communicate exclusively through the filesystem — never through conversation history. This keeps the orchestrator lean and prevents context exhaustion.

## Arguments

- `$0` — optional topic to focus the audit (e.g., "agentic memory system", "CfA state machine transitions")
- `--dry-run` — review findings without filing issues (default: file issues)

If no topic is given, audit everything that is not in `docs/` and not gitignored.

## Setup

```
TOPIC = $0 or "all"
DRY_RUN = true if --dry-run present, else false
```

### Clean Previous Run

```
rm -rf audit/findings
rm -f audit/dedup.md audit/triage.md
mkdir -p audit/findings
mkdir -p audit/context
```

**Do NOT delete `audit/filed.json`** — it tracks which issues were already filed and prevents duplicates on re-run. Only delete it manually when starting a genuinely new audit.

## Phase 0: Prefetch

Gather context that reviewers will need, so they can work with Read/Glob/Grep only.

```
python3 projects/POC/scripts/audit_prefetch.py --outdir audit/context
```

**Check the exit code.** If prefetch exits non-zero, warn the operator that issue-filtering context is missing or incomplete. The pipeline can still proceed (reviewers don't depend on issues context), but triage may produce duplicates of existing GH issues. Print the warning and ask whether to continue.

## Phase 1: Scan (parallel subagents)

Read all four core role prompt files from this skill directory:

```
.claude/skills/audit/role-architect.md
.claude/skills/audit/role-specialist.md
.claude/skills/audit/role-factcheck.md
.claude/skills/audit/role-honesty.md
```

Launch all four reviewers as parallel subagents **in a single message**. Each gets a fresh context with only the role prompt and the topic parameter.

For each reviewer, launch an agent:

```
Agent(
    subagent_type="code-reviewer",
    description="Architect review",
    prompt="""
    <full text of role-architect.md>

    ---
    TOPIC = <topic or "all">
    """
)
```

Repeat for specialist, factcheck, and honesty — all four in one message so they run concurrently.

**Wait for all four to complete.** If a subagent has not produced output after 10 minutes, treat it as failed — do not wait indefinitely.

After they complete, validate each output file:
- `audit/findings/architect.md`
- `audit/findings/specialist.md`
- `audit/findings/factcheck.md`
- `audit/findings/honesty.md`

For each file, check that it:
1. **Exists** — the file was created
2. **Is non-empty** — at least 100 bytes (a crashed agent may write an empty or stub file)
3. **Contains a `## Findings` heading** — confirms the reviewer completed its analysis (use Grep)

If any file fails validation, report which reviewer failed and why (missing, empty, or malformed), then stop. Do not proceed to dedup with incomplete results — partial inputs produce misleading dedup and triage output.

## Phase 2: Deduplicate (single subagent)

Read the role prompt from `role-dedup.md`. Launch a single subagent:

```
Agent(
    subagent_type="code-reviewer",
    description="Deduplicate findings",
    prompt="""
    <full text of role-dedup.md>
    """
)
```

**Wait for completion.**

Verify `audit/dedup.md` exists, is non-empty, and contains an `## Convergent Findings` or `## Single-Reviewer Findings` heading. If not, report the failure and stop.

## Phase 3: Triage (single subagent)

Read the role prompt from `role-triage.md`. Launch a single subagent:

```
Agent(
    subagent_type="code-reviewer",
    description="Triage findings",
    prompt="""
    <full text of role-triage.md>
    """
)
```

**Wait for completion.**

Verify `audit/triage.md` exists, is non-empty, and contains a `## File These` heading. If not, report the failure and stop.

## Phase 4: File Issues (orchestrator)

Read `audit/triage.md` yourself (in the orchestrator context — it's short).

### Filing Manifest (idempotency)

Before filing, check if `audit/filed.json` exists from a prior partial run. If it does, read it — it maps finding IDs to GH issue numbers. Skip any finding that already has an entry.

For each finding in the "File These" section that has NOT been filed:

1. Create a GitHub issue using `gh issue create`:
   - Title from "Proposed issue title"
   - Body from "Proposed issue body", prefixed with `[Audit finding {ID}]`
   - Labels from "Proposed labels"
2. **Immediately** append the finding ID and issue number to `audit/filed.json` (write after each issue, not in batch — this is the crash-safety mechanism)
3. Add the issue to the project board as backlog (use project board IDs from memory)
4. Print the created issue URL

The manifest format:
```json
{"A-003": 101, "A-007": 102}
```

### Dry Run (`--dry-run`)

Skip creating GH issues. Print what would be filed.

## Completion

Print:

```
## Audit Complete

**Topic:** [topic or "full codebase"]
**Reviewers:** architect, specialist, factcheck, honesty
**Raw findings:** [count]
**After dedup:** [count]
**Filed:** [count]

### Issues Filed

- #101: A-003 — [title] — https://github.com/...
- #102: A-007 — [title] — https://github.com/...

### Parking Lot (not filed)
[List findings that didn't make the cut, with their scores]
```

## Optional Extended Reviewers

Two additional reviewers are available for targeted audits. These are NOT run by default — invoke them explicitly when relevant:

- `role-ai-smell.md` — AI/LLM integration quality (prompt fragility, token waste, agentic anti-patterns)
- `role-performance.md` — Performance issues (algorithmic complexity, I/O waste, resource leaks)

To include them, launch them alongside the core four in Phase 1, and adjust Phase 2/3 to expect their output files (`audit/findings/ai-smell.md`, `audit/findings/performance.md`).

## How to Launch a Subagent

Read the role prompt file from the skill directory, then launch an agent with the full role prompt text and the topic parameter. Example pattern:

```
Agent(
    subagent_type="code-reviewer",
    description="Architect review",
    prompt="""
    <role prompt text read from role-architect.md>

    ---
    TOPIC = CfA state machine
    """
)
```

The role prompt files are in the same directory as this SKILL.md file. Use Glob to find them:
```
.claude/skills/audit/role-*.md
```

Each role prompt contains everything the subagent needs: what to read, what to evaluate, and where to write output. The orchestrator's only job is to read these files, inject the TOPIC parameter, launch agents, wait for results, and make filing decisions.

## Principles

- **Context isolation is the point.** Each reviewer gets a fresh context window. The orchestrator never accumulates reviewer output in its own context — it only reads the short triage output at the end.
- **The filesystem is the message bus.** All communication between roles happens through files in `audit/`. This is durable, inspectable, and context-free.
- **Parallel when independent, sequential when dependent.** Reviewers are independent. Dedup depends on all reviewers. Triage depends on dedup.
- **The orchestrator stays lean.** It manages lifecycle, not content. It reads role prompts, launches agents, checks for output files, reads triage results, and files issues.
