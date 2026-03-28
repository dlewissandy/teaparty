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

**First action:** Rename this session immediately:
```
/rename fix-issue $0
```

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
4. Write down a numbered list of acceptance criteria. These are your contract — you will verify against them in Phase 4 and Phase 6.

## Phase 2: Risk Check

Post 2-4 concrete risks as an issue comment. A paragraph, not a ceremony.

## Phase 3: Failing Tests

Write specification-based tests that encode the issue's requirements. Read `testing-standards.md` in this skill directory for guidelines. A passing test must mean the requirement is met.

1. Write the tests.
2. Run and confirm they fail: `uv run pytest <test_file>::<TestClass>::<test_method> --tb=short -q`
3. **Failure validation:** For each failing test, confirm it fails because the feature/fix is missing — not because of a typo, import error, or wrong assertion. If the test would still fail after a correct implementation, the test is wrong. Fix it.
4. **Coverage check:** Map each acceptance criterion from Phase 1 to at least one test. If any criterion has no test, write one.
5. Commit. Brief issue comment with what tests verify.

## Phase 4: Fix and Verify

1. Fix the issue. **Code conforms to design docs** — never edit docs to match your code. Escalate if you disagree with the design. **No historical artifacts** — don't comment about what code "used to do" or preserve old behavior in comments/docs. Git is the history.
2. **Wiring check:** For every new function, class, or method you wrote — grep for where it is called. If nothing calls it, it is not integrated. Wire it in or delete it. Untested, unwired code is not a fix.
3. **Acceptance gate:** Go back to your Phase 1 acceptance criteria. For each one, identify the specific file and function that satisfies it. If you cannot point to concrete code for a criterion, the work is not done — keep going.
4. Run specific tests, then full suite: `uv run pytest projects/POC/orchestrator/tests/ --tb=short -q`
5. Fix regressions before proceeding.
6. Commit.

## Phase 5: Resolution Summary

Post issue comment: root cause, what fix does, which tests verify. Do NOT close the issue — the audit decides that.

## Phase 6: Self-Review

Read `self-review.md` in this skill directory and execute every step. This is adversarial — your job is to find problems, not confirm you're done.

## Phase 7: Audit

Run `//audit-issue $0` to verify intent fidelity before merging.

Act on the verdict:

- **COMPLETE** — proceed to Phase 8.
- **PARTIAL** — the audit reopens the issue and posts findings. You MUST loop:
  1. Read every open finding.
  2. Go back to Phase 4: fix what's missing, run tests, commit.
  3. Re-run `//audit-issue $0`.
  4. If the second audit is COMPLETE, proceed to Phase 8. If not, escalate to the human.
- **WRONG DIRECTION** — stop and escalate to the human.

Do NOT proceed to Phase 8 until the audit verdict is COMPLETE.

## Phase 8: Close and Merge

Close: `gh issue close $0`. Update project board to **Done** (see `project-board.md`).

```bash
cd /Users/darrell/git/teaparty
git checkout develop
git merge --no-ff fix/issue-$0 -m "Merge fix/issue-$0: <description>"
git push origin develop
git worktree remove ../teaparty-issue-$0
```
