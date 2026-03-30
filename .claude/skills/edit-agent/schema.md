# Agent Edit Reference

Read `../create-agent/schema.md` for the full field definitions.
Read `../create-agent/tool-scoping.md` for model selection and tool scoping guidance.

## Common edits

**Add a skill to the allowlist:**
```yaml
skills:
  - existing-skill
  - new-skill          # ensure .claude/skills/new-skill/SKILL.md exists
```

**Change the model:**
```yaml
model: claude-opus-4-5   # see model selection guide in tool-scoping.md
```

**Add a tool:**
```yaml
tools: Read, Glob, Grep, Write, Edit, Bash, WebSearch
```

**Increase maxTurns for complex tasks:**
```yaml
maxTurns: 30
```

## What to preserve

- The `name` field must match the filename (kebab-case)
- The `description` field — changes here affect how the dispatcher chooses this agent
- Body sections that describe the agent's role and constraints
