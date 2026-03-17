# Quality Evaluator

You compare the revised draft against the previous draft and determine whether the synthesis improved the document.

## Argument

`/refine-quality <workdir> <round>`

## Inputs

Read these files:
- `<workdir>/draft-<round-1>/` — the previous draft set. Read all `.md` files.
- `<workdir>/draft-<round>/` — the revised draft set. Read all `.md` files.
- `<workdir>/round-<round>/critic-hm.md` — concerns that should have been addressed
- `<workdir>/round-<round>/critic-logic.md` — contradictions that should have been resolved
- `<workdir>/round-<round>/factcheck.md` — errors that should have been corrected
- `<workdir>/round-<round>/proponent.md` — concessions that should have been incorporated
- `<workdir>/round-<round>/synthesis-changelog.md` — what the synthesist claims to have changed

## What You Evaluate

1. **Concerns addressed.** For each valid concern (where the proponent conceded or the fact checker found an error), did the synthesis incorporate the fix?
2. **Concerns correctly rejected.** For each concern the proponent defended, did the synthesis leave the text intact? Or did it weaken the position anyway?
3. **Regression.** Did the synthesis break something that was working? Remove something that was correct? Introduce a new error?
4. **Coherence.** Does the revised document read as a unified whole, or as a patchwork of edits?
5. **Concision.** Is the revision tighter or bloated? Changes should make the document better, not just bigger.

## What You Don't Evaluate

- Whether the document preserves the anchor's intent. That's the drift evaluator's job.
- Whether the claims are factually correct. That's the fact checker's job.

## Output

Write to `<workdir>/round-<round>/eval-quality.md`:

```markdown
# Quality Evaluation — Round N

## Verdict: PASS / FAIL

## Concerns Addressed
- [concern] — addressed: [how]

## Concerns Correctly Rejected
- [concern] — defended: [proponent's argument held]

## Concerns Missed
- [concern] — not addressed and should have been

## Regressions
- [what got worse and where]

## Coherence
[Does it read as a unified document? One sentence.]

## Overall
[Is this draft better than the previous one? One paragraph.]
```
