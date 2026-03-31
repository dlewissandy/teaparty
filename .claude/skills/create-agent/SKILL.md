---
name: create-agent
description: Create a new agent definition file at .claude/agents/{name}.md with frontmatter, tool scoping, model selection, and role description.
argument-hint: <agent-name>
user-invocable: false
allowed-tools: Read, Glob, Grep, Bash
---

# Create Agent

Create an agent definition for `$ARGUMENTS`.

## Steps

1. Understand the intended role. What decisions does this agent make? What files does it touch? What tools does it need — and which tools would be dangerous to give it?
2. Ask clarifying questions if the role is ambiguous. Read `schema.md` for all frontmatter fields.
3. Choose the model. Read `tool-scoping.md` for guidance on model selection and tool scoping.
4. Write `.claude/agents/{name}.md` with frontmatter and a role description body.
5. Validate: frontmatter parses, model is valid, all listed tools exist, skills listed in `skills:` exist.
6. Report the file path and the key design decisions made (why this model, why these tools).
