# Phase 1: Understand

Read the issue and any design docs it references before any other phase runs. The understanding artifact is the spec every later phase delegates against.

`Delegate(coding-lead, <task>, skill='attempt-task')` with a task message that:

1. Names the issue number and title.
2. Asks the coding-lead to read the issue body, every design doc the issue links, and any acceptance criteria the issue states.
3. Asks for an `UNDERSTANDING.md` written into the worktree containing: a one-paragraph restatement of intent in the coding-lead's own words, an itemized list of acceptance criteria, the design docs consulted, and any open questions the issue does not answer.

When the coding-lead replies, `CloseConversation` on the thread to merge `UNDERSTANDING.md` into your worktree. Read it.

If the coding-lead's `UNDERSTANDING.md` lists open questions that only the originator can answer (genuinely ambiguous intent, contradiction between issue and design docs), `AskQuestion` to your originator with the questions verbatim. Wait for the answer, then `Send` the resolved guidance back into the same thread (using its `conversation_id` as `context_id`) so the coding-lead can update `UNDERSTANDING.md`.

---

**Next:** Read `phase-risk.md` in this skill directory.
