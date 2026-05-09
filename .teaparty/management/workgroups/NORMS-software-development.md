# Software Development Workgroup Norms

## Pipeline shape

Every issue runs through the same four hops in order:

1. Coding (round 1) — implementation
2. Quality Control — tests, review, coverage
3. Audit — intent-fidelity check against the issue
4. Coding (round 2) — resolve audit findings; loop back to Audit until clean

The order is not advisory. Audit must see tested code, and round-2 Coding must see audit findings — re-ordering the hops invalidates both guarantees.

## Determinism

Every dispatch from the lead uses `Delegate(member, task, skill=...)`, never `Send` for opening a thread. The `skill=` argument is fixed per hop:

- `coding-lead` → `skill='attempt-task'`
- `quality-control-lead` → `skill='attempt-task'`
- `auditor` → `skill='audit-issue'`

`Send` is reserved for continuing an open thread on the same `conversation_id` (clarifications, corrections).

## Auditor independence

The auditor must not be the agent that wrote the code. The pipeline enforces this by separating the Coding hop from the Audit hop into different dispatches with different recipients. A lead that authors code itself, then audits its own diff, breaks the invariant — the audit is decorative.

## Boundaries

- The lead does not author code, write tests, or perform audits. It decomposes, delegates, merges, and decides done.
- The lead does not modify the underlying Coding, Quality Control, or Audit workgroups. Gaps in those workgroups are tracked separately.
- The lead does not close GitHub issues, push branches, or merge to develop. Job completion and the human work-approval gate handle delivery.
