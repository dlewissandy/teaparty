# Phase 7: Audit

Independent intent-fidelity check. The QA lead has not seen the fix from the inside; they read the issue, the design docs, and the diff, and answer whether the diff delivers what the issue is actually asking for.

`Delegate(quality-assurance-lead, <task>, skill='attempt-task')` with a task message that:

1. Names the issue number and references `UNDERSTANDING.md`, `RISKS.md`, `RESOLUTION.md`, `SELF-REVIEW.md`, and any acceptance criteria the quality-control-lead flagged as inspection-only in the tests phase.
2. Asks the QA lead to perform an intent-fidelity audit: not a code-quality review, an "is this what the issue asked for?" check.
3. Asks for an `AUDIT.md` in the worktree with findings (intent statements about what the diff does and does not deliver) and a verdict — exactly one of `COMPLETE`, `PARTIAL`, or `WRONG DIRECTION`.

When the QA lead replies, `CloseConversation` to merge `AUDIT.md`. Read the verdict.

## Routing on the verdict

- **COMPLETE** — DELIVER. Compose the final reply: issue number, `COMPLETE`, list of paths the originator should look at (`UNDERSTANDING.md`, the implementation, the tests, `AUDIT.md`). End your turn with the Deliver-intent text. Halt.

- **PARTIAL** — the audit names what is missing. Do not stop. Do not create new tickets to defer. Go back to `phase-fix.md` and re-run with the audit findings as additional task input. After the second resolution + self-review completes, return here for a re-audit.

  **Two rounds maximum.** If you reach this phase a third time and the verdict is still not `COMPLETE`, escalate via `AskQuestion` rather than launching a third fix round.

- **WRONG DIRECTION** — the implementation does not solve the issue's actual problem. `AskQuestion` to your originator with the QA findings and halt. Do not iterate; this is a scoping decision.

If the QA lead's reply is not in `{COMPLETE, PARTIAL, WRONG DIRECTION}`, treat it as a malformed verdict — `Send` a correction back to the same thread asking for the verdict in the contracted form.

---

**Next on COMPLETE:** DELIVER and halt.
**Next on PARTIAL (round 1):** Read `phase-fix.md` in this skill directory.
**Next on PARTIAL (round 2 still not COMPLETE):** Escalate via `AskQuestion` and halt.
**Next on WRONG DIRECTION:** Escalate via `AskQuestion` and halt.
