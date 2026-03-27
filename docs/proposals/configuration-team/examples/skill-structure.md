# Skill Structure: Progressive Disclosure Example

## Directory Layout

Skills are located in `.claude/skills/{name}/` with supporting files for progressive disclosure:

```
.claude/skills/deploy/
├── SKILL.md              ← invocation entry point (loads on demand)
├── checklist.md          ← loaded by agent when reaching validation step
├── rollback-procedure.md ← loaded only if deployment fails
└── environments.md       ← loaded only if targeting non-default env
```

## SKILL.md Structure

The main skill definition provides the invocation interface and high-level flow:

```yaml
---
name: deploy
description: Deploy the current branch to a target environment with validation.
argument-hint: <environment>
user-invocable: true
allowed-tools: Bash, Read, Glob
---

# Deploy

Deploy `$ARGUMENTS` (default: staging).

## Steps

1. Run pre-deploy checks. Read `checklist.md` for the validation checklist.
2. Execute deployment. Use the appropriate script for the target environment.
3. Validate. Run smoke tests against the deployed environment.
4. If validation fails, read `rollback-procedure.md` and execute rollback.

For environment-specific configuration, read `environments.md`.
```

## Key Design Principles

- **Upfront:** Only the invocation instructions and high-level flow go in SKILL.md
- **On-demand:** Templates, reference data, examples, and branch-specific procedures go in supporting files
- **Progressive disclosure:** Supporting files are loaded only when the agent reaches the step that needs them
- **Context efficiency:** Never load `environments.md` if the user chose the default environment
