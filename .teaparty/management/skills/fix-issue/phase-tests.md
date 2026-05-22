# Phase 3: Tests

Failing tests come before the fix. They encode what "done" means for this issue, separate from the implementation that will satisfy them.

`Delegate(quality-control-lead, <task>, skill='attempt-task')` with a task message that:

1. References `UNDERSTANDING.md` (acceptance criteria) and `RISKS.md` (regression surface).
2. Asks for tests that encode each acceptance criterion symbolically where possible, with example tests as fallback. The standard is symbolic-or-property tests checking invariants; thin example tests that pass without exercising the criterion are not acceptable.
3. Asks the quality-control-lead to commit failing tests on the session branch and reply with the list of test files added and which acceptance criterion each one targets.

When the quality-control-lead replies, `CloseConversation` to merge the tests into your worktree. Read the reply and confirm the new tests fail right now (a passing test before the fix lands is a sign the test does not actually exercise the criterion — `Send` a correction to the same thread if so).

If the quality-control-lead reports an acceptance criterion they cannot test (because it is genuinely subjective, or because it requires an environment they do not have), capture it in their reply and carry it into the audit phase as a thing the QA lead must verify by inspection.

---

**Next:** Read `phase-fix.md` in this skill directory.
