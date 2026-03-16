# Obstacles

The session encountered four categories of obstacles. The first three are external infrastructure constraints; the fourth is a design gap in how dispatched agents understand their environment.

---

## Watchdog Timeouts and Token Limits

The session had to be restarted multiple times using the orchestrator's resume mechanism. Unforeseen watchdog timeouts interrupted execution mid-phase, and the LLM provider's context window limits were hit during longer phases, forcing session segmentation. The resume mechanism handled recovery — the session picked up where it left off — but each restart introduced latency. For a session spanning ~12 hours of wall-clock time, the restart friction was significant.

---

## Rate Limiting on Parallel Dispatch

The first research dispatch wave hit provider rate limits across six of eight tracks. The system adapted by implementing a monitoring loop to re-dispatch after the rate-limit window reset, but this was reactive rather than proactive. The plan had no provision for rate-limit-aware scheduling.

---

## Prologue Brief Persistence Failure

The prologue research brief failed to persist to disk repeatedly across sessions, even after sub-teams reported completion. The system adapted by starting Phase 2 spec work on Ch1–7 while retrying the prologue research — smart parallelization, but it contradicted the stated "sequential phases with hard gates" model. This revealed a gap between the plan's assumptions (clean parallel execution) and reality (partial delivery requiring fallback strategies).

---

## Worktree Path Confusion

Each dispatch ran in its own isolated git worktree, and the agents frequently struggled to understand which directory they were in, which directories they could access, and where to write their output. The [session log](../../projects/humor-book/.sessions/20260315-171017/session.log) contains several concrete examples:

**Sandbox boundary errors.** A research sub-agent, dispatched into its own worktree (`research-1b423304--produce-a-research-brief-`), tried to `ls` the parent session worktree to orient itself. The sandbox blocked it: *"For security, Claude Code may only list files in the allowed working directories for this session."* The agent had to discover its own working directory by trial and error rather than by inspecting the broader project structure.

**Wrong-file writes.** One research agent, tasked with producing the Ch7 brief, wrote a `ch3_brief.md` to the session worktree — the wrong chapter to the wrong location. The agent had confused its own research worktree path with the session worktree, and its task identity (Ch7) with another chapter's output filename. The file landed; it just landed in the wrong place.

**INTENT.md not where expected.** The verification agent, working in the session worktree, expected INTENT.md at the worktree root. It wasn't there — it was at the main project root. The agent noted this explicitly in its [verification report](../e2e-raw-files/verification/verification_report.md): *"INTENT.md does not exist at the worktree root. It is located at the main project root."* The agent recovered and found the file, but the confusion cost turns and added fragility.

These are symptoms of the same underlying issue: when agents are spawned into worktrees, they lack a clear, authoritative map of where they are, what they can access, and where their outputs should go. The task brief tells them *what* to produce but not always *where* — and the worktree hierarchy (session worktree → research worktree → sub-agent working directory) is deep enough that agents routinely guess wrong. A reliable solution would inject the output path and readable-paths explicitly into each dispatch's context, rather than expecting agents to infer them from the directory structure.
