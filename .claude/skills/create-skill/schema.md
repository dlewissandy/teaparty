# SKILL.md Frontmatter Schema

```yaml
---
name: skill-name                    # kebab-case, matches directory name
description: One-line description.  # used for auto-invocation matching; be specific
argument-hint: <arg> [--flag]       # describes what arguments the skill accepts
user-invocable: true                # true = human can /skill-name; false = model-only
allowed-tools: Read, Glob, Grep     # tools available when this skill is active
---
```

## Required fields

- `name` — must match the directory name
- `description` — specific enough that the dispatcher can choose this skill correctly

## Optional fields

- `argument-hint` — shown in the skill list; describes expected arguments
- `user-invocable` — defaults to false if omitted
- `allowed-tools` — if omitted, skill inherits all tools from the calling context

## Body structure

After the closing `---`:
- Title as `# Skill Name`
- One sentence describing what it does with `$ARGUMENTS`
- `## Steps` — numbered list of what to do
- References to supporting files: "Read `schema.md` for..." (loaded on demand)

## Dynamic context injection

Use backtick-command syntax to inject live data:
```
Current branch: `git branch --show-current`
Open issues: `gh issue list --state open --json number,title`
```
The command runs when the skill is invoked and the output is substituted inline.
