# Phase 6: Self-review

The coding-lead re-reads its own work against the spec before the QA audit. Self-review consistently catches gaps that survive the implementer's first pass.

`Delegate(coding-lead, <task>, skill='attempt-task')` with a task message that:

1. References the issue, `UNDERSTANDING.md`, the design docs, and `RESOLUTION.md`.
2. Asks the coding-lead to re-read all of the above and answer, in writing, whether the implementation faithfully delivers what the issue and design docs ask for. Specifically:
   - Is each acceptance criterion satisfied by the named file:line?
   - Is the feature traceable end-to-end, not just present in code?
   - Are there hidden assumptions in the implementation that the issue does not authorize?
   - Are there cleanup items the coding-lead noticed but did not finish?
3. Asks for a `SELF-REVIEW.md` in the worktree with the answers and a self-verdict: `READY`, `GAPS` (with a list), or `BLOCKED` (with what is blocking).

When the coding-lead replies, `CloseConversation` to merge `SELF-REVIEW.md`. Read the verdict.

- **READY** — proceed to audit.
- **GAPS** — `Send` the gap list back into the same thread; coding-lead resolves; loop until self-verdict is `READY`.
- **BLOCKED** — escalate via `AskQuestion`; resume self-review only after the originator clears the block.

The coding-lead is encouraged to push back on the spec at this stage if they discovered something that genuinely changes the picture. Push-back is a signal, not an obstacle — escalate it to the originator rather than dismiss it.

---

**Next:** Read `phase-audit.md` in this skill directory.
