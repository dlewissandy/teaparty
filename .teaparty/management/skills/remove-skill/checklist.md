# Skill Removal Safety Checklist

## Before removing

- [ ] Check agent definitions for allowlist references: `grep -r "skill-name" .claude/agents/`
- [ ] Check workgroup YAML skills catalogs: `grep -r "skill-name" .teaparty/`
- [ ] Confirm no active sessions are currently invoking this skill
- [ ] If this skill is referenced by a scheduled task, the scheduled task must also be removed or updated

## What removal does

- Deletes `.claude/skills/{name}/` and all files within it
- Does NOT automatically update agent definitions — you must edit them manually

## After removal

Report: "Removed skill {name}. Updated allowlists in: [list of agent files]. Updated skill catalogs in: [list of workgroup YAMLs]."
