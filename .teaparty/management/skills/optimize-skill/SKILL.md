---
name: optimize-skill
description: Structurally refactor a monolithic skill for progressive disclosure — analyze what is loaded upfront, identify deferrable content, extract supporting files, and update SKILL.md references. This is structural analysis and refactoring, not content editing.
argument-hint: <skill-name>
user-invocable: false
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
---

# Optimize Skill

Structurally refactor `$ARGUMENTS` for progressive disclosure.

## Steps

1. Read the current `.claude/skills/{name}/SKILL.md` and all existing supporting files.
2. Run the analysis. Read `analysis-checklist.md` to assess what is upfront vs. deferrable.
3. Design the refactored structure. Read `decomposition-guide.md` for naming conventions and split criteria.
4. Extract deferrable content into named supporting files.
5. Update `SKILL.md` to reference the extracted files: "Read `schema.md` for the field reference."
6. Validate: SKILL.md still covers the invocation interface and high-level flow; supporting files exist.
7. Report: what was extracted, context savings estimate (approximate before/after token count), and how the structure changes the load profile.
