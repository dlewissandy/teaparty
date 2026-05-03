# Skill Edit Reference

Read `../create-skill/schema.md` for the full frontmatter field definitions.

## What counts as a content edit (use edit-skill)

- Fixing incorrect or outdated step instructions
- Updating a schema in a supporting file to match a spec change
- Changing the description to improve auto-invocation matching
- Adding or removing a step from the flow
- Updating a supporting file's content

## What counts as structural refactoring (use optimize-skill instead)

- Moving inline content out of SKILL.md into supporting files
- Decomposing a monolithic SKILL.md
- Restructuring for progressive disclosure
- Splitting one large supporting file into focused smaller ones

## Common edits

**Update the description for better matching:**
```yaml
description: More specific description that accurately describes when to use this skill.
```

**Add an allowed tool:**
```yaml
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
```

**Fix a step in the body:**
Edit the numbered step directly. Preserve all other steps unchanged.
