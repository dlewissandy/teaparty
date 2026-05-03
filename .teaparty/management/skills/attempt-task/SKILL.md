---
name: attempt-task
description: Workgroup-lead workflow — assess a dispatched task, dispatch work units to the team via Send, assemble replies, deliver. Invoked when a workgroup-lead receives a Delegate.
user-invocable: false
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, mcp__teaparty-config__Send, mcp__teaparty-config__AskQuestion, mcp__teaparty-config__CloseConversation, mcp__teaparty-config__ListTeamMembers
---

# Attempt task

You received a Delegate. Run this workflow to completion in a single
invocation. Each terminal step ends with a `Reply` to the originator.

You dispatch to your team via `Send`, not `Delegate`. Your members
are specialists — they produce content directly with no workflow
rail at the recipient. `Delegate` is the verb a project-lead uses
to launch your workflow; you in turn launch specialists with `Send`.

## START

Read the dispatched task in your initial input. The originator named
the work, the definition of done, and the deliverable. Read any
files or paths the task references — your worktree contains
`INTENT.md`, `PLAN.md`, and any inputs the dispatcher prepared.

If the task is a status query (no work to do, just an answer), go to
ASK with the answer drafted from existing artifacts.

If the task names work to perform, go to EXECUTE.

If the task is itself a question only the originator can decide
(escalation passing through), go to ASK with the question forwarded.

## EXECUTE

You are the manager, not a primary contributor. You decompose the
task into units of work that fit a single team member's capability;
you dispatch; you assemble replies into the deliverable.

1. Call `mcp__teaparty-config__ListTeamMembers` to read your team's
   current capabilities. The roster is data on demand — read it now,
   not from memory.
2. For each unit of work, identify the team member whose capability
   covers it. A unit you would have to split across two members is
   too big — re-decompose.
3. For each unit, call `mcp__teaparty-config__Send(member, message)`
   to open a dispatch thread. Independent units run in parallel —
   Send to each in the same turn; threads run concurrently.
4. End your turn here. The runtime re-invokes you when replies
   arrive.

When members `Reply`, verify each piece against the task spec. If
satisfied, call `mcp__teaparty-config__CloseConversation` on the
thread — close is what merges the member's session branch into your
worktree. Until close, you cannot read the member's deliverables.
If a piece is unsatisfactory, call `mcp__teaparty-config__Send` on
the same thread with a correction (passing the thread's
`conversation_id` as `context_id`); return to EXECUTE when the next
reply arrives.

If a unit has no covering member at all, write `./NOFIT.md`
describing the gap and the proposed approach, then go to ASK.

When every dispatched thread is closed and the merged deliverables
are in your worktree, go to DELIVER.

If the originator's intent is unclear before you can decompose, go
to ASK.

## ASK

Conduct a dialog with the originator using
`mcp__teaparty-config__AskQuestion`. The originator is who Delegated
this task to you — typically the project-lead.

Dialog purpose: you are not certain what the originator intends, or
a unit of work has no covering member. Self-contained: the
originator hasn't seen your team's internal discussion. Name the
situation, the decision, options ruled out, and what their answer
commits them to.

When the dialog resolves the question, return to EXECUTE with the
new guidance — or, if the answer completes the task, go to DELIVER.

## DELIVER

Terminal. Two steps, in order:

1. Commit the assembled state on your session branch:
   ```bash
   git add <paths>
   git commit -m "<workgroup>: <summary>"
   ```
   Without this commit, `CloseConversation` from your originator
   merges nothing — the deliverables stay on your branch and the
   chain stalls.

2. End your turn with a final text message that carries the Deliver
   intent: name the committed paths and a one-line summary of what
   the originator is receiving. The runtime propagates that text as
   the Reply on the dispatch thread; the originator sees it as the
   signal that the work is ready.

Halt.
