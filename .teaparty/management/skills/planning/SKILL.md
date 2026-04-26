---
name: planning
description: Run the CfA planning phase to completion — produce or align PLAN.md, dialog with the human, and emit a terminal outcome (APPROVED_PLAN, REALIGN, or WITHDRAW).
user-invocable: false
allowed-tools: Read, Write, Edit, Glob, Grep, mcp__teaparty-config__AskQuestion
---

# Planning

Run the planning workflow to completion in a single invocation. Traverse the steps below. When you reach a terminal step, write `./.phase-outcome.json` and halt — the orchestrator will read the outcome and dispatch accordingly.

## START

Read `./INTENT.md`. You cannot skip this because the intent may have changed since the last time you read it.

- If `./PLAN.md` exists, go to ALIGN.
- If no plan exists at `./PLAN.md`, go to DRAFT.

## DRAFT

Generate a plan that could reasonably produce the intent.

- If you have strategic questions on how your plan should produce the intent, go to ASK.
- If you have no strategic questions on how your plan should produce the intent, go to ASSERT.

## ALIGN

Re-read `./PLAN.md` from disk. It may have changed since the last time you read it.

Compare the plan against the current intent. Identify which parts still serve it, which parts are now obsolete, and which gaps have opened. Reconstruct the plan around what survives. The prior plan is evidence of past thinking, not a scaffold you must preserve.

- If after aligning the plan you have strategic questions on how your plan should produce the intent, go to ASK.
- If you have no strategic questions on how your plan should produce the intent, go to ASSERT.

## ASK

Conduct a dialog with the human using `mcp__teaparty-config__AskQuestion`.

Dialog purpose: you are not certain that you understand how the human wants to do things, and you are seeking guidance. Dialog is necessary because your expectations may not be aligned with the human's — the questions you are asking may not be the relevant ones, and the only way to ensure alignment is to dialogue. This discussion may uncover additional questions, or produce unexpected clarifications.

- If the response begins with the line `[WITHDRAW]`, go to WITHDRAW. The text after `[WITHDRAW]` is the reason — carry it into `.phase-outcome.json`.
- If the conversation confirms that the intent does not capture the human's idea, go to REALIGN.
- If the conversation confirms that the human no longer wants to continue this job, go to WITHDRAW.
- Once your questions have been resolved (or the human deems them unnecessary), go to REVISE.

## REVISE

Re-read `./PLAN.md` from disk. It may have changed since the last time you read it.

Integrate the refinements from the preceding dialog. The intent is stable and the plan's overall shape is sound, so edit locally rather than rebuilding. If you're rewriting more than a section or two, you're probably in ALIGN (intent drift), not REVISE — surface this rather than silently restructuring.

- If in rewriting you discover that you have strategic questions on how your plan should produce the intent, go to ASK.
- If you have no strategic questions on how your plan should produce the intent, go to ASSERT.

## ASSERT

Conduct a dialog with the human regarding the current draft of the plan using `mcp__teaparty-config__AskQuestion`.

Dialog purpose: you expect that `PLAN.md` is complete, and you are confirming with the human. Dialog is necessary because your expectations may not be aligned with the human's — the plan may not actually be complete, and the only way to ensure alignment is to dialogue.

- If the response begins with the line `[WITHDRAW]`, go to WITHDRAW. The text after `[WITHDRAW]` is the reason — carry it into `.phase-outcome.json`.
- If the human approves the plan, go to APPROVE.
- If the dialog surfaces needed revisions, go to REVISE.
- If the conversation confirms that the intent does not capture the human's idea, go to REALIGN.
- If the conversation confirms that the human no longer wants to continue this job, go to WITHDRAW.

## APPROVE

Terminal. Write `./.phase-outcome.json` and halt:

```json
{
  "outcome": "APPROVED_PLAN",
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

## WITHDRAW

Terminal. Write `./.phase-outcome.json` and halt:

```json
{
  "outcome": "WITHDRAW",
  "reason": "<short summary of why the human chose to abandon the job>"
}
```
