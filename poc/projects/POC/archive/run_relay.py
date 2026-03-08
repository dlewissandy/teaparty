#!/usr/bin/env python3
"""Run relay.sh with the intent-engineering editing task."""
import subprocess
import sys

TASK = r"""Read the file at /Users/darrell/git/teaparty/poc/projects/POC/intent-engineering-detailed-design.md completely. Then apply the following seven changes exactly as specified. Do not change anything not listed. Preserve all existing JSON schemas, all existing code blocks unless a change explicitly replaces one, and all existing prose that is not being replaced. When all changes are made, write the complete revised file back to the same path.

CHANGE 1: Replace Section 1 entirely.

Replace everything from the heading "## 1. Theoretical Foundation" at the top of the file down through the sentence "This POC operates at the individual and small-team scale. The principles apply without modification to larger deployments." and the "---" separator that follows it, with the following content (verbatim):

## 1. Foundation

The theoretical basis for intent engineering — the intent gap, the Klarna pattern, the three missing architectural layers, and the relationship between prompt engineering, context engineering, and intent engineering — is documented in `intent-engineering-spec.md`. This document begins where the spec ends: it specifies how to build the system the spec describes. Readers who need the rationale should read the spec first. Readers who need the implementation specification should start here.

---

(That is the complete replacement for Section 1 plus its trailing "---" separator. Everything before "## 2." that was the old Section 1 is gone.)


CHANGE 2: Insert new subsection 5.0 at the start of Section 5.

Find the line "### 5.1 What Memory Must Contain". Insert the following block immediately before it, with a blank line between the new block and "### 5.1":

### 5.0 Current Implementation vs. Target Architecture

The JSON schemas in Sections 5.1–5.4 describe the target record format for institutional memory. The POC implementation uses a simpler markdown-backed architecture that is already built and functional. Understanding the gap prevents implementers from building the target architecture before the POC validates the approach.

**Current implementation (what exists today):**
- `OBSERVATIONS.md` — human preference signals appended by `summarize_session.py` (scope: `observations`)
- `ESCALATION.md` — autonomy calibration signals appended by `summarize_session.py` (scope: `escalation`)
- `.memory.db` — SQLite FTS5 index of the above files, built and queried by `memory_indexer.py`
- Retrieval uses BM25 full-text search with optional hybrid embedding reranking

**How the JSON schemas apply today:** The schemas in 5.1–5.4 define the *semantic structure* of what `summarize_session.py` extracts and writes to the markdown files. They are not stored as discrete JSON records; they are the conceptual model that shapes the extraction prompts. A user observation record, for example, becomes a structured paragraph in OBSERVATIONS.md rather than a JSON file entry.

**When to migrate:** When the observation corpus grows large enough that flat-file retrieval degrades (rough threshold: OBSERVATIONS.md exceeds 50KB or retrieval precision drops visibly), migrate to structured JSON storage. Until then, the markdown-backed architecture provides sufficient warm-start quality with minimal infrastructure.

**Embedding provider:** `memory_indexer.py` supports OpenAI and Gemini embeddings but requires API keys. Run BM25-only for the POC (omit the embedding provider flag) unless embeddings are already configured in the environment. BM25 is adequate for corpora with fewer than 100 observations.

(End of Change 2 block — place a blank line after this block, then "### 5.1 What Memory Must Contain" continues as before.)


CHANGE 3: Add escalation injection spec at end of Section 7.2.

Find the paragraph in Section 7.2 that ends with: "The outcome is written to the escalation calibration record in institutional memory after the session completes."

Immediately after that paragraph, insert the following new content:

**Injecting escalation context into execution agents.** The domain thresholds stored in `ESCALATION.md` must reach the execution agent at session start. `plan-execute.sh` accomplishes this by adding `--context-file "$PROJECT_DIR/ESCALATION.md"` to both the plan and execute invocations. The agent reads the injected context and uses the domain thresholds when evaluating the action cost matrix from Section 4.3.

When a calibration signal occurs — the human responds to an escalation with "just handle it" or with a correction — `plan-execute.sh` appends the signal to `ESCALATION.md` at session end by calling:

```bash
python3 "$SCRIPT_DIR/scripts/summarize_session.py" \
  --stream "$EXEC_STREAM" \
  --scope escalation \
  --session-dir "$STREAM_DIR" &
```

This runs asynchronously after session completion. The signal is available to the next session's warm-start retrieval.

(End of Change 3.)


CHANGE 4: Replace the warm-start context injection paragraph in Section 8.1.

Find this exact text block in Section 8.1. It is a bold paragraph, followed by a fenced code block, followed by a trailing sentence.

The bold paragraph starts with: "**Warm-start context injection.** Before constructing the initial prompt, intent.sh must query institutional memory"
It ends with: "These elements are formatted as a section in the initial prompt:"

The fenced code block contains:
--- Prior context (from institutional memory) ---
[pre-populated observations, each with source and confidence]
--- end prior context ---

The trailing sentence is: "This section is injected after the task description and before any other context files."

Replace ALL of that (the bold paragraph, the fenced code block, and the trailing sentence) with the following new content:

**Warm-start context injection.** Before constructing the initial prompt, `intent.sh` queries institutional memory for observations relevant to the current task. The query uses `memory_indexer.py`, which accepts the following CLI arguments:

```bash
WARM_START_FILE=$(mktemp)
python3 "$SCRIPT_DIR/scripts/memory_indexer.py" \
  --db "$PROJECT_DIR/.memory.db" \
  --source "$PROJECT_DIR/OBSERVATIONS.md" \
  --source "$PROJECT_DIR/ESCALATION.md" \
  --task "$TASK_DESCRIPTION" \
  --output "$WARM_START_FILE" \
  --top-k 10 2>/dev/null
WARM_START_CONTEXT=$(cat "$WARM_START_FILE" 2>/dev/null)
rm -f "$WARM_START_FILE"
```

If `WARM_START_CONTEXT` is empty (because the memory files are new, empty, or retrieval found nothing), `intent.sh` proceeds without warm-start context — cold-start behavior is the automatic fallback. On first use, `OBSERVATIONS.md` and `ESCALATION.md` are empty, so this path always runs cold. Warm-start activates automatically as sessions accumulate observations.

When `WARM_START_CONTEXT` is non-empty, it is formatted as a section in the initial prompt:

```
--- Prior context (from institutional memory) ---
[retrieved observations and escalation calibration data]
--- end prior context ---
```

This section is injected after the task description and before any other context files.

(End of Change 4 replacement.)


CHANGE 5: Replace the warmStartEnabled sentence in Section 8.2.

Find the sentence in Section 8.2 that contains "warmStartEnabled". It reads approximately:
"The updated configuration should also set "warmStartEnabled": true on the intent-lead agent to signal that it should look for and acknowledge "(from prior sessions)" markers in the initial prompt."

Replace that entire sentence with:
"Warm-start behavior is controlled entirely by `intent.sh`: if the memory query returns observations, they are injected into the initial prompt with "(from prior sessions)" markers; if it returns nothing, the cold-start path runs. No agent-level flag is needed. The intent-lead agent handles both cases based on whether the prior context block appears in its initial prompt."


CHANGE 6: Replace delivery-point instrumentation paragraph in Section 7.3 and remove redundant sentence.

Step 6a: Find the paragraph in Section 7.3 that begins:
"The primary feedback signal is delivery-point instrumentation: when the human receives the output, how much do they edit before accepting it? A high edit-to-acceptance ratio indicates the output did not reflect the intent. A low ratio indicates alignment. This signal requires no additional effort from the human and is available immediately."

Replace that entire paragraph with:
"**Future: Delivery-point instrumentation.** The highest-value feedback signal would be delivery-point instrumentation — tracking how much the human edits output before accepting it, with a high edit-to-acceptance ratio signaling misalignment. This requires file-system instrumentation that is out of scope for the POC. It is documented here as a post-MVP capability. Do not implement it in the current phase. When instrumentation is built, corrections must be distinguished from extensions: a correction changes something the agent produced (misalignment signal); an extension adds something the agent could not have produced from available context (not a misalignment signal)."

Step 6b: After making the replacement above, find and DELETE this sentence from Section 7.3 (it is now redundant):
"Corrections are distinguished from extensions: a correction changes something the agent produced (misalignment signal), an extension adds something the agent could not have produced from the available context (not a misalignment signal). The system must distinguish these when logging signals."


CHANGE 7: Insert Section 9 (Open Questions) before END OF DOCUMENT.

Find the line "END OF DOCUMENT" at the very bottom of the file. Insert the following block immediately before it (after the "---" separator line that precedes END OF DOCUMENT):

## 9. Open Questions

These items cannot be resolved until the POC runs enough sessions to generate calibration data. Each entry states the question, why it cannot be resolved now, and what must happen before it can be resolved.

**Escalation threshold delta calibration.** The risk tolerance model uses deltas of 0.05 (positive signal), 0.10 (negative signal), and 0.02 (neutral signal) for threshold adjustment. These values are asserted without empirical basis — no calibration data exists yet because the system has not run. They cannot be validated until the POC completes 10 or more sessions and threshold trajectories can be evaluated against actual escalation outcomes. The planning phase must instrument the threshold record to capture the history of adjustments so that drift can be analyzed after data accumulates. The deltas are reasonable starting values; treat them as defaults to be tuned, not specifications to be preserved.

**Scope assignment for team and organizational observations.** `summarize_session.py` assigns individual scope to observations by default and broader scope to statements containing markers like "we always" or "the team requires." This heuristic is untested. It cannot be validated until the system processes sessions involving explicit team or organizational statements. The planning phase must design a review mechanism — a human-readable report of scope assignments from each session — so that misclassifications are visible and correctable before they propagate through the scope hierarchy.

**Memory-to-plan handoff for open questions.** INTENT.md open questions are a mandatory handoff to the planning team (Section 7.1). The planning team must research options and present them to the human before execution begins. The current pipeline has no mechanism to verify that open questions were resolved before execution starts — `plan-execute.sh` does not check INTENT.md for unresolved open questions before launching the execution phase. This gap cannot be resolved without running the pipeline end-to-end and observing whether unresolved questions cause execution failures. The planning phase must add an INTENT.md pre-flight check to `plan-execute.sh` that warns (does not block) if open questions are present at execution start.

---

(The above "---" is a new separator that belongs between Section 9 and END OF DOCUMENT.)


IMPORTANT: Write the complete revised file to /Users/darrell/git/teaparty/poc/projects/POC/intent-engineering-detailed-design.md when all changes are applied. Confirm the file was written successfully.
"""

result = subprocess.run(
    ["/Users/darrell/git/teaparty/poc/projects/POC/relay.sh", "--team", "coding", "--task", TASK],
    capture_output=False,
    text=True,
)
sys.exit(result.returncode)
