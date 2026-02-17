# Team Workflows

Workflows give team agents a repeatable, multi-step playbook they can follow. A workflow is just a markdown file — human-readable, human-editable, stored alongside every other team file. There are no new database tables, no special runtime, no orchestrator process. Agents discover workflows through prompt context, execute them by calling tools, and track progress in a lightweight state file.

## Storage

### Workflow definitions

Workflow files live under `files/workflows/` in the team's file list. Any `.md` file in that directory (except `workflows/README.md`) is treated as a workflow. Examples from the built-in templates:

| Template   | File                              | Title             |
|------------|-----------------------------------|-------------------|
| Coding     | `workflows/code-review.md`        | Code Review       |
| Coding     | `workflows/feature-build.md`      | Feature Build     |
| Dialectic  | `workflows/structured-debate.md`  | Structured Debate |
| Roleplay   | `workflows/session-run.md`        | Session Run       |

Each file follows a conventional markdown structure:

```markdown
# Workflow Title

Description of the workflow.

## Trigger
When to activate — e.g. "When a user requests a code review."

## Steps

### 1. Step Name
- **Agent**: AgentName (or "Any", or comma-separated list)
- **Action**: What to do
- **Tools**: tool1, tool2
- **Condition**: optional guard
- **Output**: expected artifact or result
- **Goto**: N (optional: jump to step N)

### 2. Loop Step
- **Agent**: AgentName
- **Loop**: Until condition or N iterations max
  - Sub-action 1
  - Sub-action 2
- **Output**: description

### 3. Final Step
- **Agent**: AgentName
- **Action**: Wrap up
- **Completes**: Workflow done
```

Because they are ordinary team files, you can add, edit, rename, or delete workflows through the UI, through admin commands, or through agent file tools. No deploy step needed.

### Workflow state

Active progress is tracked in a single file called `_workflow_state.md`. It is **job-scoped** — each job gets its own independent state file, so the same team can run different workflows (or the same workflow at different stages) in different jobs simultaneously. In non-job conversations (e.g. agent DMs) the state file has no job scope and is shared.

A typical state file looks like:

```markdown
# Workflow State

- **Workflow**: workflows/code-review.md
- **Started**: 2024-01-15T10:30:00Z
- **Status**: in_progress
- **Current Step**: 3

## Step Log
- [x] 1. Acknowledge and Scope -- completed by Reviewer
- [x] 2. Structural Analysis -- completed by Reviewer
- [ ] 3. Implementation Review -- in_progress by Implementer
- [ ] 4. Synthesize Feedback -- pending (loop: iteration 0/3)
- [ ] 5. Present Results -- pending

## Sub-Workflow Stack
(empty)

## Notes
- Step 2 output: review-notes.md created
```

The state file is written entirely by agents — the framework does not validate or enforce its structure. This means agents can add notes, adjust the step log, or correct errors naturally.

## Auto-selection at job creation

When a new job is created (via the API, an admin command, or the coordinator's `create_job` tool), the system automatically matches the job's name and description against available workflows:

- **0 workflows** — nothing happens, no state file is created.
- **1 workflow** — it is auto-selected without an LLM call.
- **2+ workflows** — Haiku is called to match the job text against workflow triggers. If a match is found with confidence >= 0.5, that workflow is selected. Otherwise no workflow is started.

When a workflow is selected, the system creates a job-scoped `_workflow_state.md` with `Status: pending` and `Current Step: 1`. Agents see this state on the very first message and can begin following the workflow immediately, without the user needing to explicitly request it.

Auto-selection only considers shared (non-job-scoped) workflow files. The `workflows/README.md` file is excluded from consideration.

## Discovery

Agents discover workflows through two mechanisms:

### Skill context embedding

When building an agent's prompt, `_build_skill_context` scans the workgroup's workflow files for any that reference the agent by name. Matching workflows are embedded in the prompt under "Available Skills", giving the agent awareness of its role in workflows without any framework orchestration.

### Workflow tools

Three tools give agents direct access to workflow state:

#### `list_workflows`

Lists all `workflows/*.md` files (excluding README) with extracted titles and trigger summaries. An agent calls this to discover what workflows exist. Takes no parameters.

#### `get_workflow_state`

Reads `_workflow_state.md` for the current conversation scope. Returns the file content, or `"No active workflow."` if no state file exists. Takes no parameters.

#### `advance_workflow`

Creates or updates `_workflow_state.md` with new content. Takes a single required parameter `state_content` — the full markdown body of the state file. This is how agents:

- **Start** a workflow (create initial state with step 1 in progress)
- **Advance** to the next step (update the step log, bump current step)
- **Record loop iterations** (increment iteration counts)
- **Mark completion** (set status to `completed`)

Because `advance_workflow` does a full-file replacement (not a diff), concurrent writes use last-write-wins semantics. This is safe because workflow state is not diffed or merged — each update is a self-consistent snapshot.

## Execution

Execution is entirely agent-driven. There is no framework-level orchestration — agents read workflow definitions, decide what to do, and manage their own state.

### Typical execution flow

1. User posts a message that matches a workflow trigger ("Let's do a code review").
2. Agent sees the workflow in its skill context or calls `list_workflows` to discover it.
3. Agent calls `advance_workflow` to create `_workflow_state.md` with step 1 as `in_progress`.
4. Agent executes step 1 (e.g., reads files, posts scope summary).
5. Agent calls `advance_workflow` to mark step 1 complete and step 2 as `in_progress`.
6. On subsequent turns, agents see the active state and continue from the current step.
7. Loop steps are iterated by the assigned agent, incrementing the iteration count each time.
8. `Goto` steps redirect to an earlier step number instead of advancing sequentially.

Agents can also read the full workflow definition (using `read_file` on the workflow path) if they need to consult step details beyond what's in the state summary.

## Scope: Team Workflows vs. Cross-Team Orchestration

Workflows as defined here are **single-team playbooks**. All agents named in a workflow belong to the same team and operate on the same files.

Cross-team orchestration (e.g. the coordinator dispatching jobs to multiple teams and sequencing their work) is a different mechanism — it uses the **orchestration toolkit** (`create_job`, `list_team_jobs`, `read_job_status`, etc.) rather than workflows. See [engagements.md](engagements.md) for the cross-team model.

The two can compose: the coordinator dispatches a job to a team, and that team's agents execute a workflow within the job. The coordinator doesn't need to know about the team's internal workflow — it just sees job status.

## Termination

There is no framework-level workflow terminator. Workflows end when:

- **An agent marks the final step complete.** The convention is for the last step to include `- **Completes**: Workflow done.` The agent calls `advance_workflow` with `- **Status**: completed` in the state file.

- **A user explicitly redirects.** If the user asks to stop or start something different, agents recognize this and either reset the state or leave it.

- **The state file is deleted.** Calling `delete_file` on `_workflow_state.md` removes all workflow tracking. The next turn sees "No active workflow."

Completed state files persist until deleted, so agents (and users) can review what happened. There is no automatic cleanup.

## Human interruption

Workflows are not modal — they don't lock a conversation into a fixed script. Human messages are processed normally at every turn. Agents see workflow context alongside the human's message and decide how to handle both:

- If the message is on-topic for the current step, the agent incorporates it and continues.
- If the message asks to skip ahead, the agent can advance multiple steps.
- If the message is unrelated, the agent can respond to it normally and resume the workflow on the next turn.
- If the message asks to stop or change course, the agent can update or clear the state.

The workflow is advisory, not mandatory. An agent that judges a human's question to be more important than the next workflow step will simply address the question first.

### Missing assigned agent

If a step names a specific agent but that agent does not respond, any agent can pick up the step. The `- **Agent**: AgentName` field is a suggestion, not a hard constraint.

### Corrupted state

If the state file contains garbled or inconsistent content, the next `advance_workflow` call overwrites it entirely with a corrected version. Since the tool does a full replacement, there is no accumulation of corruption — each write is a clean slate.
