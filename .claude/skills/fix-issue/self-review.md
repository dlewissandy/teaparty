# Self-Review Checklist

Before merging, re-read the issue and every relevant design doc. Then review your diff against them.

1. `gh issue view $0` — re-read the issue. Does your implementation address the **full intent**, not just the surface ask?
2. Re-read the design docs cited in Phase 1. Does your code **faithfully implement** what they specify? If you changed behavior, did you change it in the direction the design describes?
3. `git diff origin/develop...HEAD` — every change must trace to acceptance criteria. No scope creep.
4. For each function you added or modified: is it wired into its callers? Are edge cases handled? Are the tests testing the actual behavior, not a simplified version of it?
5. Fix problems before merging. Do not leave known gaps for follow-up — the issue is not done until the work is complete.

## Key constraints

- **Code conforms to design docs, not the other way around.** If your implementation diverges from a design document, fix your code. If you believe the design is wrong, escalate — do not silently edit design docs to match your code.
- **Assume you cut corners and look for where.** Agents consistently find gaps when prompted to re-check — do that re-check yourself before the human has to ask.
- **No historical artifacts.** Comments, docs, and code must describe the current system. Never write "previously X" or "used to Y" or "replaced Z" — git history is for that. If you updated a doc, delete stale descriptions rather than annotating them.
