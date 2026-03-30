---
name: create-skill
description: Create a new skill as a .claude/skills/{name}/ directory with SKILL.md entry point and supporting files using progressive disclosure.
argument-hint: <skill-name>
user-invocable: false
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
---

# Create Skill

Create the skill `$ARGUMENTS`.

## Steps

1. Understand what the skill does, who invokes it (user or model), and what tools it needs.
2. Design the structure using progressive disclosure. Read `progressive-disclosure.md` for the design guide.
3. Read `schema.md` for the SKILL.md frontmatter fields.
4. Write `.claude/skills/{name}/SKILL.md` — entry point with frontmatter and high-level steps.
5. Write supporting files for domain knowledge that should be loaded on demand rather than upfront.
6. Validate: frontmatter parses, referenced supporting files exist, `!`command`` injections are syntactically valid.
7. Report: file paths created, progressive disclosure design decisions made (what is upfront vs. deferred).
