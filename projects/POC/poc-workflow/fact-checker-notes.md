# Fact-Check Report: Intent Pipeline & Learning System Technical Explanation

## Summary

This document contains one significant internal inconsistency regarding the memory hierarchy structure, several claims about "active" vs. "future" capability status that are overstated, and claims about specific learning moments that need verification.

---

## Issues Found

### CRITICAL: Memory Hierarchy Level Count Mismatch

**Location:** Layer 3, "The Memory Hierarchy" section

**Claim as written:**
"Five levels, each more abstract than the last:
1. Dispatch-level MEMORY.md
2. Team-level MEMORY.md
3. Session-level MEMORY.md
4. Project-level MEMORY.md
5. Global MEMORY.md"

**Conflict/Concern:**
- Layer 2 states: "learnings are promoted up **four levels** via `promote_learnings.sh`"
- Layer 3 lists **five** distinct levels in the memory hierarchy
- The four promotion scopes in promote_learnings.sh (team, session, project, global) actually represent **four** promotion boundaries, not five levels
- The confusion arises because there are five distinct MEMORY.md files but only four promotion operations between them

**Verification from code (promote_learnings.sh):**
```
--scope team     (dispatch → team)
--scope session  (team → session)
--scope project  (session → project)
--scope global   (project → global)
```

This shows four promotion operations connecting five distinct MEMORY.md locations.

**Suggested correction:**
Either clarify that there are "five MEMORY.md files across four promotion levels" or reframe Layer 3 to say "Four levels of promotion connecting five MEMORY.md locations" to match Layer 2's language consistently.

---

### OVERSTATED CAPABILITY: "Warm-started classification" Active vs. Future

**Location:** Layer 2, "Memory feeding into intent" section

**Claim as written:**
"Before the intent session begins, `classify_task.py` reads the project-level `ESCALATION.md` and `MEMORY.md` (up to 2000 chars each). `ESCALATION.md` holds domain-indexed autonomy calibrations... By the time the intent dialog even begins, the system already has a posture shaped by lessons from prior runs."

**Status claimed:** Active (described in present tense as something "is" happening)

**Conflict/Concern:**
- Reading memory into `classify_task.py` for warm-start context IS currently implemented
- BUT the INTENT.md document itself does NOT describe memory being injected into the intent agent's prompt at session start
- The statement about `classify_task.py` warm-starting is accurate, but the broader claim about how memory shapes the intent session output is incomplete
- `intent.sh` shows no explicit memory injection into the initial prompt structure

**Verification from code (classify_task.py):**
```python
def read_memory_context(projects_dir: str, slug: str) -> str:
    """Read ESCALATION.md and MEMORY.md for warm-start context. Truncate to 2000 chars each."""
    # ... reads both files and injects them into CLASSIFY_PROMPT
```

This confirms warm-start reading is active.

**Verification from code (intent.sh):**
```bash
for ctx_file in "${CONTEXT_FILES[@]}"; do
  if [[ -f "$ctx_file" && -s "$ctx_file" ]]; then
    INITIAL_PROMPT="$INITIAL_PROMPT
--- $LABEL ---
$(cat "$ctx_file")"
```

Context files CAN be passed to intent.sh via `--context-file` arguments, but there is no automatic MEMORY.md injection into intent.sh's initial prompt. This is optional/manual, not automatic.

**Suggested correction:**
Clarify that warm-start memory injection into classify_task.py is active, but memory injection into the intent agent's own prompt is not automatic—it requires explicit `--context-file` parameters passed to intent.sh. If this is a designed-but-not-wired feature, move it to the "future" section.

---

### OVERSTATED CAPABILITY: "retroactive_extract.py" and OBSERVATIONS.md / ESCALATION.md

**Location:** Layer 2, "Intent recording for learning" section

**Claim as written:**
"`intent.sh` records the entire dialog to `.intent-stream.jsonl`. Post-session, `retroactive_extract.py` reads this stream and populates two files: `OBSERVATIONS.md` (human preference signals inferred from the dialog) and `ESCALATION.md` (autonomy calibrations derived from how the human pushed back or agreed). These feed back into the next `classify_task.py` run — the loop closes."

**Status claimed:** Active (present tense, described as already functioning)

**Concern:**
- `retroactive_extract.py` EXISTS and CAN extract to OBSERVATIONS.md and ESCALATION.md
- BUT there is NO evidence in the codebase that these files are automatically consulted during the next task's `classify_task.py` call
- `classify_task.py` currently reads `ESCALATION.md` (confirmed), but the mechanism for OBSERVATIONS.md feeding into intent behavior is not evident
- `retroactive_extract.py` is documented as a one-shot retroactive tool, not an automatic post-session extraction step

**Verification from code (classify_task.py):**
```python
def read_memory_context(projects_dir: str, slug: str) -> str:
    """Read ESCALATION.md and MEMORY.md for warm-start context..."""
    for fname in ["ESCALATION.md", "MEMORY.md"]:
```

This confirms ESCALATION.md is read, but OBSERVATIONS.md is NOT read by classify_task.py.

**Verification from code (retroactive_extract.py):**
```python
"""One-shot retroactive extraction from all intent streams in .sessions/.

Run this once to populate OBSERVATIONS.md and ESCALATION.md from existing
intent streams. Safe to re-run — appends only; does not deduplicate.
```

Marked as "one-shot" and manually invoked, not automatic.

**Suggested correction:**
State that `retroactive_extract.py` CAN be run to extract OBSERVATIONS.md and ESCALATION.md, and ESCALATION.md DOES feed into `classify_task.py`. But clarify that this is not an automatic post-session process—it must be manually invoked. If automatic extraction is a future design intent, move to the future section.

---

### INCONSISTENCY: "Four Temporal Moments" Status Labels

**Location:** Layer 3, "Four Temporal Moments" table

**Claim as written:**
The table marks Prospective and Retrospective as "Active" and In-flight and Corrective as "Designed (future)".

**Concern:**
- Layer 2 states: "By the time the intent dialog even begins, the system already has a posture shaped by lessons from prior runs" — implying prospective learning is active
- But prospective learning's full scope (project patterns, domain constraints, known failure modes) is only partially active
- Current active prospective learning: warm-start of ESCALATION.md in classify_task.py
- Future prospective learning: memory_indexer.py for BM25 + embeddings retrieval (explicitly stated as "not yet fully active")
- Corrective learning extraction IS stubbed in promote_learnings.sh with a `corrective` scope that calls summarize_session.py with `--scope corrective`

**Verification from code (promote_learnings.sh):**
```bash
corrective)
  # ... calls summarize_session.py with --scope corrective
```

This suggests corrective extraction is at least partially wired, not purely designed.

**Suggested correction:**
Refine the "Prospective" status to "Partially Active (warm-start of ESCALATION.md; full pattern/constraint retrieval designed)" and clarify that Corrective has extraction scaffolding stubbed but may not be fully integrated into the runtime workflow.

---

### FLAG ONLY: Pre-mortem and In-flight Learning Status

**Location:** Layer 3, "Four Temporal Moments" table and Layer 2

**Claim:** In-flight and Corrective are "Designed (future)"

**Context:** The learning-evolution.md document discusses pre-mortem and in-flight learning extensively with implementation details. The promote_learnings.sh script has stubs for "prospective", "in-flight", and "corrective" scopes, suggesting at least partial implementation scaffolding.

**Flag for author:** The status of these four moments may require clarification of what "wired" vs. "stubbed" vs. "designed but untested" means in this workflow. The promote_learnings.sh script suggests infrastructure exists to wire these, but whether the runtime actually invokes them during live sessions is not clear from the documentation reviewed.

---

### MINOR: Inconsistent Terminology

**Location:** Layer 2 and Layer 3

**Issue:**
- Layer 2 refers to "post-run extraction" and "post-execution"
- Layer 2 states learning is "promoted upward through **four levels**"
- Layer 3 states there are **five** distinct MEMORY.md levels

**Suggested standardization:**
Use "five MEMORY.md locations / four promotion boundaries" terminology consistently throughout, or restructure the hierarchy description to use only four levels if that is the intended model.

---

## Verification Summary

| Category | Verified | Overstated | Needs Clarification |
|----------|----------|-----------|---------------------|
| Memory hierarchy count | | X | X (4 vs 5) |
| Warm-start via ESCALATION.md in classify_task | X | | |
| Memory injection into intent.sh prompt | | X | (Optional, not automatic) |
| retroactive_extract.py integration | | X | (One-shot, not automatic) |
| Four Temporal Moments status | | X | (Prospective partially active; Corrective partially wired) |
| Pre-mortem scaffolding | | | (Flag for clarification) |

---

## Recommendations

1. **Critical:** Resolve the 4-vs-5 levels inconsistency in Layer 3's memory hierarchy section
2. **High:** Clarify which learning moments are fully active vs. partially wired vs. designed-but-unstubbed
3. **Medium:** Specify whether retroactive extraction and memory injection into intent.sh are automatic or manual workflows
4. **Medium:** Standardize terminology around "promotion levels" vs. "MEMORY.md locations" throughout both layers
