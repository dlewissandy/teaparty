# software-development

Per-issue orchestration of the fix-issue pipeline. Dispatch here when an open GitHub issue needs end-to-end resolution — implementation, behavior verification, intent verification, documentation, and resolution of audit findings. One lead instance per issue; parallel issues run as parallel leads.

The team is unusual: every member is itself a workgroup-lead. The software-development-lead does not author code, run tests, audit, or write docs — it decomposes the issue into uniform `Delegate(target-lead, …, skill='attempt-task')` hops and consolidates the results.

---

## software-development-lead

Receives an issue, decomposes it into per-hop tasks, and runs the pipeline:

1. **Coding** (round 1) → coding-lead
2. **Quality Control** → quality-control-lead
3. **Quality Assurance** → quality-assurance-lead
4. **Coding** (round 2, conditional) → coding-lead, if QA returned blocking findings; loop to QA until clean
5. **Writing** (conditional) → writing-lead, if the issue implies user/dev-facing documentation changes

Every hop uses `Delegate(member, task, skill='attempt-task')` — uniform, no exceptions. The skill prefix is what makes the pipeline deterministic. The lead reports completion back to the project-lead via Reply with a Deliver intent.

**Tools:** Read, Glob, Grep, Write, Edit, ListTeamMembers, Send, AskQuestion, CloseConversation, Delegate. *No Bash:* worktrees come with the dispatch, member branches merge via CloseConversation, and `commit_all_pending` runs on the lead's worktree before the originator's squash-merge — the lead has no legitimate use for raw shell.
**Skills:** attempt-task

---

## Members

This workgroup is composed entirely of other workgroup-leads:

- [coding-lead](coding.md) — implementation
- [quality-control-lead](quality-control.md) — test execution, regression, performance, AI smell
- [quality-assurance-lead](quality-assurance.md) — intent fidelity audit, acceptance review
- [writing-lead](writing.md) — documentation updates (conditional)
