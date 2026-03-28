---
name: audit-issue
description: Intent-fidelity audit of an issue's diff. Spawns reviewers scoped to the diff, posts findings as intent statements on the issue, returns a verdict.
argument-hint: <issue-number>
user-invocable: true
---

# Audit Issue

Verify that a fix fully realizes the intent of its issue. This is not a code quality review — it is an intent fidelity check. The question is: does this diff deliver what the issue and its design docs are actually asking for?

- `$0` — the GitHub issue number (required)
- Use **Read**, **Glob**, **Grep**, **Write** for file ops. Reserve Bash for `git` and `gh` only.

## Phase 0: Gather Context

1. `gh issue view $0` — extract the issue text, acceptance criteria, and any linked design docs or proposals.
2. Read every design doc or proposal referenced by the issue.
3. Capture the diff against the branch point (not current develop, which may have moved):
   ```bash
   MERGE_BASE=$(git merge-base origin/develop HEAD)
   git diff $MERGE_BASE...HEAD
   ```
4. Write context to `audit-issue/context.md`:

```markdown
# Audit Context: Issue #$0

## Issue Text
{full issue body}

## Design Docs
{for each: path, relevant sections verbatim}

## Diff Summary
{files changed, insertions, deletions}
```

## Phase 0.5: Load Prior Findings

Fetch all prior audit comments for this issue:

```bash
gh api repos/{owner}/{repo}/issues/$0/comments --jq '[.[] | select(.body | contains("<!-- audit-issue:$0:finding:"))]'
```

Classify each as **open** or **resolved** (resolved comments contain `**RESOLVED**`).

Write to `audit-issue/prior-findings.md`:

```markdown
# Prior Audit Findings

## Open (still unresolved)
{for each: finding number, title, body}

## Resolved
{for each: finding number, title — summary only}
```

If there are no prior findings, write `No prior audit findings.`

## Phase 1: Review (parallel subagents)

Read both role prompts from this skill directory, then launch both as parallel subagents **in a single message**:

| Reviewer | Role file | Output file |
|----------|-----------|-------------|
| Intent | `role-intent.md` | `audit-issue/intent-review.md` |
| Factcheck | `role-factcheck.md` | `audit-issue/factcheck-review.md` |

Each subagent gets:

```
Agent(
    subagent_type="general-purpose",
    description="<Reviewer> review",
    prompt="<full role prompt text>\n\n---\nISSUE = $0\nCONTEXT_FILE = audit-issue/context.md\nPRIOR_FINDINGS_FILE = audit-issue/prior-findings.md"
)
```

After both complete, validate each output file exists and contains a `## Findings` heading.

## Phase 2: Verdict

Read both review files. Synthesize a verdict:

- **COMPLETE** — the diff delivers the intent of the issue fully and faithfully. No findings, or findings are minor and do not affect intent fidelity.
- **PARTIAL** — the diff touches the right area but leaves meaningful parts of the intent undelivered. Findings describe what is missing.
- **WRONG DIRECTION** — the diff does not deliver what the issue asks for. The approach or understanding is fundamentally off.

## Phase 3: Post to Issue

Format each finding using the template in `finding-template.md` (in this skill directory).

### Comment strategy

Each finding gets its own comment. One additional comment carries the verdict. Comments use HTML markers so the audit can find its own comments on re-runs.

**Fetch prior audit comments:**

```bash
gh api repos/{owner}/{repo}/issues/$0/comments --jq '[.[] | select(.body | contains("<!-- audit-issue:$0:"))]'
```

This returns all prior audit comments (findings and verdict) for this issue.

### For each finding:

Check if this finding has a prior comment (match by finding number in marker):

- **New finding** — post a new comment:
  ```markdown
  <!-- audit-issue:$0:finding:N -->
  {finding formatted per finding-template.md}

  ---
  *`/audit-issue` finding N — reviewers: {which reviewers flagged this}*
  ```

- **Still open** — edit the existing comment in place (wording may have refined).

- **Addressed** — edit the existing comment to mark resolved:
  ```markdown
  <!-- audit-issue:$0:finding:N -->
  **RESOLVED**

  ~~{original finding title}~~

  <details>
  <summary>Original finding</summary>

  {original finding body preserved}

  </details>

  ---
  *`/audit-issue` finding N — resolved*
  ```

### Verdict comment:

Check if a prior verdict comment exists (`<!-- audit-issue:$0:verdict -->`). Edit if so, post if not.

```markdown
<!-- audit-issue:$0:verdict -->
## Intent Audit

**Verdict: {COMPLETE|PARTIAL|WRONG DIRECTION}**
**Open findings:** {count} | **Resolved:** {count}

{If COMPLETE: "This diff delivers the intent of the issue fully and faithfully."}

---
*`/audit-issue` — reviewers: intent, factcheck*
```

### Reopen if needed:

If the verdict is PARTIAL or WRONG DIRECTION:

```bash
gh issue reopen $0
```

## Return

Print the verdict. If called from `//fix-issue`, the fixing agent acts on it:
- **COMPLETE** — proceed to merge.
- **PARTIAL** — go back to Phase 4, address what's missing, then re-run `//audit-issue`.
- **WRONG DIRECTION** — stop and escalate to the human.

Two rounds maximum. If the second audit is not COMPLETE, escalate.
