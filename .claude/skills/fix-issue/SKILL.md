---
name: fix-issue
description: Fix GitHub Issue. Systematically investigate, test, and resolve a GitHub issue with full traceability — worktree isolation, failing tests, root cause analysis, fix, and merge.
argument-hint: <issue-number>
user-invocable: true
---

# Fix GitHub Issue

Resolve a GitHub issue with full traceability. Complete ALL phases — do not stop partway through.

- `$0` — the GitHub issue number (required)
- Commits: `Issue #$0: <description>` on line 1, detail below.

## Tool Usage

Use **Read**, **Write**, **Edit**, **Grep**, **Glob** for all file operations. Do NOT use `cat`, `head`, `tail`, `sed`, `grep`, or `find` via Bash — those trigger unnecessary permission prompts. Reserve Bash for `git`, `gh`, `uv run pytest`, and shell commands only.

## Phase 0: Worktree

Create an isolated worktree. NEVER work in the main checkout.

```bash
git fetch origin
git worktree add ../teaparty-issue-$0 -b fix/issue-$0 origin/develop
```

Then `cd ../teaparty-issue-$0`. ALL subsequent work happens there until Phase 7.

Update the project board to **In Progress** (see `project-board.md` in this skill directory).

## Phase 1: Understand

1. `gh issue view $0` — extract concrete acceptance criteria.
2. Read relevant docs starting from `docs/overview.md`. Use the **Read** tool.
3. Read relevant source in `projects/POC/orchestrator/` and tests. Use **Read** and **Grep**.

Before proceeding, post an issue comment stating:
- **What the issue asks for** (specific, in your own words)
- **What the current code does** (the gap)
- **Done when** (testable acceptance criteria)

Do not proceed until all three are clear.

## Phase 2: Risk Check

Post 2-4 concrete risks specific to this issue and this code as an issue comment. This is a paragraph, not a ceremony — move on.

## Phase 3: Failing Tests

1. Write tests proving the issue is resolved. Project conventions: `unittest.TestCase`, `_make_*()` helpers, no pytest fixtures, no `conftest.py`.
2. Run and confirm they fail: `uv run pytest <test_file>::<TestClass>::<test_method> --tb=short -q`
3. Commit. Brief issue comment with what tests verify.

## Phase 4: Fix and Verify

1. Fix the issue.
2. **Check against Phase 1 acceptance criteria** — does this address the intent, not just surface symptoms?
3. Commit.
4. Run specific tests, confirm pass.
5. Run full suite: `uv run pytest projects/POC/orchestrator/tests/ --tb=short -q`
6. Fix regressions before proceeding.

## Phase 5: Close Out

Post final issue comment: root cause, what fix does, which tests verify, any follow-up.
Close: `gh issue close $0`
Update project board to **Done** (see `project-board.md`).

## Phase 6: Self-Review

`git diff origin/develop...HEAD` — every change must trace to acceptance criteria. No scope creep. Fix problems before merging.

## Phase 7: Merge

```bash
cd /Users/darrell/git/teaparty
git checkout develop
git merge --no-ff fix/issue-$0 -m "Merge fix/issue-$0: <description>"
git push origin develop
git worktree remove ../teaparty-issue-$0
```
