# Project Removal Safety Checklist

Before removing a project from the registry, verify these conditions.

## Safety checks

- [ ] No active sessions are currently running against this project
- [ ] The human confirms they want to deregister, not delete, the project directory
- [ ] Any workgroups scoped to this project are noted (they will become unreachable)

## What removal does

- Removes the `teams:` entry from `~/.teaparty/teaparty.yaml`
- Does NOT delete `{project}/.teaparty/project.yaml` or any project files
- The project can be re-registered later by pointing the registry at the same path

## What removal does NOT do

- Does not remove project-scoped agent definitions from `.claude/agents/`
- Does not remove project-scoped skills from `.claude/skills/`
- Does not close any open GitHub issues or PRs

## After removal

Report: "Removed {name} from the TeaParty registry. The project directory at {path} is untouched and can be re-registered with create-project."
