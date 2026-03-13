# POC Architecture

The TeaParty POC demonstrates that hierarchical agent team coordination works using Claude Code CLI's existing primitives — no bespoke orchestration framework required. A single flat team trying to both plan strategy and produce every file hits context limits and loses coherence. The POC fixes this structurally: an uber team handles coordination while subteams handle execution, each running in its own process with its own context window. The uber lead never sees raw file content; subteam workers never see cross-team coordination.

---

## Two-Level Hierarchy

```
uber team (one claude -p process)
├── project-lead  — coordinates strategy, never produces deliverables
└── liaisons      — one per subteam, bridges via dispatch.sh

subteams (separate claude -p processes, one per dispatch)
├── lead          — coordinates workers within the subteam
└── workers       — produce files and return results
```

The **uber team** is responsible for decomposing the task, sequencing subteam dispatches, and synthesizing results. The project-lead delegates to liaisons via SendMessage; liaisons run concurrently, so multiple subteams can execute in parallel.

**Subteams** receive a scoped task and execute it independently. Workers (writers, artists, coders) produce files. The subteam lead synthesizes results and returns a JSON summary to the liaison. Subteams never communicate with each other — all coordination flows through the uber team.

**Liaisons** are the only agents that cross the process boundary. Each liaison calls `dispatch.sh` via Bash, which spawns a subteam process, waits for completion, and returns the result. This is the only bespoke inter-process bridge in the system.

---

## CfA State Machine

The POC uses a three-phase Conversation for Action (CfA) lifecycle, enforced by `plan-execute.sh`:

1. **Intent** — the orchestrator gathers what the human wants and produces an `intent.md`. This phase runs before any planning or execution.

2. **Planning** — the uber team runs in `--permission-mode plan`. The project-lead explores the problem, delegates research to liaisons as needed, and calls `ExitPlanMode` when ready. The human (or proxy) reviews and approves the plan before execution begins.

3. **Execution** — the uber team resumes the plan session in `--permission-mode acceptEdits`. The project-lead dispatches liaisons to subteams. Each subteam runs its own plan-then-execute cycle at the subteam level, with proxy-gated approval.

Backtrack transitions are explicit: the proxy can send a session back from Execution to Planning, or from Planning back to Intent, when the work has diverged from its purpose.

---

## Git Worktree Isolation

Each session and each subteam dispatch runs in its own **isolated git worktree** on a separate branch. This is what makes concurrent execution safe:

- The uber session branch is checked out from `main` at session start.
- Each dispatch creates a child branch from the session branch.
- When a dispatch completes, its deliverables are committed and merged into the session branch.
- When the session completes, the session branch merges into `main`.

`main` always holds the latest consolidated deliverables. `git log` provides full version history. A failed session or dispatch is discarded without touching `main`.

---

## Learning Extraction

Learning is **structural, not prompt-dependent**. Agents do not write memory files. At the end of each session, `scripts/summarize_session.py` reads the conversation stream, calls claude-haiku, and extracts durable learnings scoped to the appropriate level.

The extraction pipeline runs after every session across 10 scopes in three groups:

**Intent-stream scopes** (extracted from session conversation streams):
1. **Observations** → `proxy.md`: human preference signals
2. **Escalation** → `proxy-tasks/`: autonomy calibration signals
3. **Intent-alignment** → `tasks/`: gaps between stated intent and execution

**Rollup scopes** (promote learnings upward through the hierarchy):
4. **Dispatch → team**: per-team patterns from individual dispatch streams
5. **Team → session**: team-agnostic coordination insights
6. **Session → project**: project-specific patterns
7. **Project → global**: cross-project process insights only; all domain knowledge stays at project level

**Temporal scopes** (different analytical perspectives on the work):
8. **Prospective**: pre-mortem analysis → `tasks/<ts>-prospective.md`
9. **In-flight**: assumption checkpoints → `tasks/<ts>-inflight.md`
10. **Corrective**: execution errors → `tasks/<ts>-corrective.md`

Each rollup step filters more aggressively. The result is a memory hierarchy where learnings are stored at the most specific scope where they apply and promoted only when they generalize.

---

## For Contributors

The full implementation reference — including stream-JSON event format, CLI flags, environment variables, file layout, agent/team lifecycle, failure modes, and counter-indicated patterns — is in [`projects/POC/docs/poc-architecture.md`](../projects/POC/docs/poc-architecture.md).
