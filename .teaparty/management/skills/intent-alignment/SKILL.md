---
name: intent-alignment
description: Run the CfA intent-alignment phase to completion — produce or align INTENT.md from IDEA.md, dialog with the human, and emit a terminal outcome (APPROVED_INTENT or WITHDRAW).
user-invocable: false
allowed-tools: Read, Write, Edit, Glob, Grep, mcp__teaparty-config__AskQuestion
---

# Intent Alignment

Run the intent-alignment workflow to completion in a single invocation. Traverse the steps below. When you reach a terminal step, write `./.phase-outcome.json` and halt — the orchestrator will read the outcome and dispatch accordingly.

## What a good INTENT.md captures

INTENT.md captures the **what** and the **why** behind the user's idea — not the how (that is planning's job). A good INTENT.md reads unambiguously to someone who was not privy to this conversation: a stranger could pick it up and understand what the user wants and why, without needing to reconstruct the dialog that produced it.

## START

Read `./IDEA.md`. You cannot skip this because the idea may have changed since the last time you read it.

- If `./INTENT.md` exists, go to ALIGN.
- If no intent exists at `./INTENT.md`, go to DRAFT.

## DRAFT

Generate an intent that could reasonably capture the idea.

- If after drafting, you are still uncertain that you have captured the intent behind the user's idea, go to ASK.
- If you are certain that you have captured the intent behind the user's idea, go to ASSERT.

## ALIGN

Re-read `./INTENT.md` from disk. It may have changed since the last time you read it.

Compare the intent against the current idea. Identify which parts still serve it, which parts are now obsolete, and which gaps have opened. Reconstruct the intent around what survives. The prior intent is evidence of past thinking, not a scaffold you must preserve.

- If after aligning, you are still uncertain that you have captured the intent behind the user's idea, go to ASK.
- If you are certain that you have captured the intent behind the user's idea, go to ASSERT.

## ASK

Conduct a dialog with the human using `mcp__teaparty-config__AskQuestion`.

Dialog purpose: you are not certain that you understand what the human actually wants, and you are seeking guidance. Dialog is necessary because your expectations may not be aligned with the human's — the questions you are asking may not be the relevant ones, and the only way to ensure alignment is to dialogue. This discussion may uncover additional questions, or produce unexpected clarifications.

- If the response begins with the line `[WITHDRAW]`, go to WITHDRAW. The text after `[WITHDRAW]` is the reason — carry it into `.phase-outcome.json`.
- If the conversation confirms that the human no longer wants to continue this job, go to WITHDRAW.
- Once your questions have been resolved (or the human deems them unnecessary), go to REVISE.

## REVISE

Re-read `./INTENT.md` from disk. It may have changed since the last time you read it.

Integrate the refinements from the preceding dialog. The idea is stable and the intent's overall shape is sound, so edit locally rather than rebuilding. If you're rewriting more than a section or two, you're probably in ALIGN (idea drift), not REVISE — surface this rather than silently restructuring.

**Edit `./INTENT.md` in place.** Do not write `APPROVED_INTENT.md`, `INTENT_v2.md`, `INTENT_REVISED.md`, or any other variant. The next CfA state and any dispatched workers receive `INTENT.md` by name; renaming or duplicating defeats that copy and they work from a stale version. Git tracks the file's history; you do not need a new filename to preserve previous content.

- If after revising, you are still uncertain that you have captured the intent behind the user's idea, go to ASK.
- If you are certain that you have captured the intent behind the user's idea, go to ASSERT.

## ASSERT

Conduct a dialog with the human regarding the current draft of the intent using `mcp__teaparty-config__AskQuestion`.

Dialog purpose: you expect that `INTENT.md` is complete, and you are confirming with the human. Dialog is necessary because your expectations may not be aligned with the human's — the intent may not actually be complete, and the only way to ensure alignment is to dialogue.

- If the response begins with the line `[WITHDRAW]`, go to WITHDRAW. The text after `[WITHDRAW]` is the reason — carry it into `.phase-outcome.json`.
- If the human approves the intent, go to APPROVE.
- If the dialog surfaces needed revisions, go to REVISE.
- If the conversation confirms that the human no longer wants to continue this job, go to WITHDRAW.

## APPROVE

Terminal. Write `./.phase-outcome.json` and halt:

```json
{
  "outcome": "APPROVED_INTENT",
  "reason": "<short summary of what the human approved, preserving any conditions or caveats they attached during the ASSERT dialog>"
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
