---
name: edit-agent
description: Modify an existing agent definition — update tools, model, maxTurns, skills allowlist, or role description body.
argument-hint: <agent-name>
user-invocable: false
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
---

# Edit Agent

Modify the agent definition for `$ARGUMENTS`.

## Steps

1. Read `.claude/agents/{name}.md` to understand the current definition.
2. Clarify what needs to change. Read `schema.md` for field reference.
3. Apply changes with Edit — preserve unchanged frontmatter and body sections.
4. Validate: frontmatter parses, model is valid, all tools exist, skills in `skills:` exist.
5. Report what changed and why (especially for model or tool scope changes).
