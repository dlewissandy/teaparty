# Episodic Memory

Episodic memory is session-derived knowledge: what happened, what was learned, and how it should influence future work. Implemented under `teaparty/learning/episodic/`.

## Design choices

**Markdown as source of truth, SQLite as derived index.** Learnings are authored and stored as markdown files with YAML frontmatter at each scope level. A SQLite FTS5 database (`.memory.db`) is built as a derived index over these files; it can be rebuilt from the markdown at any time. Agents read and write markdown natively with the tools they already have, learnings persist in git alongside the work they describe, and retrieval gets BM25 ranking and optional vector search without agents needing to speak SQL.

**Structured entries with YAML frontmatter.** Each learning entry carries typed metadata:

```yaml
---
id: <uuid4>
type: declarative|procedural|directive|corrective
domain: task|team
importance: 0.0–1.0
reinforcement_count: <int>
last_reinforced: '2026-03-01'
status: active|retired|compacted
---
```

This is not undifferentiated prose. The metadata enables prominence scoring, temporal decay, and type-aware retrieval: a corrective learning with high reinforcement count surfaces ahead of a single-observation declarative one.

**Post-session extraction, not online learning.** Extraction runs after session completion, not during execution. Online learning would require interrupting agent execution to reflect, and the signal quality from a single in-progress interaction is low. Post-session extraction can see the full arc of the work: what was attempted, what succeeded, what the human corrected.

**LLM as the extraction engine.** Extraction calls Claude Haiku to analyze conversation streams and produce structured entries across ten extraction scopes. There is no separate ML pipeline.

## Hierarchy on disk

Learnings are stored at multiple scope levels.  Current on-disk layout (post-repo-flattening migration):

```
~/MEMORY.md                                                          # global (user-home)
<project>/MEMORY.md                                                  # project
<project>/institutional.md                                           # institutional (always loaded)
<project>/.teaparty/jobs/<job>/institutional.md                      # session/job-level
<project>/.teaparty/jobs/<job>/tasks/<task>/worktree/MEMORY.md       # team (per-task workgroup)
<project>/.teaparty/jobs/<job>/tasks/<task>/worktree/...             # additional team-scope artifacts
```

Legacy layout (pre-migration, still matched by `classify_scope()` for backward compatibility with any historical index rows):

```
projects/<project>/.sessions/<ts>/...                                # legacy team scope
```

## Extraction dimensions

- **Temporal (WHEN).** Extraction runs at four moments: prospective (before execution, `.premortem.md`), in-flight (at phase milestones, `.assumptions.jsonl`), corrective (at gate mismatches), and retrospective (post-session LLM pass). Corrective and retrospective are operational and feed promotion; prospective and in-flight are designed but not yet implemented (see [learning index status](index.md#status)).
- **Spatial (WHERE).** Entries are labeled by scope where they apply: team, session, project, global, dispatch.
- **Type (WHAT).** Entries are labeled by type/domain: observations, escalation, intent-alignment, corrective, procedural, directive.

The "ten extraction scopes" refers to entries that can be labeled as belonging to these categories. The labels describe what the entries are about, not when they were extracted.

## Retrieval

`memory_indexer.py` implements a three-stage retrieval pipeline:

1. **Query construction.** Claude Haiku extracts 5–8 key search terms from the raw task description, filtering common words and focusing on domain concepts. Falls back to the first 500 characters of the task on error.
2. **Two-phase scoring.** BM25 via FTS5 provides the primary retrieval signal. When vector embeddings are available (OpenAI `text-embedding-3-small` or Gemini `embedding-001`), scores blend at `0.7 × vector + 0.3 × BM25`. Falls back to BM25-only when embeddings are unavailable.
3. **Post-processing.** Results are weighted by prominence, multiplied by scope level (team=1.5×, project=1.2×, global=1.0×), then reranked for diversity using MMR with Jaccard similarity to avoid returning near-duplicates.

`retrieve()` accepts `learning_type` for type filtering and `max_chars` for per-type budget caps. Institutional learnings are loaded unconditionally (not through `retrieve()`); task-based learnings are fuzzy-retrieved with a dedicated budget. The two never compete for the same ranking.

The SQLite index maintains:
- **file_meta** — change detection (path, mtime, size, hash)
- **chunks** — document chunks with source path, char offset, and JSON metadata (preserved from YAML frontmatter)
- **chunks_fts** — FTS5 virtual table with BM25 ranking, Porter stemming, ASCII tokenization
- **embedding_cache** — optional vector embeddings keyed by content hash

## Prominence, reinforcement, decay

```
prominence    = importance × recency_decay × (1 + reinforcement_count)
recency_decay = max(DECAY_FLOOR, exp(-ln(2) / HALF_LIFE_DAYS × age_days))

HALF_LIFE_DAYS = 90
DECAY_FLOOR    = 0.1
scope multipliers: team=1.5, project=1.2, global=1.0
```

The decay floor is applied to `recency_decay`, not to final prominence. Time alone cannot make an entry invisible (decay bottoms out at 10%), but importance and reinforcement still differentiate entries at the floor. An ancient high-importance entry (0.9 × 0.1 = 0.09) still ranks above an ancient low-importance entry (0.2 × 0.1 = 0.02). Retired entries return prominence 0.0 regardless.

**Reinforcement tracking** is wired into the post-session pipeline. `extract_learnings()` calls `reinforce_entries()` at session end. The trigger is *retrieval*: when an entry's id appears in the session's `retrieved_ids` list (collected at session start by `memory_indexer.py`), its `reinforcement_count` is incremented by 1 and `last_reinforced` is set to today's date. Retrieval is a frequency-of-access signal, not a quality-of-use signal — even retrieved entries that the agent ignored count, on the grounds that retrieval reflects ongoing topical relevance.

**Compaction** (`compact.py`) deduplicates by ID, merges near-duplicates (Jaccard > 0.8), and removes retired entries. It runs post-write for session, project, and global scopes.

## Modules

- `entry.py` — structured entry format, type system, importance scoring
- `indexer.py` — FTS5 indexing, hybrid retrieval, scope multipliers, prominence scoring, MMR diversity
- `summarize.py` — session summarization across extraction scopes, calls the promotion pipeline
- `reinforce.py` — reinforcement signal tracking
- `compact.py` — deduplication, similarity merging, retired entry removal
- `detect_stage.py` — detects the current project stage from `INTENT.md` (stage metadata drives scope-aware extraction and retirement)
- `retire_stage.py` — stage-based retirement: retires `domain='task'` entries whose `phase` matches the just-ended project stage (contradiction-driven importance adjustment is in `consolidation.py`, not here)
