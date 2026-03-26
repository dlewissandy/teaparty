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
- Use **Read**, **Write**, **Edit**, **Grep**, **Glob** for file ops. Reserve Bash for `git`, `gh`, `uv run pytest`, and shell commands only.

## Phase 0: Worktree

NEVER work in the main checkout.

```bash
git fetch origin
git worktree add ../teaparty-issue-$0 -b fix/issue-$0 origin/develop
```

Then `cd ../teaparty-issue-$0`. Update project board to **In Progress** (see `project-board.md`).

## Phase 1: Understand

1. `gh issue view $0` — extract acceptance criteria.
2. Read relevant docs (`docs/overview.md` and linked design docs) and source (`projects/POC/orchestrator/`).
3. Post issue comment: **what the issue asks for**, **what the current code does** (the gap), **done when** (testable criteria). Do not proceed until all three are clear.

## Phase 2: Risk Check

Post 2-4 concrete risks as an issue comment. A paragraph, not a ceremony.

## Phase 3: Failing Tests

Write specification-based tests that encode the issue's requirements. Read `testing-standards.md` in this skill directory for guidelines. A passing test must mean the requirement is met.

1. Write the tests.
2. Run and confirm they fail: `uv run pytest <test_file>::<TestClass>::<test_method> --tb=short -q`
3. Commit. Brief issue comment with what tests verify.

## Phase 4: Fix and Verify

1. Fix the issue. **Code conforms to design docs** — never edit docs to match your code. Escalate if you disagree with the design. **No historical artifacts** — don't comment about what code "used to do" or preserve old behavior in comments/docs. Git is the history.
2. Check against Phase 1 acceptance criteria — intent, not just surface symptoms.
3. Commit. Run specific tests, then full suite: `uv run pytest projects/POC/orchestrator/tests/ --tb=short -q`
4. Fix regressions before proceeding.

## Phase 5: Close Out

Post final issue comment: root cause, what fix does, which tests verify.
Close: `gh issue close $0`. Update project board to **Done** (see `project-board.md`).

## Phase 6: Self-Review

Read `self-review.md` in this skill directory and execute every step. Re-read the issue and design docs. Review your diff against them. Fix problems before merging.

## Phase 7: Merge

```bash
cd /Users/darrell/git/teaparty
git checkout develop
git merge --no-ff fix/issue-$0 -m "Merge fix/issue-$0: <description>"
git push origin develop
git worktree remove ../teaparty-issue-$0
```
