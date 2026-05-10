# Phase 5: Dispatch

Hand Tier 1 Approved issues to the software-development workgroup. Independent issues run in parallel.

## What to do

For each Tier 1 issue currently `Approved` and not already in flight:

1. `Delegate(scrum-master, "Mark issue #N In Progress.", skill='mark-in-progress', args={issue_number: N})`. `CloseConversation` on its reply.
2. `Delegate(software-development-lead, "Resolve issue #N end-to-end.", skill='fix-issue', args={issue_number: N})`. Reference the issue body from `.teaparty/project/sprint/issues/{N}.md` so the dev-lead has the planning-time snapshot in hand.

Open both threads in parallel — and across multiple issues, open all the dispatches in the same turn. Independent issues should not wait on each other.

End your turn here. The runtime re-invokes you when replies arrive.

## When a software-development-lead replies

For each `fix-issue` reply that comes back:

1. Read the reply. The dev-lead reports the issue number, a verdict, and the paths it touched.
2. If the verdict is the work-completed signal, `Delegate(scrum-master, "Mark issue #N Done.", skill='mark-done', args={issue_number: N})`, then `CloseConversation` on the dev-lead thread once the mark-done reply lands.
3. If the dev-lead escalated (asked you a question via `AskQuestion`, or replied with an unresolved blocker), do not mark Done. Conduct the escalation dialog with the human via `AskQuestion`, then either re-dispatch with new guidance using `Send` on the same thread, or close the thread and route the issue back through triage with a note about why it stalled.

When every dispatched fix-issue thread for this wave is closed, return to triage to decide whether more issues are ready, or whether the sprint is over.

---

**Next:** Read `phase-triage.md` in this skill directory.
