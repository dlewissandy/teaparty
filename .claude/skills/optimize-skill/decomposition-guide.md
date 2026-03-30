# Skill Decomposition Guide

## How to split a monolith

### Step 1: Draw the invocation boundary

Everything the agent needs to understand the task and begin the first step belongs in SKILL.md. Everything needed only at a specific step belongs in a supporting file loaded at that step.

SKILL.md template after optimization:
```markdown
# Skill Name

Do X for `$ARGUMENTS`.

## Steps

1. [First action — pure instruction, no reference data]
2. [Second action — "Read `schema.md` for the field reference"]
3. [Third action — "Read `checklist.md` to validate before completing"]
4. Report what was done.
```

### Step 2: Name supporting files by their role

| File | When loaded | Contains |
|---|---|---|
| `schema.md` | Step that writes a new artifact | YAML/JSON field reference |
| `checklist.md` | Validation step | Ordered validation checks |
| `template.md` | Scaffolding step | Starter file content |
| `{topic}-guide.md` | Decision step | Criteria for a specific choice |
| `examples.md` | When the agent needs a model | Before/after examples |

### Step 3: Write the references in SKILL.md

Replace extracted inline content with a single sentence:
- "Read `schema.md` for the full field reference."
- "Read `checklist.md` and run each check before reporting completion."
- "If targeting a non-default environment, read `environments.md`."

### Step 4: Validate the restructured skill

- SKILL.md is self-contained enough to start the task
- Each supporting file is focused (single purpose, not a catch-all)
- No orphan files (every file is referenced from SKILL.md)
- No orphan references (every referenced file exists)

## Context savings estimate

Token count before optimization: count characters in the monolithic SKILL.md ÷ 4.
Token count after optimization (average invocation): SKILL.md + 1–2 supporting files typically needed.
Savings = before − after per invocation.
