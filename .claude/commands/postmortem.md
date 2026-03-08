# Failure Post-Mortem

Analyze what went wrong in a failed task or session and produce a structured failure report.

## Argument

Either a session directory path or a description of what failed: `/postmortem "the coding team crashed during execution"`

## What To Do

1. **Gather evidence.** Look for these artifacts in the session/working directory:
   - Stream JSONL files (`.exec-stream.jsonl`, `.plan-stream.jsonl`, `.intent-stream.jsonl`) — scan for error events, permission denials, tool failures.
   - `session.log` — look for lines containing: failure, failed, error, blocked, withdrawn, backtrack, denied, permission, TASK_ESCALATE.
   - `.cfa-state.json` — what state was the CfA machine in when it failed?
   - Sentinel files: `.failure-reason`, `.task-escalation.md`, `.backtrack-feedback.txt`, `.plan-escalation.md`, `.intent-escalation.md`.
   - Subteam `.result.json` files — check for non-zero exit codes or failed statuses.

2. **Classify the failure** into one of:
   - **permission** — agent couldn't do what the plan required because the execution environment blocked it.
   - **stall** — agent produced no output for an extended period (watchdog killed it).
   - **infrastructure** — agent crashed (non-zero exit, OOM, signal).
   - **subteam** — a delegated subteam failed.

3. **Compose the report** with these sections:

## Report Structure

```markdown
# Failure: <one-line summary>

Phase: <intent|planning|execution> | Agent: <name> | Exit: <code> | State: <CfA state>

## What Failed
2-3 sentences at human-concern level. What was the agent doing? What stopped it?

## Evidence
Bullet list of file paths + line numbers pointing to specific error locations.
Never embed log blocks or raw JSON — point to the file and line.

## What This Reveals
Structural analysis: why did this failure happen? Not "the agent crashed" but
"the permission model and the approved plan disagree — the plan was approved
by the human but the execution environment blocked commands the plan required."

## Open Questions
2-3 specific questions that would help diagnose the root cause.

## Reproduction
Task text, agent config, permission mode, working directory — enough to reproduce.
```

## Key Principle

Evidence pointers, not embedded dumps. The report should point to where the evidence is (`stream.jsonl line 47 — permission denied: Write`), not paste the evidence inline. This keeps the report scannable and the evidence auditable.
