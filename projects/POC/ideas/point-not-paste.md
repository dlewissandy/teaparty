# Idea: Point-not-paste — agents pass file references, not file contents

## Problem

Agents currently paste file contents into messages, tool inputs, escalation files, and inter-agent communications. This causes:

1. **Context window bloat.** A 1500-line LaTeX paper pasted into a message consumes thousands of tokens that could be used for reasoning. When multiple agents in a team each paste the same file, the cost multiplies.
2. **Stale copies.** A pasted snapshot is frozen at the moment of pasting. If the file changes (another agent edits it, or the same agent edits it later), every prior paste is now stale. Agents reason over outdated content without knowing it.
3. **Redundant transfer.** The same file gets pasted into escalation documents, planning artifacts, team messages, and tool calls. Each paste is an independent copy that must be processed, stored, and (in streaming) transmitted.
4. **Breaks tool efficiency.** The Read tool supports offset/limit parameters for efficient partial reads. When an agent pastes full contents instead of pointing to a path, downstream agents lose the ability to read selectively.

## Desired behaviour

Agents should pass **file paths** (or path + line range references) instead of file contents. The receiving agent or tool uses Read/Grep to access exactly what it needs.

Examples of what changes:

- **Escalation files** reference paths: "See `hierarchical-memory-paper.tex` lines 730-750" rather than pasting the block.
- **Inter-agent messages** point to artifacts: "Plan is at `PLAN.md` in the worktree" rather than quoting the plan.
- **Tool inputs** stay small: an Edit tool call references the file by path; the old_string/new_string should be the minimal unique match, not a multi-paragraph block.
- **Planning documents** reference source material by path and section, not by inline quotation.

## Why this matters beyond efficiency

Point-not-paste is also a **freshness guarantee**. When an agent reads a file at the moment it needs it, it gets the current version. When it works from a pasted copy, it may be reasoning over content that was edited five tool calls ago. In multi-agent sessions where several agents edit the same file, this is the difference between coherent collaboration and silent divergence.

## Scope

This is a prompting and convention change, not an infrastructure change. The tools already support it — Read, Grep, and Glob all work by reference. The change is in agent instructions (system prompts, team definitions, workflow descriptions) to establish point-not-paste as the default communication pattern.
