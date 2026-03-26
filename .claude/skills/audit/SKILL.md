---
name: audit
description: Multidimensional code audit using an ensemble of specialized reviewers as parallel subagents. Findings are deduplicated, triaged, and filed as GitHub issues.
argument-hint: [topic] [--dry-run]
user-invocable: true
---

# Code Audit

Multidimensional code review through an ensemble of specialized reviewers. Each reviewer runs as an independent subagent with a fresh context window. Findings are deduplicated, triaged, and filed as GitHub issues.

**This pipeline does not modify source code.** All scratch output goes to `audit/` (gitignored).

## Arguments

- `$0` — optional focus topic (e.g., "agentic memory system", "CfA state machine transitions")
- `--dry-run` — review findings without filing issues

## Tool Usage

The orchestrator and all subagents use **Read**, **Glob**, **Grep**, **Write** for file operations. Do NOT use `cat`, `head`, `tail`, `grep`, `find` via Bash. Reserve Bash for `python3` (prefetch script) and `gh` (issue filing) only.

## Setup

```
TOPIC = $0 or "all"
DRY_RUN = true if --dry-run present, else false

rm -rf audit/findings
rm -f audit/dedup.md audit/triage.md
mkdir -p audit/findings audit/context
```

Do NOT delete `audit/filed.json` — it prevents duplicate filing on re-runs.

## Phase 0: Prefetch

```bash
python3 projects/POC/scripts/audit_prefetch.py --outdir audit/context
```

If non-zero exit, warn that issue-filtering context is incomplete (triage may produce duplicates). Ask whether to continue.

## Phase 1: Scan (parallel subagents)

Read all four role prompts from this skill directory, then launch all four as parallel subagents **in a single message**:

| Reviewer | Role file | Output file |
|----------|-----------|-------------|
| Architect | `role-architect.md` | `audit/findings/architect.md` |
| Specialist | `role-specialist.md` | `audit/findings/specialist.md` |
| Factcheck | `role-factcheck.md` | `audit/findings/factcheck.md` |
| Honesty | `role-honesty.md` | `audit/findings/honesty.md` |

Each subagent gets:
```
Agent(
    subagent_type="general-purpose",
    description="<Reviewer> review",
    prompt="<full role prompt text>\n\n---\nTOPIC = <topic>"
)
```

**After all complete**, validate each output file exists, is >100 bytes, and contains a `## Findings` heading (use Grep). If any fails, report which and stop.

Optional extended reviewers (launch only when relevant): `role-ai-smell.md`, `role-performance.md`.

## Phase 2: Deduplicate (single subagent)

Launch `role-dedup.md` as a single subagent. Verify `audit/dedup.md` exists with `## Convergent Findings` or `## Single-Reviewer Findings` heading.

## Phase 3: Triage (single subagent)

Launch `role-triage.md` as a single subagent. Verify `audit/triage.md` exists with `## File These` heading.

## Phase 4: File Issues

Read `audit/triage.md` and `issue-template.md` (in this skill directory).

For each finding in "File These" that hasn't been filed (check `audit/filed.json`):

1. Format the issue body using the template in `issue-template.md`
2. Create with `gh issue create --title "..." --body "..." --label audit,...`
3. Immediately append to `audit/filed.json` (write after each, not batched — crash safety)
4. Add to project board as backlog
5. Print the issue URL

If `--dry-run`, print what would be filed instead.

### filed.json format

```json
{"A-003": 101, "A-007": 102}
```

## Completion

```
## Audit Complete

**Topic:** [topic or "full codebase"]
**Reviewers:** [list]
**Raw findings:** [count]  **After dedup:** [count]  **Filed:** [count]

### Issues Filed
- #101: A-003 — [title]
...

### Parking Lot
[Findings that didn't make the cut, with scores]
```
