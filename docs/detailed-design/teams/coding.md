# coding

Dispatch here when the task requires writing, modifying, or reviewing code. The team handles architecture decisions, implementation, and code review. It does not produce documentation, visual assets, or configuration — only working software and the tests that verify it. *(Already in management catalog.)*

---

## coding-lead

The coding-lead breaks the implementation task into sub-tasks, assigns to architect, developer, or reviewer as appropriate, integrates the work, and delivers a working implementation with tests. It requests clarification when requirements are ambiguous or when a design decision requires the requestor's input — it does not make product decisions unilaterally. It declares completion when the implementation passes review and tests.

**Tools:** Read, ListFiles, mcp__teaparty-config__Send, mcp__teaparty-config__Reply, mcp__teaparty-config__AskQuestion

---

## architect

Dispatch when a design decision is needed before implementation can begin — system structure, module boundaries, interface design, or technology selection. Produces a design document or decision record, not code. Dispatch before the developer, not after.

**Tools:** Read, Write, Glob, Grep
**Skills:** digest

---

## developer

Dispatch when the task is to write or modify code. Works from a design document or specification and produces code and tests. Not for design decisions (architect) or reviewing completed code (reviewer).

**Tools:** Read, Write, Edit, Bash, Glob, Grep
**Skills:** digest

---

## reviewer

Dispatch when completed code needs a quality gate before it is accepted. Reviews for correctness, clarity, test coverage, and adherence to project conventions. Not for implementation — for judgment on what was implemented.

**Tools:** Read, Glob, Grep, Bash
**Skills:** digest
