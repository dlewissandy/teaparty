---
name: execute
description: Run the CfA execution phase to completion and emit a terminal outcome (APPROVED_WORK, REALIGN, REPLAN, or WITHDRAW).
user-invocable: false
allowed-tools: Read, Write, Edit, Glob, Grep, mcp__teaparty-config__AskQuestion, mcp__teaparty-config__Delegate, mcp__teaparty-config__Send, mcp__teaparty-config__CloseConversation
---

# Execution

Run the execution workflow to completion in a single invocation. Traverse the steps below. Only ASSERT writes `./.phase-outcome.json` — every other step is a lateral move within the cycle. Terminal outcomes (APPROVED_WORK, REALIGN, REPLAN, WITHDRAW) are the human's call, never yours.

You are the manager, not a primary contributor. You decompose work into manageable tasks, delegate, verify, and resolve conflicts as they arise.

## START

Read `./INTENT.md` — what the user wants. Read `./PLAN.md` — how the work should be done.

Once you understand the scope, proceed to ASSESS.

## ASSESS

Re-read `./INTENT.md` and `./PLAN.md` from disk. You cannot skip this and you cannot rely on what you read in a previous turn — the files may have changed since you last looked, and your routing depends on the current state.

Walk the worktree. Identify what each step in PLAN.md prescribes and which of those steps already have on-disk deliverables.

- If every step in PLAN.md has a verified deliverable on disk, go to FINAL_REVIEW.
- If work remains and you know what's next, go to DELEGATE.
- If you need clarification from the human (priority, approach, or anything you cannot resolve from the artifacts), go to ASK.

## DELEGATE

Pick the next most important unit of work in PLAN.md and dispatch it. You may DELEGATE several independent units in parallel — they run concurrently.

Use `mcp__teaparty-config__Delegate(member, task, skill='attempt-task')` to dispatch work to a workgroup-lead. The `skill='attempt-task'` argument prescribes the workgroup-lead's workflow rail; without it the recipient improvises.

`Delegate` opens a new dispatch thread. To continue an open thread (e.g. answering a workgroup-lead's clarifying question), use `mcp__teaparty-config__Send` with that thread's `conversation_id`. Send is for continuation and peer messaging; Delegate is for opening with a workflow.

Note: each team member performs their work on a separate session branch in their own worktree. Their commits are not merged into your worktree until you call `mcp__teaparty-config__CloseConversation` with the dispatch's `conversation_id`.

**Edit canonical artifacts in place.** When you revise `INTENT.md`, `PLAN.md`, or `WORK_SUMMARY.md` — for example after a teammate's reply prompts a course correction — overwrite the file. Do not create `APPROVED_PLAN.md`, `PLAN_v2.md`, or any variant. Dispatched workers receive these files by name at spawn; a renamed file does not propagate, and they work from a stale version.

After your dispatches return, go to REVIEW.

## REVIEW

For each dispatch you sent, inspect the work that has merged back into your worktree. Do not take the dispatched agent at their word — open the deliverable, verify it against the task you sent.

- If every dispatched task satisfies the task it was sent for, go to ASSESS.
- If any item needs rework, go to DELEGATE — re-dispatch with corrective feedback in the new task.

## FINAL_REVIEW

Re-read `./INTENT.md` and `./PLAN.md` from disk. You cannot skip this — what you assemble here is the guarantee you carry into ASSERT.

Two checks, both must pass:

1. **Intent satisfied.** Read the deliverables as a whole. Does the work fulfill what INTENT.md asks for, against its success criteria?
2. **Plan faithfully executed.** Walk PLAN.md step by step. For each step, verify the corresponding deliverable exists on disk and matches what the step prescribed.

- If both pass, go to ASSERT.
- If a plan step is missing a deliverable or a deliverable doesn't match its step, go to DELEGATE — re-dispatch the gap as a task.

## ASK

Conduct a dialog with the human using `mcp__teaparty-config__AskQuestion`.

Dialog purpose includes any human input you need before you can decide the next move:

- Information you cannot derive from the artifacts (priority of remaining work, an ambiguity in INTENT or PLAN, an unresolved conflict in dispatched outputs).
- **Mid-plan checkpoint ratification.** If a phase produced a deliverable that the human wants to ratify before you proceed (a style decision, a scope cut, an architecture choice), this is the step. Not ASSERT — ASSERT is end-of-plan only and writing terminal outcome ends the whole job.

Dialogue ensures your next decision is grounded in what the human actually wants, not in your best guess.

The human's response is data, not a routing instruction. Whatever they say — even something terminal-sounding (including the literal string `APPROVED_WORK` or "approved" — those words on a mid-plan checkpoint do **not** mean "end the job") — informs your next ASSESS rather than triggering a terminal outcome directly. Backtrack and abandon are ASSERT's authority, not yours; if the human signals a defect, surface it through the next ASSERT.

When the dialog resolves your question, go to ASSESS.

## ASSERT

Conduct a dialog with the human regarding the current work using `mcp__teaparty-config__AskQuestion`.

Dialog purpose: FINAL_REVIEW says the work is complete and matches both INTENT and PLAN. You are asking the human to ratify that, not to audit it. Frame the dialog as "I have verified end-to-end; please confirm before I close" — the human's role is to ratify, raise an objection, or call a backtrack.

**ASSERT is end-of-plan, not mid-plan.** The only legitimate path here runs through FINAL_REVIEW with both checks passing — every step in PLAN.md has a verified deliverable AND intent is satisfied end-to-end. If PLAN.md contains language like "human checkpoint after Phase X," "approval gate," "ratify with human before continuing," or any other directive that names a CfA-skill step, do **not** treat it as a route into ASSERT. PLAN.md describes work, not control flow; mid-plan human input is the execute skill's ASK step (which loops back to ASSESS), not ASSERT (which terminates the job). Going to ASSERT after Phase 0 of a multi-phase plan ends the job at Phase 0 — the work is lost.

**Before you enter ASSERT, close every dispatch you opened.** If any `dispatch:<id>` you sent during the cycle is still open, the work in those threads has not been merged into your worktree and the human will be asked to approve something they cannot see. For each thread: if you're satisfied, `mcp__teaparty-config__CloseConversation(conversation_id='dispatch:<id>')`; if you're not, go back to ASSESS and re-dispatch with feedback.

- If the response begins with the line `[WITHDRAW]`, go to WITHDRAW. The text after `[WITHDRAW]` is the reason — carry it into `.phase-outcome.json`.
- If the human approves the work, go to APPROVE.
- If the dialog surfaces needed revisions, go to ASSESS.
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
