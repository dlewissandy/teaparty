---
name: sprint
description: Run a sprint end-to-end as project-lead. Bootstrap the local cache from a milestone, then alternate (non-strictly) between triage, refresh, and dispatch until the sprint is over and the cache is archived. Orchestration only — every concrete board op is a Delegate to scrum-master, every fix is a Delegate to software-development-lead.
allowed-tools: Read, Glob, Grep, Write, Edit, mcp__teaparty-config__Delegate, mcp__teaparty-config__Send, mcp__teaparty-config__AskQuestion, mcp__teaparty-config__CloseConversation
user-invocable: false
argument-hint: <milestone>
---

# sprint

Drive a sprint from "milestone is set" to "cache archived". The shape:

1. **Bootstrap once.** `Delegate(scrum-master, …, skill='sprint-plan', args={milestone})` builds the local cache.
2. **Alternate non-strictly** between triage, refresh, and dispatch as conditions warrant. The order is not fixed — the *triage* phase routes to whichever phase is appropriate next.
3. **Archive once.** When the sprint is over, `Delegate(scrum-master, …, skill='archive-sprint')` and halt.

The phases and the prose pointers between them encode the workflow. There is no central controller — each phase file ends with the rule for picking what to read next, and you follow it.

## Inputs

- `milestone` — milestone number or title; passed through to `sprint-plan` on the bootstrap hop.

## How this skill works

Each phase lives in its own file in this skill directory. When you finish a phase, the file tells you which file to read next. Read only the current phase — do not read ahead.

## Start

Read `phase-bootstrap.md` in this skill directory.
