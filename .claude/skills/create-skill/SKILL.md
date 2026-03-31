---
name: create-skill
description: Create a new skill as a .claude/skills/{name}/ directory with SKILL.md entry point and supporting files using progressive disclosure.
argument-hint: <skill-name>
user-invocable: false
allowed-tools: Read, Glob, Grep, Bash
---

# Create Skill

Create the skill `$ARGUMENTS`.

## Steps

1. Understand what the skill does, who invokes it (user or model), and what tools it needs.
2. Design the structure using progressive disclosure. Read `progressive-disclosure.md` for the design guide.
3. Read `schema.md` for the SKILL.md frontmatter fields.
4. Call `CreateSkill(name, description, body, allowed_tools, argument_hint, user_invocable)` with the collected fields. The tool creates the `SKILL.md` entry point.
5. For supporting files (domain knowledge loaded on demand): the Skills Specialist writes them to `.claude/skills/{name}/` after the skill is created.
6. Validate: frontmatter parses, referenced supporting files exist, `!`command`` injections are syntactically valid. Read `validation.md`.
7. Report what was created.
