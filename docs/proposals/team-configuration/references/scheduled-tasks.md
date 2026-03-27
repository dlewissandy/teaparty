# Scheduled Tasks

Scheduled tasks invoke a skill on a timer. They are defined inline in the YAML at the level they belong to.

## Definition

```yaml
scheduled:
  - name: nightly-test-sweep
    schedule: "0 2 * * *"
    skill: test-sweep
    args: "--all-projects"
    enabled: true
```

A scheduled task **must** reference a skill. No raw prompts — the skill is the contract for what the task does. If a skill doesn't exist for the desired task, the Configuration Team creates it first.

## Execution

The execution mechanism is Claude Code's `/schedule` feature (persistent scheduled triggers). Each run creates a fresh session, clones the repo, and invokes the skill. The skill defines the behavior; the schedule defines when.

## Lifecycle

- **Enabled** — fires at the scheduled time
- **Paused** — defined but not firing (human can pause from dashboard)
- **Run Now** — trigger immediately (human can run from dashboard)

The dashboard shows scheduled tasks with their skill name, schedule, last-run time, and status.

## Loops (Session-Scoped)

Claude Code also has `/loop` for session-scoped recurring tasks — e.g., "check the build every 5 minutes." These are ephemeral: they live within an active session, share session context, and die when the session ends (3-day max).

Loops are not configured in YAML. Agents or humans create them during a session when they need short-lived polling. The project lead might loop a health check while dispatches are running. The office manager might loop a status poll during a critical deployment.

The dashboard can show active loops alongside scheduled tasks when a session is running, but they are not a configuration artifact.
