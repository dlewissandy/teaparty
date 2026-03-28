# Request Flow Scenarios

These five scenarios show how the Configuration Team coordinates to handle common requests.

---

## "I would like to create a new skill"

1. Human types in office manager chat (or clicks "+ New" on Skills card, which pre-seeds the message)
2. Office manager recognizes this as a configuration request and dispatches to Configuration Team via AskTeam
3. Configuration Lead receives the request, asks clarifying questions back through the office manager if needed (what should the skill do? what tools does it need? is it user-invocable?)
4. Configuration Lead routes to Skill Architect
5. Skill Architect designs the skill structure, writes files to `.claude/skills/{name}/`
6. Configuration Lead reviews and reports completion back to office manager
7. Office manager confirms to the human: "Created skill `deploy` with 4 files"

---

## "I would like to create a new workgroup"

This is a multi-artifact request. The Configuration Lead coordinates, sequencing work so that hard dependencies (skills before agents that reference them) are satisfied:

1. **Description** — Configuration Lead writes the workgroup description (the one-line summary that tells team leads when to dispatch to this workgroup)
2. **Skills** — Skill Architect creates or assigns workgroup-scoped skills (before agents, because agents may reference skills by name)
3. **Agent definitions** — Agent Designer creates the workgroup lead agent and any specialist agents
4. **Hooks** — Systems Engineer creates any workgroup-specific hooks
5. **Registration** — Configuration Lead writes the workgroup YAML and updates the parent team's configuration. If the workgroup is shared (org-level), it goes in `~/.teaparty/workgroups/`. If project-scoped, it goes in `{project}/.teaparty/workgroups/`

**If a specialist fails** after prior steps have already succeeded, the Configuration Lead does not roll back the artifacts already created — they are independently valid. Instead, the Lead reports to the office manager exactly what was created and what failed. The human can retry the failed step through a follow-up conversation ("finish setting up the workgroup"), which the Lead routes to the specialist that failed.

---

## "Optimize the audit skill for progressive disclosure"

1. Skill Architect reads the current skill structure
2. Analyzes which content is loaded upfront vs. could be deferred
3. Decomposes monolithic content into supporting files
4. Updates SKILL.md to reference supporting files instead of including them inline
5. Validates that the skill still invokes correctly
6. Reports what changed and the context savings

---

## "Add a pre-commit hook that runs tests"

1. Systems Engineer reads current `.claude/settings.json`
2. Adds a `PreToolUse` hook matching `Bash` with a matcher that detects git commit commands
3. Writes the hook handler (command type pointing to a validation script, or agent type that runs tests)
4. Creates the handler script if needed (`.claude/hooks/pre-commit-tests.sh`)

---

## "Run the test sweep every night at 2am"

1. Configuration Lead checks: does a `test-sweep` skill exist? If not → routes to Skill Architect first
2. Skill Architect creates `.claude/skills/test-sweep/SKILL.md` (if needed)
3. Systems Engineer adds the scheduled entry to the appropriate YAML (`teaparty.yaml` for cross-project, `project.yaml` for project-scoped)
4. Systems Engineer creates the `/schedule` trigger via Claude Code
