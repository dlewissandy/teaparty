[Workflow Skills](../proposal.md) >

# Example: Research Paper Workflow

## Before Crystallization

The first time "write a research paper" comes in, full CfA runs. The project lead plans a decomposition: survey the literature, construct the argument, draft sections in parallel, validate claims, finalize. The human reviews the plan. The proxy learns what the human attends to (citation standards, argument structure). The session completes.

Second time — same task category, different topic. Full CfA again. The decomposition converges on the same phases. The proxy now has more confidence at the gates.

After four sessions: consistent phase sequence, consistent gate outcomes, consistent escalation patterns. Crystallization candidate.

---

## The Crystallized Skill

```
.teaparty/management/skills/research-paper/
├── SKILL.md              ← entry point, applicability boundary
├── phase-survey.md       ← literature search and evaluation
├── phase-synthesize.md   ← argument construction
├── phase-draft.md        ← parallel section drafting
├── phase-validate.md     ← claim verification gate
└── phase-finalize.md     ← edit, format, close
```

`SKILL.md` frontmatter records the boundary:
```yaml
applies-when:
  - systematic investigation of a question with documented sources
  - output is a structured written artifact
does-not-apply-when:
  - task requires original empirical data collection
  - scope is a single-source summary
crystallized-from: 4 sessions
```

---

## Direct Invocation

Fifth session: "write a research paper on adversarial robustness in LLMs." The lead matches the task against the skill. Confident match. Invokes the skill directly — no planning phase, no multi-round negotiation.

The agent follows the continuation chain. At `phase-validate.md`, a gate fires: one cited source has been retracted. The agent calls `AskQuestion`. The proxy resolves it: substitute with the citing paper. Session continues.

---

## Graph Extension

Sixth session, same skill. Source retraction again — same phase, same exception. Third time this happens across sessions: extension candidate.

The Skills Specialist creates `phase-validate-retracted-source.md` — a branch node that handles retracted sources autonomously (find the citing paper, check if the argument still holds, proceed or escalate if the argument collapses). `phase-validate.md` gains a conditional continuation.

Seventh session: source retraction at validation. The agent follows the new branch. No escalation. Handled.

---

## Promotion

The research-paper skill was crystallized by the TeaParty project team. The pybayes project also does research. When the skill's pattern holds for pybayes sessions too, it promotes from project-scoped to global — the exception branch for retracted sources comes with it. The pybayes team inherits the handler it never had to earn.
