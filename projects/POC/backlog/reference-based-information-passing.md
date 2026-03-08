# Reference-Based Information Passing

## Problem

When one actor in the CfA system needs context from another, the current
pattern is: read the full document, truncate it, and inline it into a
prompt. This creates several problems:

1. **Scale ceiling.** Artifacts are capped at 4000 chars (generate_review_bridge,
   generate_dialog_response) or 500 chars (classify_review summaries). Real
   plans, intents, and execution streams will outgrow these limits.

2. **Relevance dilution.** Dumping 4000 chars of a plan into a prompt about
   one specific question wastes context window on irrelevant sections. The
   human asks "did you test it?" and the dialog response LLM receives the
   entire plan instead of the testing-relevant section.

3. **Information hygiene.** The asker should state what they need and
   provide a reference. The responder pulls what is relevant. This mirrors
   how humans work: you send a link to the doc and say "look at section 3",
   not paste the whole doc into Slack.

4. **Coupling.** Every script that consumes context (classify_review,
   generate_dialog_response, generate_review_bridge) has its own
   file-reading and truncation logic. Changes to artifact format require
   updating all consumers.

## Principle

**When actor A asks actor B a question, A passes supporting documents as
references (file paths), not as inline content. B retrieves and chunks what
it needs. Quoting is judicious -- only explicitly state sections relevant
to the ask.**

## Current State

### generate_review_bridge.py
```python
content = read_file_content(file_path)    # reads up to 4000 chars
prompt = template.format(
    file_path=file_path,
    task=task,
    content=content,                       # inlined into prompt
)
```

### classify_review.py
```python
# Called from shell with pre-truncated summaries:
#   intent_summary = head -c 500 INTENT.md
#   plan_summary = head -c 500 plan.md
# These are inserted into the LLM prompt as inline context.
```

### generate_dialog_response.py
```python
content = read_artifact(artifact_path)     # up to 4000 chars
exec_tail = read_exec_stream(stream_path)  # last 2000 chars
# Both inlined into the prompt
```

### Shell orchestration (intent.sh, plan-execute.sh)
```bash
INTENT_SUMMARY=$(head -c 500 "$INTENT_FILE" 2>/dev/null || true)
PLAN_SUMMARY=$(head -c 500 "$PLAN_FILE" 2>/dev/null || true)
cfa_review_loop "PLAN_ASSERT" "$INTENT_SUMMARY" "$PLAN_SUMMARY" "$PLAN_FILE" ...
```

Every consumer reads its own slice of the file and stuffs it inline. There
is no shared retrieval layer.

## Design Direction

### Phase 1: Consolidate file reading into a shared retrieval utility

Create `scripts/artifact_reader.py` -- a small utility that:

- Accepts a file path and a query/purpose
- Returns relevant chunks (not the whole file)
- Supports multiple strategies:
  - `head`: first N chars (current behavior, for backward compat)
  - `tail`: last N chars (for exec streams)
  - `section`: heading-based extraction (for markdown artifacts)
  - `keyword`: lines containing specific terms (for differential matching)

```python
# artifact_reader.py

def read_artifact(
    path: str,
    strategy: str = 'head',
    max_chars: int = 4000,
    query: str = '',
) -> str:
    """Read relevant content from an artifact file.

    Strategies:
      head     -- first max_chars (backward compat default)
      tail     -- last max_chars (exec streams, logs)
      section  -- markdown section(s) matching query
      keyword  -- lines containing query terms
    """
```

All consumers import from this utility instead of rolling their own
`read_file_content()`. The retrieval strategy is chosen by the caller
based on its purpose.

### Phase 2: Pass paths, not content, through the shell pipeline

Instead of:
```bash
INTENT_SUMMARY=$(head -c 500 "$INTENT_FILE")
classify_review "PLAN_ASSERT" "$response" "$INTENT_SUMMARY" "$PLAN_SUMMARY"
```

Shift to:
```bash
classify_review "PLAN_ASSERT" "$response" "$INTENT_FILE" "$PLAN_FILE"
```

The Python script receives paths and uses `artifact_reader` to pull what
it needs. Each script decides its own retrieval strategy:

- **classify_review.py**: Needs the *gist* of the intent and plan to
  classify a human response. Uses `section` strategy to pull the
  objective/approach sections, or `head` for short docs.

- **generate_dialog_response.py**: Needs content *relevant to the
  question*. Uses `keyword` strategy seeded by the human's question to
  pull relevant sections, plus `tail` for recent exec stream.

- **generate_review_bridge.py**: Needs an overview for a 2-3 sentence
  summary. Uses `head` strategy (current behavior).

- **approval_gate.py**: Needs structural signals for novelty detection
  (per context-aware-proxy backlog item). Uses `head` + `keyword`
  against differential history.

### Phase 3: Structured artifact references (future)

For larger artifacts (multi-file projects, long execution streams), the
path-based approach may need to become a structured reference:

```json
{
  "type": "artifact_ref",
  "path": "/path/to/plan.md",
  "sections": ["## Approach", "## Testing"],
  "max_chars": 2000
}
```

This allows the orchestration layer to hint at which sections are relevant
without pre-reading the file. The receiving script can honor the hints or
ignore them.

## Migration Path

This is backward-compatible at every phase:

1. **Phase 1** adds `artifact_reader.py` as a new module. Existing scripts
   can adopt it incrementally -- each script replaces its own
   `read_file_content()` call with an import.

2. **Phase 2** changes the shell calling convention. The Python scripts
   accept both inline content (old) and file paths (new) by detecting
   whether the argument is a readable file path or raw text. This allows
   incremental migration of call sites.

3. **Phase 3** is additive -- structured references are a new protocol
   layered on top of path-based passing.

## Files Affected

| File | Change | Phase |
|------|--------|-------|
| `scripts/artifact_reader.py` | **NEW** ~80 lines | 1 |
| `scripts/generate_review_bridge.py` | Replace `read_file_content()` with import | 1 |
| `scripts/generate_dialog_response.py` | Replace inline reading with import | 1 |
| `scripts/classify_review.py` | Accept paths instead of inline summaries | 2 |
| `scripts/approval_gate.py` | Use artifact_reader for content checks | 2 |
| `ui.sh` | Pass paths instead of `head -c 500` results | 2 |
| `intent.sh` | Stop pre-reading intent summary | 2 |
| `plan-execute.sh` | Stop pre-reading plan/intent summaries | 2 |
| `scripts/tests/test_artifact_reader.py` | **NEW** ~30 tests | 1 |

## Testing

- Phase 1: Unit tests for artifact_reader strategies (head, tail, section,
  keyword). Test with markdown files, JSONL exec streams, empty files,
  missing files.
- Phase 2: Existing tests for classify_review, generate_dialog_response,
  generate_review_bridge continue to pass (backward compat). New tests
  verify path-based calling convention.
- Integration: Smoke test the full CfA loop with path-based passing.

## Relationship to Other Backlog Items

This feature is a prerequisite for **context-aware-proxy.md** -- the proxy
needs artifact_reader to do content-based novelty detection without
re-implementing file reading logic.

Both features share the principle: actors should pull context they need
from references, not receive pre-digested inline content. The proxy reads
artifacts to decide. The dialog system reads artifacts to answer. The
classifier reads artifacts to categorize. Each uses the retrieval strategy
appropriate to its purpose.
