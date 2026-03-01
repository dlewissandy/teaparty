# Intent: Finish the Learning Subsystem

## What This System Is For

The goal is an agent that knows the human well enough to start working from minimal cues. It arrives at a session with accumulated institutional knowledge — what the human values, how they think, where they grant autonomy, what cost and risk thresholds would make them want to stop — and uses that knowledge to act rather than ask. When something unforeseeable at session start exceeds the human's known tolerance, the agent pauses — not with a question, but with researched alternatives, a clear recommendation, and enough context that the human can redirect without re-explaining what they already communicated in prior sessions. This is the end state, reached through accumulated calibration over many sessions.

## What Is Broken

**The extraction is broken.** `projects/POC/run.sh` calls `projects/POC/scripts/summarize_session.py` with the intent stream for observations and escalation extraction. Intent stream files exist in `projects/POC/.sessions/` from prior sessions. OBSERVATIONS.md and ESCALATION.md are empty everywhere. The call is failing — confirmed broken, not a signal-strength issue. The failure is silent behind `|| true`.

**When extraction does run, it extracts the wrong things.** The prompts in `summarize_session.py` treat the execution stream as equivalent to the intent stream. The exec stream contains agent-to-agent coordination traffic. The intent stream — written to `projects/POC/.sessions/<timestamp>/.intent-stream.jsonl` by `projects/POC/intent.sh` — is where the human actually speaks: preference signals, corrections, pushback, stated values. MEMORY.md is being populated with coordination patterns extracted from execution. OBSERVATIONS.md should be populated with human-preference signals extracted from the intent stream. The current prompts do not make that distinction.

**The storage model doesn't scale.** MEMORY.md, OBSERVATIONS.md, and ESCALATION.md are injected wholesale as context at session start via `--context-file` flags in `run.sh` and `intent.sh`. As they grow, context windows fill with increasingly irrelevant content. An indexed retrieval system — SQLite with FTS5, optional sqlite-vec for embeddings — replaces injection with relevance queries against the current task. None of this exists yet.

## The Learning Loop

**Sessions deepen the model.** Every intent conversation is signal. What the human emphasizes, what they push back on, what they accept without comment, what they correct — all of this is evidence about preferences, values, and working style. Post-session extraction runs against the intent stream and appends to OBSERVATIONS.md and ESCALATION.md. The `intent-alignment` scope in `summarize_session.py` compares the produced INTENT.md against what was actually delivered and appends observations about gaps and divergences.

**The model enables action.** At session start, relevant observations and escalation calibrations are retrieved against the current task. The agent uses this to derive intent and proceed — enough context to make sound decisions without asking.

**Corrections refine the calibration.** Every autonomous action that gets corrected and every escalation that proves unnecessary is a calibration data point. At cold start the agent escalates more. As domain-specific calibration accumulates, the threshold shifts toward autonomy in domains where the human has demonstrated consistent tolerance.

## Objective

Two work streams, sequenced: extraction first, retrieval second. Retrieval cannot be meaningfully built or validated until the index contains real signal, so the streams are not parallel in practice even though the implementations are independent.

**1. Fix extraction.** Diagnose why the extraction call in `projects/POC/run.sh` is failing silently. Fix the call, then verify the prompts in `summarize_session.py` correctly target the intent stream (not the exec stream) as the primary signal source. If the prompts are wrong, rewrite the `observations` and `escalation` scopes to extract human-preference signal specifically — what the human values, pushes back on, corrects, or states as constraint. Once extraction is running correctly, retroactively extract from existing intent streams in `projects/POC/.sessions/` to populate a baseline index.

**2. Build indexed storage and retrieval.** Implement a Python SQLite indexer (FTS5 + optional sqlite-vec) that chunks OBSERVATIONS.md, ESCALATION.md, and MEMORY.md, maintains an index, and answers relevance queries against a task description. Replace `--context-file` injection of these three files in `projects/POC/run.sh` and `projects/POC/intent.sh` with retrieval calls. The SQLite file lives adjacent to the markdown files it indexes, is gitignored, and is rebuildable from source.

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

## Open Questions

- Has any implementation work begun on either stream since this INTENT.md was written? Knowing what's been attempted (even if incomplete or reverted) shapes where the planner starts.

## Reference Material

Treat these as specifications, not background reading:

- `projects/agentic-memory/openclaw-memory-architecture-R1.3.md` — chunking algorithm, embedding provider selection, SQLite schema
- `projects/agentic-memory/openclaw-memory-config-schema-R1.7.md` — hybrid weights, candidate multiplier, MMR defaults
- `projects/agentic-memory/R-1.6-memory-write-paths.md` — write triggers, daily log vs. MEMORY.md distinction
- `projects/agentic-memory/alternative-memory-backends.md` — Mem0's Auto-Recall/Auto-Capture lifecycle, the model for wiring retrieval into session start and extraction into session end
- `projects/POC/intent-engineering-spec.md` — governing specification for what the intent gathering system produces and what institutional memory must contain to support it
