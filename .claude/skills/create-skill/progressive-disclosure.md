# Progressive Disclosure Design Guide

## What it means

A skill is loaded when invoked. Every byte in SKILL.md burns context on every invocation — even if 80% of the content is only relevant for edge cases. Supporting files are loaded only when the agent reaches the step that references them.

## What goes in SKILL.md (upfront)

- The invocation interface (what arguments the skill accepts)
- The high-level steps the agent will follow
- References to supporting files: "Read `schema.md` for the field reference"
- Dynamic context that is always needed (current branch, current config state)

## What goes in supporting files (on demand)

- Full schema definitions (only needed when writing a new artifact)
- Templates (only needed when creating from scratch)
- Checklists (only needed when validating)
- Reference data with many entries (event names, tool names, model names)
- Branch-specific or conditional procedures (rollback, error handling)
- Historical context or rationale that helps understanding but isn't action-critical

## When to create a supporting file

Ask: "Is this content needed on every invocation, or only sometimes?"
- Always needed → in SKILL.md
- Sometimes needed → supporting file

## Naming conventions

| File | Contents |
|---|---|
| `schema.md` | YAML/JSON field reference for the artifact being created |
| `checklist.md` | Validation steps to run before reporting completion |
| `template.md` | Starter file content the agent can copy and modify |
| `{topic}-guide.md` | Reference guide for a specific decision area |
| `examples.md` | Concrete examples showing before/after |

## Example

Skill: `create-agent`

SKILL.md contains: 5 high-level steps + "Read schema.md for fields" + "Read tool-scoping.md for model guidance"

schema.md contains: every frontmatter field with types and valid values (only needed when writing the definition)

tool-scoping.md contains: model selection criteria, tool profiles (only needed when making design decisions)

Result: a simple agent creation invocation loads ~200 tokens; a complex one with model/tool decisions loads ~600.
