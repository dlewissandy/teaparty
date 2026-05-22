# Phase 4: Fix

Implement the change so the failing tests pass.

`Delegate(coding-lead, <task>, skill='attempt-task')` with a task message that:

1. References `UNDERSTANDING.md`, `RISKS.md`, and the failing tests merged in the previous phase.
2. Names the acceptance criteria the implementation must satisfy.
3. Reminds the coding-lead: code conforms to design docs (escalate to you if the design seems wrong); no historical artifacts in code or comments (git is the history); no follow-up tickets (finish the work in this dispatch).
4. Asks for the implementation to be committed on the session branch with the `Issue #N: <description>` commit-message convention.

When the coding-lead replies, `CloseConversation` to merge the implementation. Read the reply for what changed and where.

If the coding-lead escalates that the design doc and the issue contradict, halt this phase and `AskQuestion` to your originator. Do not let the coding-lead silently pick a side.

---

**Next:** Read `phase-resolution.md` in this skill directory.
