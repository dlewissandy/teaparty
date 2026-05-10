# Phase 2: Risk

Before any code lands, name what could break. The risk inventory is what later phases (tests, audit) check the change against.

`Delegate(coding-lead, <task>, skill='attempt-task')` with a task message that:

1. References `UNDERSTANDING.md` from the previous phase.
2. Asks the coding-lead to enumerate the risks the planned change carries: schema changes, runtime call paths affected, code/config that other agents read, public APIs, persisted state, security-sensitive surface.
3. Asks for a `RISKS.md` in the worktree with one entry per risk: what can go wrong, how it would be detected, what would mitigate it.

When the coding-lead replies, `CloseConversation` to merge `RISKS.md`. Read it.

If a risk is in a class only the originator can sign off on — an irreversible migration, a breaking API change, a security boundary change — escalate via `AskQuestion` before continuing. Ambiguous code-level risks are the coding-lead's call; cross-system risks are the originator's.

---

**Next:** Read `phase-tests.md` in this skill directory.
