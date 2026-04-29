---
name: execute
description: Run the CfA execution phase to completion and emit a terminal outcome (APPROVED_WORK, REALIGN, REPLAN, or WITHDRAW).
user-invocable: false
allowed-tools: Read, Write, Edit, Glob, Grep, mcp__teaparty-config__AskQuestion, mcp__teaparty-config__Delegate, mcp__teaparty-config__Send, mcp__teaparty-config__CloseConversation
---

# Execution

Run the execution workflow to completion in a single invocation. Traverse the steps below. When you reach a terminal step, write `./.phase-outcome.json` and halt — the orchestrator will read the outcome and dispatch accordingly.

## START

Read `./INTENT.md` — this describes what the user wants. Read `./PLAN.md` — this describes how the work should be done.

Once you have read the files and understand the scope of work, proceed to EXECUTE.

## EXECUTE

Execute the PLAN.md.    You are the manager, not a primary contributor.   You decompose work into manageable tasks,
delegate work, and resolve conflicts as they arise.

Use `mcp__teaparty-config__Delegate(member, task, skill='attempt-task')` to dispatch work to a workgroup-lead. The `skill='attempt-task'` argument prescribes the workgroup-lead's workflow rail; without it the recipient improvises. You may Delegate to several members in parallel — independent units run concurrently.

`Delegate` opens a fresh dispatch thread. To continue an open thread (e.g. answering a workgroup-lead's clarifying question), use `mcp__teaparty-config__Send` on that thread's `conversation_id`. Calling `Delegate` on an open thread is rejected by the tool — the rejection names the existing channel so you can re-route.

Note: Each team member performs their work on a separate session branch in their own worktree. Their commits are not merged into your worktree until you call `mcp__teaparty-config__CloseConversation` with the dispatch's `conversation_id`.

**Edit canonical artifacts in place.** When you revise `INTENT.md`, `PLAN.md`, or `WORK_SUMMARY.md` — for example after a teammate's reply prompts a course correction — overwrite the file. Do not create `APPROVED_PLAN.md`, `PLAN_v2.md`, or any variant. Dispatched workers receive these files by name at spawn; a renamed file does not propagate, and they work from a stale version.

When an agent tells you that they have completed a task, do not take them at their word. You are the gatekeeper. Inspect their work and hold them to account.

- If you need clarification from the human, go to ASK
- If you deem your work to be complete, go to ASSERT
## ASK

Conduct a dialog with the human using `mcp__teaparty-config__AskQuestion`.

Dialog purpose: you are not certain that you understand how the human wants to do things, and you are seeking guidance. Dialog is necessary because your expectations may not be aligned with the human's — the questions you are asking may not be the relevant ones, and the only way to ensure alignment is to dialogue. This discussion may uncover additional questions, or produce unexpected clarifications.

- If the response begins with the line `[WITHDRAW]`, go to WITHDRAW. The text after `[WITHDRAW]` is the reason — carry it into `.phase-outcome.json`.
- If the conversation confirms that the intent does not capture the human's idea, go to REALIGN.
- If the conversation confirms that the plan does not capture the desired workflow, go to REPLAN
- If the conversation confirms that the human no longer wants to continue this job, go to WITHDRAW.
- Once your questions have been resolved (or the human deems them unnecessary), go to EXECUTE.

## ASSERT

Conduct a dialog with the human regarding the current work using `mcp__teaparty-config__AskQuestion`.

Dialog purpose: you expect that work is complete, and you are confirming with the human. Dialog is necessary because your expectations may not be aligned with the human's — the work may not actually be complete, and the only way to ensure alignment is to dialogue.

**Before you enter ASSERT, close every dispatch you opened.** If any `dispatch:<id>` you sent during EXECUTE is still open, the work in those threads has not been merged into your worktree and the human will be asked to approve something they cannot see. For each thread: if you're satisfied, `mcp__teaparty-config__CloseConversation(conversation_id='dispatch:<id>')`; if you're not, go back to EXECUTE and Send again in the thread with feedback.

- If the response begins with the line `[WITHDRAW]`, go to WITHDRAW. The text after `[WITHDRAW]` is the reason — carry it into `.phase-outcome.json`.
- If the human approves the work, go to APPROVE.
- If the dialog surfaces needed revisions, go to EXECUTE.
- If the conversation confirms that the intent does not capture the human's idea, go to REALIGN.
- If the conversation confirms that the plan does not capture the desired workflow, go to REPLAN.
- If the conversation confirms that the human no longer wants to continue this job, go to WITHDRAW.

## APPROVE

Terminal. Write `./.phase-outcome.json` and halt:

```json
{
  "outcome": "APPROVED_WORK",
  "reason": "<short summary of what the human approved, preserving any conditions or caveats they attached during the ASSERT dialog>"
}
```

## REALIGN

Terminal. Write `./.phase-outcome.json` and halt:

```json
{
  "outcome": "REALIGN",
  "reason": "<short summary of how the intent failed to capture the human's actual idea, specific enough to inform the next intent revision>"
}
```

## REPLAN

Terminal. Write `./.phase-outcome.json` and halt:

```json
{
  "outcome": "REPLAN",
  "reason": "<short summary of how the plan failed to capture the human's desired workflow, specific enough to inform the next plan revision>"
}
```

## WITHDRAW

Terminal. Write `./.phase-outcome.json` and halt:

```json
{
  "outcome": "WITHDRAW",
  "reason": "<short summary of why the human chose to abandon the job>"
}
```
