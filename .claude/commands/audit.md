# Code Audit

Multidimensional code review that surfaces consequential issues through an ensemble of specialized reviewers. Findings are deduplicated, triaged against existing issues, and filed as GitHub backlog items.

**This pipeline does not modify any source code.** All scratch output goes to `audit/` (gitignored).

## Argument

An optional topic to focus the audit: `/audit agentic memory system` or `/audit CfA state machine transitions`

If no topic is given, audit everything that is not in `docs/` and not gitignored. This means the full codebase — `projects/POC/orchestrator/`, `projects/POC/tui/`, `projects/POC/scripts/`, etc.

If a topic is given, reviewers should use it to focus their attention: find the files, modules, and functions most relevant to that topic, and audit those in depth rather than scanning everything shallowly.

Optional: `--dry-run` to review findings without filing issues (default: file issues)

## Phase 0: Prefetch

Gather context that reviewers will need, so they can work with Read/Glob/Grep only (no Bash, no WebSearch).

```
python3 projects/POC/scripts/audit_prefetch.py --outdir audit/context
```

Create the findings directory:

```
mkdir -p audit/findings
```

If `audit/findings/` already has files from a prior run, delete them:

```
rm -f audit/findings/*.md
```

## Phase 1: Scan (parallel)

Run all four reviewers in parallel. Each uses only Read, Glob, and Grep. Each writes to its own file under `audit/findings/`.

Pass the topic (or "all") as the scope argument:

- `/audit-architect <topic or all>` — Structural soundness, race conditions, failure modes, spec drift, OO overboard, stale comments, production cosplay
- `/audit-specialist <topic or all>` — Algorithmic soundness, LLM integration quality, theoretical basis, cargo culting
- `/audit-factcheck <topic or all>` — Code vs. docs vs. citations consistency
- `/audit-honesty <topic or all>` — Complexity theater, naming dishonesty, confidence without basis, swept-under-rug, fake generality

Wait for all four to complete before proceeding.

## Phase 2: Deduplicate

Run the deduplicator. It reads all four findings files and produces a consolidated list with stable IDs.

- `/audit-dedup`

Output: `audit/dedup.md`

## Phase 3: Triage

Run the triager. It reads the deduplicated findings, compares against existing GH issues and dismissed findings, ranks by consequence, and selects the top findings.

- `/audit-triage`

Output: `audit/triage.md`

## Phase 4: File Issues (default)

Read `audit/triage.md`. For each finding in the "File These" section:

1. Create a GitHub issue using `gh issue create`:
   - Title from "Proposed issue title"
   - Body from "Proposed issue body", prefixed with `[Audit finding {ID}]`
   - Labels from "Proposed labels"
2. Add the issue to the project board as backlog (use project board IDs from memory)
3. Print the created issue URLs

After filing:

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

### Dry Run (`--dry-run`)

Same output but skip creating GH issues. Print what would be filed:

```
## Audit Complete (dry run)

...same summary...

### Would File

1. **A-003: [title]** (score: 10, convergent) — [one-line summary]
2. **A-007: [title]** (score: 8) — [one-line summary]
```

## Notes

- **No code is modified.** The audit directory is gitignored.
- **Reviewers use only safe tools.** Read, Glob, Grep — no permission escalation during the scan phase.
- **Bash is used only by the orchestrator** for prefetch (Phase 0) and issue filing (Phase 4).
- **`audit/audit-dismissed.md`** persists across runs. Add dismissed findings there to prevent re-filing.
- **Convergent findings** (flagged by 2+ reviewers) are weighted higher in triage.
