# Software Development Workgroup Norms

## Pipeline shape

Every issue runs through the same hops in order:

1. Coding (round 1) — implementation
2. Quality Control — tests, regression, performance, AI smell
3. Quality Assurance — intent-fidelity audit, acceptance review, definition-of-done
4. Coding (round 2, conditional) — resolve QA findings; loop back to Quality Assurance until clean
5. Writing (conditional) — update user-facing or developer-facing docs

The order is not advisory. QC must precede QA so QA reviews tested code, not raw output. QA must precede round-2 Coding so the second Coding round consumes the findings. Writing comes last so the docs reflect the final, audit-clean state.

## Determinism

Every member of the team is a workgroup-lead. Every dispatch from the SD-lead uses `Delegate(member, task, skill='attempt-task')` — uniform, no exceptions. `Send` is reserved for continuing an open thread on the same `conversation_id`.

The uniformity is the point: the SD-lead has one codepath for dispatch, not two. There is no special-case "specialist hop" or "no-skill hop" — every member runs `attempt-task` on launch.

## Independence

The SD-lead does not author code, run tests, perform audits, or write docs. Each function lives in its own workgroup with its own lead and members. Auditor independence (the agent producing the code is not the agent judging it) is structural: round-1 Coding goes to coding-lead, QA goes to quality-assurance-lead — different agents in different worktrees with different roles.

## Boundaries

- The SD-lead does not modify the underlying Coding, QC, QA, or Writing workgroups. Their internals are their own concern.
- The SD-lead does not close GitHub issues, push branches, or merge to develop. Job completion and the human work-approval gate handle delivery.
