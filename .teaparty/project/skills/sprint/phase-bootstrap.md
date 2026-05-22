# Phase 1: Bootstrap

Build the local sprint cache. One dispatch.

`Delegate(scrum-master, "Plan the sprint for milestone {milestone}.", skill='sprint-plan', args={milestone: <milestone>})`.

When the scrum-master replies, `CloseConversation` on the thread to merge the cache into your worktree. The cache lives at `.teaparty/project/sprint/{sprint.yaml, index.md, issues/{N}.md}`.

If the scrum-master's reply says the cache already exists (the `sprint-plan` guard refused), do **not** re-bootstrap. Treat the existing cache as authoritative and proceed.

If the scrum-master escalates that the milestone does not match anything on GitHub, halt and `AskQuestion` to the human originator with the list of available milestones.

---

**Next:** Read `phase-triage.md` in this skill directory.
