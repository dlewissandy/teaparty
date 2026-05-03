---
name: edit-skill
description: Modify an existing skill's SKILL.md content or supporting files — fix instructions, update a schema, change behavior. Structural refactoring (decomposing a monolith) uses optimize-skill instead.
argument-hint: <skill-name>
user-invocable: false
allowed-tools: Read, Glob, Grep, Bash
---

# Edit Skill

Modify the skill `$ARGUMENTS`.

## Steps

1. Read `.claude/skills/{name}/SKILL.md` and any relevant supporting files.
2. Clarify what needs to change: is this a content change (fix instructions, update schema) or a structural change (decompose monolith)?
   - If structural: stop and use `optimize-skill` instead.
   - If content: continue.
3. Read `schema.md` for frontmatter field reference if the frontmatter is changing.
4. Call `EditSkill(name, field, value)` — use `field='body'` to update the skill body, or `field='allowed-tools'`, `field='description'`, etc. to update frontmatter fields.
5. Validate: frontmatter parses, referenced supporting files still exist.
6. Report what changed.
