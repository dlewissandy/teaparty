# Classify Task

Classify the given task into a project slug and execution mode.

## Argument

The task description to classify: `/classify "refactor the authentication module"`

## What To Do

1. **List existing projects** in the `projects/` directory.
2. **Read memory context** — check for `ESCALATION.md` and `MEMORY.md` in the project directory (or the projects root) for warm-start calibration data. Read up to 2000 characters from each.
3. **Classify the task** along two dimensions:

### Project Slug

- If the task clearly belongs to an existing project, use that project's slug exactly.
- If new, derive a short kebab-case slug (2-5 words) from the task description.
- The slug names the **project** (larger body of work), not the specific task.
- Focus on what is being **created**, not the action being taken.

### Mode

- **conversational** — Status queries, "what is X", clarifications, questions requiring NO file changes and only a short answer. Protect this mode: misclassifying a simple question as workflow erodes trust.
- **workflow** — Everything else: file changes, code, writing, research, creative work, builds, fixes, any sustained effort.

## Asymmetric Error Cost

**Under-classification is catastrophic; over-classification is merely annoying.** When ambiguous, default to workflow. A simple question routed through workflow wastes a few seconds of ceremony. A complex task misclassified as conversational gets a shallow answer when it needed sustained effort.

## Output

Report your classification as:
```
Project: <slug>
Mode: <workflow|conversational>
Reasoning: <one sentence explaining why>
```

Then proceed according to the mode — if workflow, begin the work. If conversational, answer the question directly.
