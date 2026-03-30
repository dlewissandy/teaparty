---
name: remove-skill
description: "Remove a skill directory and clean up any agent definition skills: allowlist references."
argument-hint: <skill-name>
user-invocable: false
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
---

# Remove Skill

Remove the skill `$ARGUMENTS`.

## Steps

1. Read `.claude/skills/{name}/SKILL.md` to confirm the skill to remove.
2. Read `checklist.md` for safety checks before proceeding.
3. Find all agent definitions that list this skill in their `skills:` allowlist.
4. Confirm with the human: list what will be deleted and which agent definitions need updating.
5. Delete the `.claude/skills/{name}/` directory and all its contents.
6. Remove the skill from each agent definition's `skills:` allowlist.
7. Report what was deleted and what was updated.
