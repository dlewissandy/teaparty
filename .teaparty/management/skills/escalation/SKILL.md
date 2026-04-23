---
name: escalation
description: Run the proxy's escalation dialog — answer a teammate's question from memory, or dialog with the human to reach consensus, then relay the decision back to the teammate.
user-invocable: false
allowed-tools: Read, Glob, Grep
---

# Dispatch

The project's escalation policy for the current state has been passed to you as `$ARGUMENTS`.  Match `$ARGUMENTS` against the values below and execute the indicated workflow:

- `$ARGUMENTS` is `never` — read `delegate.md` in this skill directory and execute the workflow it contains.  The proxy answers from memory alone; the human is not consulted.
- `$ARGUMENTS` is `when_unsure` — read `collaborate.md` in this skill directory and execute the workflow it contains.  The proxy answers from memory when confident, and dialogs with the human when it is not.
- `$ARGUMENTS` is `always` — read `escalate.md` in this skill directory and execute the workflow it contains.  The human is the decider; the proxy facilitates the dialog.

If `$ARGUMENTS` is empty or is not one of the three values above, read `unknown.md` in this skill directory and execute the workflow it contains.
