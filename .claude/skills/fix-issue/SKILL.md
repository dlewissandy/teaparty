---
name: fix-issue
description: Fix GitHub Issue. Systematically investigate, test, and resolve a GitHub issue with full traceability — branching, pre-mortem, failing tests, root cause analysis, fix, post-mortem, and merge.
argument-hint: <issue-number>
user-invocable: true
---

# Fix GitHub Issue

Systematically investigate, test, and resolve a GitHub issue with full traceability.

All work is performed on an isolated branch. The branch is merged back to develop at the end.

## Arguments

- `$0` — the GitHub issue number (required)

## Commit Convention

Every commit in this workflow uses a multiline message:
- **Line 1:** `Issue #<number>: <short description>`
- **Remaining lines:** Describe the work in detail.

## Phase 0: Create Working Branch

Ensure the develop branch exists and is up to date, then branch from it:

```bash
# Create develop from main if it doesn't exist yet
git fetch origin
git checkout develop 2>/dev/null || git checkout -b develop main

# Create the working branch from develop
git checkout -b fix/issue-<number>
```

All subsequent work happens on this branch. Do not work directly on develop or main.

Move the issue to **In Progress** on the project board:

```bash
# 1. Find the project item ID for this issue
ITEM_ID=$(gh api graphql -f query='
{
  user(login: "dlewissandy") {
    projectV2(number: 2) {
      items(first: 100) {
        nodes {
          id
          content { ... on Issue { number } }
        }
      }
    }
  }
}' --jq '.data.user.projectV2.items.nodes[] | select(.content.number == <number>) | .id')

# 2. Set Status = In Progress
gh api graphql -f query="
mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: \"PVT_kwHOAH4OHc4BR81E\"
    itemId: \"${ITEM_ID}\"
    fieldId: \"PVTSSF_lAHOAH4OHc4BR81Ezg_oGbs\"
    value: { singleSelectOptionId: \"71f64e69\" }
  }) { projectV2Item { id } }
}"
```

## Phase 1: Understand

1. **Read the issue** using `gh issue view <number>`.
2. **Read the docs** -- read everything under `docs/` (and nowhere else) that is relevant to the issue. Start with `docs/overview.md` and follow references.
3. **Read the code** -- read the relevant source files in `projects/POC/orchestrator/` and its tests in `projects/POC/orchestrator/tests/`. Understand the current behavior.

Do not proceed until you have a clear understanding of what the issue describes, what the code currently does, and what the docs say it should do.

## Phase 2: Pre-Mortem

Run `/premortem` against the task of fixing this issue. Post the pre-mortem as a comment on the GitHub issue:

```bash
gh issue comment <number> --body "<premortem output>"
```

## Phase 3: Write Failing Tests

1. Write a test or tests that are **necessary and sufficient** to prove the issue is resolved. Follow the project test conventions: `unittest.TestCase` with `_make_*()` helpers, no pytest fixtures, no `conftest.py`.
2. Run the tests and **demonstrate that they fail** with the current code:
   ```bash
   uv run pytest <test_file>::<TestClass>::<test_method> --tb=short -q
   ```
3. Commit the failing tests:
   ```
   Issue #<number>: Add failing tests for <issue description>

   <describe what the tests verify and why they are the right tests>
   ```
4. Post progress as a comment on the GitHub issue:
   ```bash
   gh issue comment <number> --body "Failing tests committed: <commit hash>. Tests verify: <what they check>."
   ```

## Phase 4: Investigate Root Cause

1. Investigate the root cause of the issue. Read code, trace execution paths, run experiments if needed.
2. **Do not fix the issue yet.** Understand it fully first.
3. Be certain of your conclusions. If you are not certain, run more experiments.
4. Post your findings as a comment on the GitHub issue:
   ```bash
   gh issue comment <number> --body "<learnings and root cause hypothesis>"
   ```

## Phase 5: Fix and Verify

This phase repeats until all tests pass:

1. **Address the issue** based on your root cause analysis.
2. **Commit the fix:**
   ```
   Issue #<number>: <short description of fix>

   <detailed description of what was changed and why>
   ```
3. **Run the tests** and demonstrate they pass:
   ```bash
   uv run pytest <test_file>::<TestClass>::<test_method> --tb=short -q
   ```
4. If tests fail, return to step 1 of this phase. Refine your understanding and try again.

Also run the broader test suite to check for regressions:
```bash
uv run pytest projects/POC/orchestrator/tests/ --tb=short -q
```

## Phase 6: Close Out

Post a final comment on the GitHub issue summarizing:
- What the root cause was
- What the fix does
- Which tests verify the fix
- Any remaining considerations or follow-up work

```bash
gh issue comment <number> --body "<final summary>"
```

Move the issue to **Done** on the project board and close it:

```bash
# 1. Find the project item ID for this issue
ITEM_ID=$(gh api graphql -f query='
{
  user(login: "dlewissandy") {
    projectV2(number: 2) {
      items(first: 100) {
        nodes {
          id
          content { ... on Issue { number } }
        }
      }
    }
  }
}' --jq '.data.user.projectV2.items.nodes[] | select(.content.number == <number>) | .id')

# 2. Set Status = Done
gh api graphql -f query="
mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: \"PVT_kwHOAH4OHc4BR81E\"
    itemId: \"${ITEM_ID}\"
    fieldId: \"PVTSSF_lAHOAH4OHc4BR81Ezg_oGbs\"
    value: { singleSelectOptionId: \"42fb9610\" }
  }) { projectV2Item { id } }
}"

# 3. Close the issue
gh issue close <number>
```

## Phase 7: Post-Mortem

Run `/postmortem` against this fix. Post the post-mortem as a comment on the GitHub issue:

```bash
gh issue comment <number> --body "<postmortem output>"
```

## Phase 8: Merge to Develop

Merge the working branch back to develop:

```bash
git checkout develop
git merge --no-ff fix/issue-<number> -m "$(cat <<'EOF'
Merge fix/issue-<number>: <short description>

<summary of all changes made on the branch>
EOF
)"
```

Use `--no-ff` to preserve the branch history as a distinct unit of work.

Push the result:

```bash
git push origin develop
```
