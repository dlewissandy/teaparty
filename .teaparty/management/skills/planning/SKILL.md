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
- If no plan exists at `./PLAN.md`, go to SELECT.

## SELECT

Decide whether an existing skill already describes how to do this kind of work. The frontmatter (name + description) for every available skill is already in your context — you do not need to search the filesystem. Match by description, not by name.

Never select `intent-alignment`, `planning`, or `execute` — those are CfA phase orchestrators (one of them is what you are running right now), not task skills.

- If a skill's description plausibly covers the intent, go to APPLY.
- If no skill matches (or you're unsure), go to DRAFT.

## APPLY

You have selected an existing skill to apply.

1. Read the skill's `SKILL.md` from disk to get its full body.
2. Copy the body to `./PLAN.md` as the working draft. Adapt only the parts that are intent-specific (names, paths, scope) — keep the structure intact.
3. Write `./.active-skill.json` so the orchestrator knows which skill backed this plan:

   ```json
   {
     "name": "<skill name from frontmatter>",
     "path": "<absolute path to the SKILL.md you read>",
     "scope": "<project|team>",
     "template": "<verbatim contents of the SKILL.md body you just copied — used to detect divergence at RECONCILE>"
   }
   ```

Then go to ASSERT. The skill body is the proposal; the human reviews `PLAN.md`, not the skill itself.

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
- If the human approves the plan, go to RECONCILE.
- If the dialog surfaces needed revisions, go to REVISE.
- If the conversation confirms that the intent does not capture the human's idea, go to REALIGN.
- If the conversation confirms that the human no longer wants to continue this job, go to WITHDRAW.

## RECONCILE

The plan has been approved. If you applied an existing skill at SELECT, decide what to do with any divergence the human introduced.

- If `./.active-skill.json` does not exist, you drafted from scratch — go to APPROVE.
- Otherwise read it. Compare the current `./PLAN.md` against the `template` field. If they are equivalent (modulo the intent-specific adaptations you made at APPLY), go to APPROVE.

If `PLAN.md` diverges from the template in ways that are not just intent-specific adaptation, escalate to the human via `mcp__teaparty-config__AskQuestion`:

> The approved plan diverges from skill `<name>` (at `<path>`). The differences are: `<one-paragraph summary of the substantive changes, not the local naming/scoping edits>`.
>
> How should we capture this for future use?
>
> - **generalize** — fold these changes back into the existing skill so the next task that matches it benefits from this revision.
> - **fork** — leave the original skill alone and create a new variant (a sibling skill with a more specific description) that captures this particular shape.
> - **one-off** — this revision is task-specific; don't change the skill library.

Apply the chosen action, then go to APPROVE:

- **generalize** — `Edit` the skill's `SKILL.md` body in place to absorb the substantive changes. Preserve the frontmatter unchanged.
- **fork** — `Write` a new `SKILL.md` at `<sibling-path>/SKILL.md` (pick a descriptive directory name under the same scope as the original). Reuse the original frontmatter as a starting point but rewrite the `description` so it discriminates against the original — the description is what every future planner matches against.
- **one-off** — do nothing.

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
