# Phase: Scaffold

Call `CreateProject` with the complete frontmatter collected in the dialog phase.

1. Call `CreateProject(name, path, description, lead, decider)` with all confirmed values.
2. If the call succeeds, report the result to the human, including the path where the project was created.
3. If the call fails, surface the error message and ask the human how to proceed. Do not silently retry.

**Next:** Read `phase-exit.md` in this skill directory.
