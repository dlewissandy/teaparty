# Layer 1: The Feedback Loop

The intent pipeline and learning system are not two separate systems — they form a closed feedback loop.

```
MEMORY.md  (cross-task, backward-looking)
    ↓  warm-starts tier + project routing
classify_task.py  →  intent.sh dialog
    ↓  INTENT.md produced (per-task, forward-looking)
Planning → Execution  (exec streams captured)
    ↓  post-run extraction
summarize_session.py  →  promote_learnings.sh
    ↓  filtered up 4 levels
MEMORY.md  (updated for next run)
```

- **INTENT.md** — per-task, forward-looking ('what should happen')
- **MEMORY.md** — cross-task, backward-looking ('what has worked')

Every task begins with `classify_task.py` reading prior memory. Before the intent session dialog even starts, the system has already absorbed lessons from previous runs — adjusting its tier classification and routing posture based on what `MEMORY.md` records about what has worked. That warm-started classification then drives the `intent.sh` dialog, which produces `INTENT.md`: the per-task artifact that captures what should happen, what assumptions are live, and what needs confirmation.

Once `INTENT.md` exists, planning and execution proceed. The execution streams — agent outputs, tool calls, escalations, decisions — are captured throughout. When the dispatch completes, `summarize_session.py` and `promote_learnings.sh` process those streams, extracting signal and promoting it upward through four levels of memory hierarchy until the strongest, most general insights reach the global `MEMORY.md`.

That updated `MEMORY.md` is what `classify_task.py` reads at the start of the next task. The loop closes. Nothing about this is incidental — the design intention is that the system learns from what agents do, not from instructions about what to remember.

---

# Layer 2: How They Connect — Mechanics

**Memory feeding into intent**

Before the intent session begins, `classify_task.py` reads the project-level `ESCALATION.md` and `MEMORY.md` (up to 2000 chars each). `ESCALATION.md` holds domain-indexed autonomy calibrations — for example, 'Escalate more in domain X'. These warm-start the tier classification: the CLASSIFY_PROMPT literally includes the instruction 'MEMORY WARM-START: If ESCALATION.md shows Escalate more for this domain, push tier up.' By the time the intent dialog even begins, the system already has a posture shaped by lessons from prior runs.

*Future capability (not yet fully active):* `memory_indexer.py` will retrieve top-k relevant memory chunks via BM25 + embeddings and inject them as additional context into the intent agent's prompt at session start.

**Intent recording for learning**

`intent.sh` records the entire dialog to `.intent-stream.jsonl`. Post-session, `retroactive_extract.py` reads this stream and populates two files: `OBSERVATIONS.md` (human preference signals inferred from the dialog) and `ESCALATION.md` (autonomy calibrations derived from how the human pushed back or agreed). These feed back into the next `classify_task.py` run — the loop closes.

**How execution produces memory**

Each dispatch: `relay.sh` asynchronously calls `summarize_session.py --scope team` on the exec stream after the dispatch completes. Learnings are promoted up four levels via `promote_learnings.sh`: dispatch → team → session → project → global. Each level filters for increasing generality; global `MEMORY.md` contains only cross-project process insights — no domain knowledge, no project names.

Quality gate: only structured `## [DATE] Type` entries survive. `summarize_session.py` is explicitly instructed: 'Silence over noise — if no real signal found, output nothing.'

Importantly, **agents do not write `MEMORY.md` directly.** Learning is structural — extracted from exec streams post-run by claude-haiku. This is intentional: agents see no memory instructions in their prompts; the system learns from what they *do*, not from what they're told to remember.

---

# Layer 3: Architecture — Deeper Connections

**INTENT.md as a living hypothesis**

`INTENT.md` is not a finished spec — it uses provisional framing throughout: 'current assumption:', 'to be confirmed:', 'best guess:'. The `<!-- INTENT VERSION: v0.1 ... -->` header is auto-maintained. Revisions are governed by an intent revision authority: the agent may update `INTENT.md` autonomously only for reversible, low-impact changes. Irreversible changes or those affecting already-approved deliverables require human approval. This framing is itself a learning pattern — the system has 'learned' (by design) not to commit prematurely.

**The Memory Hierarchy**

Five levels, each more abstract than the last:

1. Dispatch-level `MEMORY.md` — what happened in one agent run
2. Team-level `MEMORY.md` — aggregated patterns across dispatches for one team
3. Session-level `MEMORY.md` — cross-team coordination learnings (team-internal details filtered out)
4. Project-level `MEMORY.md` — project-specific workflow and domain patterns
5. Global `MEMORY.md` — cross-project process insights only (project names, domain details stripped)

`MEMORY.md` files are gitignored — they live in `.sessions/` and `.worktrees/`, never on main. Infrastructure doesn't pollute the code history.

**Four Temporal Moments**

The system integrates memory at four distinct moments in a task's lifetime. Two are currently active; two are designed but not yet wired:

| Moment | Status | What happens |
|--------|--------|--------------|
| **Prospective** | Active | `classify_task.py` reads memory before intent begins |
| **Retrospective** | Active | `summarize_session.py` extracts learnings post-execution |
| **In-flight** | Designed (future) | Milestone checkpoint updates during execution |
| **Corrective** | Designed (future) | Real-time extraction at moment of error or escalation |

The in-flight and corrective moments are designed and stubbed — their specifications live in `/poc/projects/POC/poc-workflow/task-learning-evolution.txt` — but are not yet wired into the runtime. The architecture is built to receive them when they are.
