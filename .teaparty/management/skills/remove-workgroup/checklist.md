# Workgroup Removal Safety Checklist

## Before removing

- [ ] No active sessions are currently dispatching to this workgroup
- [ ] Human confirms removal intent
- [ ] Check if other workgroups or projects reference this workgroup by name

## What removal does

- Deletes the workgroup YAML file
- Removes the `workgroups:` entry from the parent config
- Does NOT delete agent definitions listed in the workgroup's `agents:` roster

## After removal

Report: "Removed workgroup {name}. Agent definitions in .claude/agents/ are untouched."
