# Intent: Finish the Learning Subsystem

## What This System Is For

The goal is an agent that knows the human well enough to start working from minimal cues. It arrives at a session with accumulated institutional knowledge — what the human values, how they think, where they grant autonomy, what cost and risk thresholds would make them want to stop — and uses that knowledge to act rather than ask. When something unforeseeable at session start exceeds the human's known tolerance, the agent pauses — not with a question, but with researched alternatives, a clear recommendation, and enough context that the human can redirect without re-explaining what they already communicated in prior sessions. This is the end state, reached through accumulated calibration over many sessions.

## What Remains

**Error visibility.** Both extraction calls in `run.sh` use `|| true`, which suppresses return codes and stderr. A failing extraction produces an empty OBSERVATIONS.md or ESCALATION.md with no indication why. Replace both `|| true` guards with error reporting that surfaces failures to stderr.

**Output quality validation.** Extraction has not been validated against actual intent streams. Run extraction against existing intent streams in `projects/POC/.sessions/` and verify that OBSERVATIONS.md and ESCALATION.md entries meet the success criteria bar — specific, actionable observations and domain-indexed escalation entries with cited signals. Generic output means the prompts need revision.

**Retroactive extraction.** `scripts/retroactive_extract.py` exists but has not been confirmed to have run against the existing `.sessions/` intent streams. Run it to populate the baseline index. Retrieval cannot be meaningfully tested without real signal in the index.

## The Learning Loop

**Sessions deepen the model.** Every intent conversation is signal. What the human emphasizes, what they push back on, what they accept without comment, what they correct — all of this is evidence about preferences, values, and working style. Post-session extraction runs against the intent stream and appends to OBSERVATIONS.md and ESCALATION.md. The `intent-alignment` scope in `summarize_session.py` compares the produced INTENT.md against what was actually delivered and appends observations about gaps and divergences.

**The model enables action.** At session start, relevant observations and escalation calibrations are retrieved against the current task. The agent uses this to derive intent and proceed — enough context to make sound decisions without asking.

**Corrections refine the calibration.** Every autonomous action that gets corrected and every escalation that proves unnecessary is a calibration data point. At cold start the agent escalates more. As domain-specific calibration accumulates, the threshold shifts toward autonomy in domains where the human has demonstrated consistent tolerance.

## Objective

Both implementation streams are complete: `summarize_session.py` correctly targets the intent stream for extraction, and `memory_indexer.py` provides SQLite FTS5 + hybrid embedding retrieval integrated at session start. The remaining work is validation and error surfacing, in this order:

**1. Make failures visible.** Replace `|| true` on both extraction calls in `run.sh` with error handling that reports failures to stderr. Until this is done, empty output files are indistinguishable from correct output.

**2. Validate extraction quality.** Run extraction against existing intent streams in `projects/POC/.sessions/` and verify OBSERVATIONS.md and ESCALATION.md entries against the success criteria: observations specific enough to act on, escalation entries that name a domain and cite a signal. If output is generic, revise the prompts.

**3. Run retroactive extraction.** Execute `scripts/retroactive_extract.py` against existing `.sessions/` intent streams to populate the baseline index. This must happen before retrieval can be meaningfully tested.

**4. Confirm retrieval.** Verify that `memory_indexer.py` is serving relevant chunks at session start for representative task descriptions. Confirm the `--context-file` injection flags for MEMORY.md, OBSERVATIONS.md, and ESCALATION.md have been removed from `run.sh` and `intent.sh`.

## Success Criteria

**Extraction** is working when:
- OBSERVATIONS.md entries are specific enough that a cold agent could act on them. "The human consistently rejects deliverables written in first-person agent narration" is valid. "The human values quality" is not.
- ESCALATION.md entries name a domain, a direction (more or less autonomous), and cite the specific signal that produced the entry.
- Sessions where the human provides no meaningful preference signal produce no new entries in either file.
- Retroactive extraction from existing intent streams populates a baseline index.

**Retrieval** is working when:
- Memory is stored as chunks in SQLite rather than injected as whole files.
- Relevant chunks are retrieved against the current task description at session start.
- The index rebuilds when source files change.
- Memory accumulates across sessions without degrading startup time or burying recent entries.

**The system is on track** when a returning session opens without the agent asking questions it could have answered from prior observations, and when the agent does surface a blocker, it arrives with researched alternatives and a recommendation rather than a raw question.

## Decision Boundaries

**Silence over noise.** If haiku cannot find real signal in the source material, the correct output is nothing. Generic observations pollute the index and pre-populate wrong priors.

**Escalation entries are domain-indexed.** The domain is extracted from content, not assigned generically. A human correcting a file-naming decision produces a file-naming domain entry. Pushing back on an architecture choice produces an architecture domain entry.

**When the agent surfaces a blocker, it brings solutions.** An escalation is not a question. The agent has already researched the option space, formed a view based on what it knows about the human, and is surfacing because the decision has implications that exceed its calibration — unforeseen cost, unforeseen risk, irreversible action outside established patterns. The human receives situation + options + recommendation.

**Divergence between stated and revealed preferences is surfaced, not auto-resolved.** When the human states X in prior intents but corrects toward Y in practice, the system surfaces that contradiction explicitly rather than silently updating the model.

**Retrieval replaces injection.** Once retrieval is working, `--context-file` flags for MEMORY.md, OBSERVATIONS.md, and ESCALATION.md in `run.sh` and `intent.sh` are removed. Adding retrieval on top of wholesale injection makes context worse, not better.

**Embedding provider fallback.** OpenAI `text-embedding-3-small` if the API key is present, then Gemini `gemini-embedding-001`, then BM25-only. BM25-only is the minimum viable retrieval mode. No new infrastructure is required.

## Constraints

- Python and bash only. The indexer is a Python script; the SQLite file is gitignored and rebuildable from source at any time.
- Chunking: 1600 characters per chunk, 320-character overlap (character-based, structure-blind).
- sqlite-vec is optional; fall back to FTS5/BM25 if unavailable.
- Retrieval queries at session start are constructed from the task description using the same single haiku-call pattern as `projects/POC/scripts/classify_task.py`.
- Downstream outcome learning (tracking edit-to-acceptance ratios) is deferred.

## Reference Material

Treat these as specifications, not background reading:

- `projects/agentic-memory/openclaw-memory-architecture-R1.3.md` — chunking algorithm, embedding provider selection, SQLite schema
- `projects/agentic-memory/openclaw-memory-config-schema-R1.7.md` — hybrid weights, candidate multiplier, MMR defaults
- `projects/agentic-memory/R-1.6-memory-write-paths.md` — write triggers, daily log vs. MEMORY.md distinction
- `projects/agentic-memory/alternative-memory-backends.md` — Mem0's Auto-Recall/Auto-Capture lifecycle, the model for wiring retrieval into session start and extraction into session end
- `projects/POC/intent-engineering-spec.md` — governing specification for what the intent gathering system produces and what institutional memory must contain to support it
