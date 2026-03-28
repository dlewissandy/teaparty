# Request Flow Scenarios

These five scenarios show how the Configuration Team handles common requests. Simple requests (single artifact, clear requirements) use the **fast path** — the office manager routes directly to the specialist, bypassing the Configuration Lead. Complex requests (multi-artifact or ambiguous) use the **full team** with the Configuration Lead coordinating.

---

## "I would like to create a new skill" — fast path

Single artifact, clear type → office manager routes directly to Skill Architect.

1. Human types in office manager chat (or clicks "+ New" on Skills card, which pre-seeds the message)
2. Office manager recognizes this as a single-artifact configuration request for a skill
3. Office manager routes directly to Skill Architect via AskTeam
4. Skill Architect asks clarifying questions back through the office manager if needed (what should the skill do? what tools does it need? is it user-invocable?)
5. Skill Architect designs the skill structure, writes files to `.claude/skills/{name}/`
6. Office manager confirms to the human: "Created skill `deploy` with 4 files"

---

## "I would like to create a new workgroup" — full team

Multi-artifact request → office manager dispatches to Configuration Lead, who coordinates. The Lead sequences work so that hard dependencies (skills before agents that reference them) are satisfied.

1. Office manager recognizes this requires multiple artifact types and routes to Configuration Lead
2. Configuration Lead decomposes the request and coordinates:
   - **Description** — Configuration Lead writes the workgroup description (the one-line summary that tells team leads when to dispatch to this workgroup)
   - **Skills** — Skill Architect creates or assigns workgroup-scoped skills (before agents, because agents may reference skills by name)
   - **Agent definitions** — Agent Designer creates the workgroup lead agent and any specialist agents
   - **Hooks** — Systems Engineer creates any workgroup-specific hooks
   - **Registration** — Configuration Lead writes the workgroup YAML and updates the parent team's configuration. If the workgroup is shared (org-level), it goes in `~/.teaparty/workgroups/`. If project-scoped, it goes in `{project}/.teaparty/workgroups/`

**If a specialist fails** after prior steps have already succeeded, the Configuration Lead does not roll back the artifacts already created — they are independently valid. Instead, the Lead reports to the office manager exactly what was created and what failed. The human can retry the failed step through a follow-up conversation ("finish setting up the workgroup"), which the Lead routes to the specialist that failed.

---

## "Optimize the audit skill for progressive disclosure" — fast path

Single artifact, clear type → office manager routes directly to Skill Architect.

1. Office manager routes to Skill Architect
2. Skill Architect reads the current skill structure
3. Analyzes which content is loaded upfront vs. could be deferred
4. Decomposes monolithic content into supporting files
5. Updates SKILL.md to reference supporting files instead of including them inline
6. Validates that the skill still invokes correctly
7. Reports what changed and the context savings

---

## "Add a pre-commit hook that runs tests" — fast path

Single artifact, clear type → office manager routes directly to Systems Engineer.

1. Office manager routes to Systems Engineer
2. Systems Engineer reads current `.claude/settings.json`
3. Adds a `PreToolUse` hook matching `Bash` with a matcher that detects git commit commands
4. Writes the hook handler (command type pointing to a validation script, or agent type that runs tests)
5. Creates the handler script if needed (`.claude/hooks/pre-commit-tests.sh`)

---

## "Run the test sweep every night at 2am" — full team

May require multiple artifacts (skill + scheduled task) → office manager dispatches to Configuration Lead.

1. Configuration Lead checks: does a `test-sweep` skill exist? If not → routes to Skill Architect first
2. Skill Architect creates `.claude/skills/test-sweep/SKILL.md` (if needed)
3. Systems Engineer adds the scheduled entry to the appropriate YAML (`teaparty.yaml` for cross-project, `project.yaml` for project-scoped)
4. Systems Engineer creates the `/schedule` trigger via Claude Code
