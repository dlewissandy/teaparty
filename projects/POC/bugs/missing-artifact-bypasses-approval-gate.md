# BUG: Missing artifact silently bypasses approval gate

**Discovered:** 2026-03-12, session 20260312-221105 (hierarchical-memory-paper)
**Severity:** High — defeats the human-in-the-loop safety mechanism
**Component:** `orchestrator/actors.py`, `AgentRunner._interpret_output()`

## Observed behaviour

When an agent completes a phase (intent or planning) without producing the expected artifact file (e.g., `INTENT.md` or `PLAN.md`), the `AgentRunner._interpret_output()` method falls through to a default `auto-approve` action. This bypasses the `ApprovalGate` entirely — the human proxy model is never consulted, and the session advances to the next phase without any review.

## Reproduction

In session 20260312-221105, the user provided a detailed `ham-idea.md` document that effectively served as both intent and plan. The intent and planning agents read the document and proceeded to execution without writing separate `INTENT.md` or `PLAN.md` artifacts. As a result:

1. The intent agent completed without producing `INTENT.md`.
2. `_interpret_output()` found no artifact and no escalation file.
3. It returned `ActorResult(action='auto-approve')`, which `_resolve_action()` mapped to the first forward-advancing CfA transition.
4. The `ApprovalGate` was never invoked.
5. The same sequence repeated for the planning phase.

The session log confirms both phases were auto-approved without gate consultation:
```
[22:11:40] STATE  | PROPOSAL → INTENT [auto-approve]
[22:12:35] STATE  | DRAFT → PLAN [auto-approve]
```

## Why this matters

The proxy model for `INTENT_ASSERT|hierarchical-memory-paper` had an EMA approval rate of 0.182 — far below the 0.80 auto-approve threshold. It also had 6 recorded corrections out of 12 total observations, with substantive text differentials capturing the user's standards. Had the gate been consulted, it would have escalated to the human.

The approval gate is the primary mechanism for human oversight of agent work. Bypassing it based on the absence of an artifact file means the gate only functions when the agent happens to follow the expected output convention. An agent that does meaningful work but skips the artifact — whether by design, prompt interpretation, or error — receives no human review at all.

## Scope

This affects all three approval states (`INTENT_ASSERT`, `PLAN_ASSERT`, `WORK_ASSERT`) equally. Any phase where the agent does not produce the configured artifact file will bypass the gate via the same code path.

The bug is in the fallback logic of `_interpret_output()` (actors.py lines 148-150):

```python
# Agent produced output but no artifact or escalation — auto-approve
action = self._resolve_action(ctx.state, 'auto-approve')
return ActorResult(action=action, data=data)
```

## Related

A second, cosmetic issue exists in the resume path: when a crashed session resumes mid-execution, `Orchestrator.run()` re-enters the phase loop from the top. The planning phase detects the CfA state belongs to execution and exits immediately, but still emits `PHASE_STARTED` / `PHASE_COMPLETED` events, producing misleading log entries. This is cosmetic — no gates are actually skipped on resume — but it obscures diagnosis of the real bypass described above.
