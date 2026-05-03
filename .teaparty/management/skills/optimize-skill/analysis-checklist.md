# Progressive Disclosure Analysis Checklist

Use this checklist to assess a skill before restructuring.

## Inventory current content

For each section of the current SKILL.md, classify it:

| Content | Needed on every invocation? | Classification |
|---|---|---|
| Invocation steps | Yes | Keep in SKILL.md |
| Schema/field reference | Only when creating | Extract → schema.md |
| Validation checklist | Only when validating | Extract → checklist.md |
| Templates or examples | Only when scaffolding | Extract → template.md |
| Reference data (event names, model names) | Only when deciding | Extract → {topic}-guide.md |
| Error handling / rollback | Only on failure | Extract → {topic}-recovery.md |
| Conceptual rationale | Rarely needed during action | Extract → {topic}-rationale.md |

## Red flags for a monolithic skill

- [ ] SKILL.md is longer than ~60 lines
- [ ] Field definitions with types and defaults appear inline in steps
- [ ] Conditional procedures (only for X case) are inline rather than in supporting files
- [ ] The skill loads the same reference data regardless of which branch the agent takes
- [ ] Examples or templates are embedded inline

## Green flags (skill is already well-structured)

- [ ] SKILL.md is 20–40 lines
- [ ] Each step references supporting files rather than embedding their content
- [ ] Supporting files exist and have focused, named purposes
- [ ] Context varies by invocation path (some files never load for simple cases)
