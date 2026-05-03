# Phase: Register

Call `AddProject` with the complete frontmatter collected in prior phases.

1. Call `AddProject(name, path, description, lead, decider)` with all confirmed values.
2. If the call succeeds, report the result to the human.
3. If the call fails, surface the error message and ask the human how to proceed. Do not silently retry. If the human withdraws, call `WithdrawSession` and stop.

**Next:** Read `phase-exit.md` in this skill directory.
