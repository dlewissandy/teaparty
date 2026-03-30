# Agent Removal Safety Checklist

## Before removing

- [ ] Check workgroup YAMLs for roster entries: `grep -r "{agent-name}" .teaparty/`
- [ ] Check `teaparty.yaml` and `project.yaml` for `lead:` references to this agent
- [ ] Check other agent definitions' `skills:` allowlists for any indirect references
- [ ] Confirm no active sessions are currently running as this agent

## What removal does

- Deletes `.claude/agents/{name}.md`
- Removes roster entries from workgroup YAMLs (do this manually, report each change)

## What removal does NOT do

- Does not delete skills this agent invoked (skills are independent)
- Does not affect sessions that have already completed

## After removal

Report: "Removed {name}.md. Updated the following workgroup YAMLs: [list]."
