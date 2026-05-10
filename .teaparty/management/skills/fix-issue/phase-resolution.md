# Phase 5: Resolution

Verify the fix is integrated, the test suite is green, and nothing adjacent regressed.

`Delegate(coding-lead, <task>, skill='attempt-task')` with a task message that:

1. References the implementation merged in the previous phase and the failing tests merged in `phase-tests.md`.
2. Asks the coding-lead to:
   - Trace each new function/class/method to where it is called. Untested, unwired code is not a fix — wire it in or delete it.
   - Trace the feature from entry point to observable effect. Walk the call chain end-to-end. If the chain has a gap, the work is not done.
   - Run the full test suite (`uv run pytest`). All previously failing tests must now pass; nothing else may regress.
3. Asks for a `RESOLUTION.md` in the worktree summarizing: each acceptance criterion → file:line that satisfies it; the test result; any regressions encountered and how they were resolved.

When the coding-lead replies, `CloseConversation` to merge `RESOLUTION.md`. Read it.

If `RESOLUTION.md` reports unresolved regressions or wiring gaps, `Send` the gap back into the same thread for the coding-lead to fix. Do not advance until the resolution is clean.

---

**Next:** Read `phase-self-review.md` in this skill directory.
