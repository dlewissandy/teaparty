# Procedural Memory

Where episodic learning captures knowledge as text — facts, norms, preferences — procedural learning captures knowledge as executable structure. The core refinement pipeline lives in `teaparty/learning/procedural/`; skill lookup at planning time lives in `teaparty/util/skill_lookup.py`.

A single successful plan is an anecdote. Three successful plans with the same shape are a candidate skill. Procedural memory lets the organization's skills evolve: failure points get patched, unnecessary steps get pruned, missing gates get added — not by a human editing a template, but by the system observing where its own plans break and repairing them.

## Skill crystallization

When multiple plans for the same category of work converge on the same decomposition, the system generalizes the pattern into a Claude Code skill — a parameterized workflow with fixed structure (sequencing, gates, fan-out/fan-in) and variable parameters (topic, audience, depth). This is how cold-start plans become warm-start templates.

The pipeline:

1. `archive_skill_candidate()` saves successful session plans as candidates at session close.
2. `crystallize_skills()` clusters candidates by category and task similarity before generalization. Each coherent cluster is generalized independently via a separate LLM call — the clustering step matters because generalizing across dissimilar candidates produces a skill that fits none of them.
3. `teaparty/util/skill_lookup.py` matches incoming tasks against the resulting skills at planning time, seeding the plan with the skill's structure instead of starting blank.

See [strategic planning — warm start](../cfa-orchestration/planning.md) for how skills participate in the planning phase.

### SKILL.md format

A crystallized skill lives at `{scope}/.teaparty/.../skills/{name}/SKILL.md`. The file is YAML frontmatter plus a Markdown body:

```markdown
---
name: edit-hook
description: Modify an existing hook in .claude/settings.json — change the matcher, handler command, or handler type.
argument-hint: <hook-description>
user-invocable: false
allowed-tools: Read, Glob, Grep, Bash
---

# Edit Hook

Modify the hook for `$ARGUMENTS`.

## Steps

1. Read `.claude/settings.json` (and `.claude/settings.local.json` if local hooks are in scope).
2. Locate the hook entry by event and matcher.
3. ...
```

Frontmatter fields:

| Field | Purpose |
|---|---|
| `name` | Slug; matches the directory name |
| `description` | One-sentence trigger description used by skill matching |
| `argument-hint` | Placeholder for the parameterized argument (replaces `$ARGUMENTS` in the body) |
| `user-invocable` | `true` exposes as a slash command; `false` restricts to lookup-time invocation |
| `allowed-tools` | Comma-separated tool allowlist for the agent invoking the skill |

The body is a numbered procedure that operates on `$ARGUMENTS`. Continuous refinement (below) edits the body in place when execution friction is detected.

## Continuous refinement

Skills are not frozen once crystallized. When execution under a skill fails at a specific point — a contingency the skill didn't anticipate, a gate that consistently triggers escalation, a decomposition step that produces work requiring rework — the corrective learning targets the skill itself rather than only the session.

Three refinement signals are operational:

1. **Execution friction detection.** `detect_friction_events()` scans stream JSONL post-session for permission denials, file-not-found errors, and fallback retries. These are low-level indicators that the skill's assumptions didn't match reality.
2. **Friction-aware skill refinement.** `refine_skill_with_friction()` sends friction events to an LLM that updates the skill template — patching the specific step that produced the failure, adjusting assumptions that turned out wrong, or inserting a missing guard. Wired into `extract_learnings()` as the `skill-refine` scope.
3. **Per-skill quality monitoring.** `update_skill_friction_stats()` accumulates friction counts in skill frontmatter. Skills with high friction get flagged `needs_review: true` and are excluded from `lookup_skill()` results until reviewed — a degraded skill stops seeding new plans before it poisons more sessions.

Gate correction refinement is also operational: when the human corrects a gate decision, the correction is routed back to the skill that produced the artifact under review.

## Why this closes the loop

Without procedural learning, each session's plan is informed by declarative learnings ("this approach didn't work last time") but not by structural corrections to the workflow itself. A team that learns "always back up before migrating" is better prepared; a team whose *migration skill* now has a backup step is structurally improved — the correction survives personnel turnover, context loss, and the next round of context compaction.

Procedural learning carries durability across sessions, where individual declarative learnings cannot.
