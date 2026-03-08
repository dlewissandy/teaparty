# Pre-Mortem Risk Assessment

Imagine the task has been completed and it went badly wrong. What happened?

## Argument

The task to assess: `/premortem "migrate the database to PostgreSQL"`

## What To Do

1. **Read context** — check for `MEMORY.md` and `ESCALATION.md` in the current project directory for prior learnings and calibration data.
2. **Imagine failure.** The task is done. It went wrong. Identify 3-6 specific, concrete risks.
3. **Be specific.** Not "communication problems" but "writing team produces content in wrong register because audience was not specified in the task brief."

## Output Format

For each risk:

```
## Risk N: <concrete name>
**Likelihood:** High | Medium | Low
**Impact:** High | Medium | Low
**Description:** What specifically could go wrong.
**Mitigation:** Concrete action to take before or during execution.
```

## Lessons From Prior Pre-Mortems

- Pre-mortems work when **specific** (named test cases, decision verification points), not generic ("could have communication issues").
- Mitigations only help if **actually executed** — flag the ones that need to be checked at specific milestones.
- Permission friction and scope drift are the two most common failure modes in this project. Always check for them.
