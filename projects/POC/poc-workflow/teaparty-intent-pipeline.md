# Layer 1: The Feedback Loop

The intent pipeline and learning system are not two separate systems — they form a closed feedback loop.

```
MEMORY.md  (cross-task, backward-looking)
    ↓  warm-starts tier + project routing
classify_task.py  →  intent.sh dialog  (intent session)
    ↓  INTENT.md produced (per-task, forward-looking)
Planning → Execution  (exec streams captured)
    ↓  post-run extraction
summarize_session.py  →  promote_learnings.sh
    ↓  promoted through memory hierarchy
MEMORY.md  (updated for next run)
```

- **INTENT.md** — per-task, forward-looking ("what should happen")
- **MEMORY.md** — cross-task, backward-looking ("what has worked")

Every task begins with `classify_task.py` reading prior memory. Before the intent session dialog even starts, the system has already absorbed lessons from previous runs — adjusting its tier classification and routing posture (its default stance on which agents or tiers to prefer) based on what `MEMORY.md` records about what has worked. That warm-started classification then drives the `intent.sh` dialog, which produces `INTENT.md`: the per-task artifact that captures what should happen, what assumptions are still open, and what needs confirmation. The dialog session itself is recorded for later analysis.

Once `INTENT.md` exists, planning and execution proceed. The execution streams — agent outputs, tool calls, escalations, decisions — are captured throughout execution. When the dispatch completes, `summarize_session.py` and `promote_learnings.sh` process those streams, extracting signal and promoting it upward through five memory levels until the strongest, most general insights reach the global `MEMORY.md`.

That updated `MEMORY.md` is what `classify_task.py` reads at the start of the next task. The loop closes. The system is designed to learn from what agents do, not from instructions about what to remember.

---

# Layer 2: How They Connect — Mechanics

**Memory feeding into intent**

Before the intent session begins, `classify_task.py` reads the project-level `ESCALATION.md` and `MEMORY.md` (up to 2000 chars each). `ESCALATION.md` — a file that records per-domain guidance on when to escalate — holds domain-indexed autonomy calibrations, for example, 'Escalate more in domain X'. These warm-start the tier classification: the CLASSIFY_PROMPT literally includes the instruction 'MEMORY WARM-START: If ESCALATION.md shows Escalate more for this domain, push tier up (assign a higher tier).' By the time the intent dialog even begins, the system already has a posture shaped by lessons from prior runs.

*Future capability (not yet fully active):* `memory_indexer.py` will retrieve the most relevant memory excerpts (using a combination of keyword and semantic search) and inject them as additional context into the intent agent's prompt at session start.

**Intent recording for learning**

`intent.sh` records the entire dialog to `.intent-stream.jsonl`. `retroactive_extract.py` (which analyzes the recorded dialog after the session ends) can be run manually to populate two files: `OBSERVATIONS.md` (human preference signals inferred from the dialog) and `ESCALATION.md` (autonomy calibrations derived from how the human pushed back or agreed). Note: this extraction is not automatic — `retroactive_extract.py` is a one-shot tool that must be invoked manually. `ESCALATION.md` is read automatically by the next `classify_task.py` run; `OBSERVATIONS.md` is available for analysis but is not currently read by `classify_task.py`. Both files feed back into the system — the loop closes.

**How execution produces memory**

After each dispatch, `relay.sh` asynchronously calls `summarize_session.py --scope team` on the exec stream after the dispatch completes. Learnings are promoted upward through five levels via `promote_learnings.sh`: dispatch → team → session → project → global. Each level filters for increasing generality; global `MEMORY.md` contains only cross-project process insights — no domain knowledge, no project names.

A quality gate ensures that only structured `## [DATE] Type` entries survive. `summarize_session.py` is explicitly instructed: 'Silence over noise — if no real signal found, output nothing.'

Importantly, **agents do not write `MEMORY.md` directly.** Learning is structural — built into the process, not prompted: it is extracted from exec streams post-run by claude-haiku (the model used for summarization). Agents see no memory instructions in their prompts; the system learns from what they *do*, not from what they're told to remember.

---

# Layer 3: Architecture — Deeper Connections

**INTENT.md as a living hypothesis**

`INTENT.md` is not a finished spec — it uses provisional framing throughout, with labels such as `current assumption:`, `to be confirmed:`, and `best guess:`. The `<!-- INTENT VERSION: v0.1 ... -->` header is maintained automatically by the intent session. Revisions are governed by an intent revision authority: the agent may update `INTENT.md` autonomously only for reversible, low-impact changes. Irreversible changes or those affecting already-approved deliverables require human approval. This framing is itself a design pattern — the system is built not to commit prematurely.

**The Memory Hierarchy**

Five MEMORY.md locations, each more abstract than the last, connected by four promotion steps:

1. Dispatch-level `MEMORY.md` — what happened in one agent run
2. Team-level `MEMORY.md` — aggregated patterns across dispatches for one team
3. Session-level `MEMORY.md` — cross-team coordination learnings, with team-internal details stripped
4. Project-level `MEMORY.md` — project-specific workflow and domain patterns
5. Global `MEMORY.md` — cross-project process insights only (project names, domain details stripped)

`MEMORY.md` files are gitignored — they live in `.sessions/` and `.worktrees/`, never on main. This keeps infrastructure concerns out of the code history.

**Four Temporal Moments**

The system integrates memory at four distinct moments in a task's lifetime. Two are currently active; two are designed but not yet wired in:

| Moment | Status | What happens |
|--------|--------|--------------|
| **Prospective** | Partially Active | `classify_task.py` reads ESCALATION.md before intent begins; full pattern/constraint retrieval is designed but not yet active |
| **Retrospective** | Active | `summarize_session.py` extracts learnings post-execution |
| **In-flight** | Designed (future) | Milestone checkpoint updates during execution |
| **Corrective** | Partially Wired | Real-time extraction at the moment of an error or escalation; extraction scaffolding is stubbed in `promote_learnings.sh` but not yet wired into the runtime |

The in-flight and corrective moments are designed and scaffolded — their specifications live in `/poc/projects/POC/poc-workflow/task-learning-evolution.txt` — but are not yet wired into the runtime. The architecture is built to accommodate them when they are wired in.
