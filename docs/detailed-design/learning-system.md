# Learning System

The learning system implements the memory architecture described in [learning-system.md](../conceptual-design/learning-system.md). Post-session learning extraction runs via `learnings.py` (called from `session.py`). The storage layer combines markdown files (source of truth) with a SQLite FTS5 index (derived, for retrieval). Helper modules handle memory indexing, session summarization, reinforcement tracking, and memory compaction.

---

## Design Choices

**Markdown as source of truth, SQLite as derived index.** Learnings are authored and stored as markdown files with YAML frontmatter at each scope level. A SQLite FTS5 database (`.memory.db`) is built as a derived index over these files — it can be rebuilt from the markdown at any time. This gives the best of both worlds: agents read and write markdown natively with the tools they already have, learnings persist in git alongside the work they describe, and retrieval gets BM25 ranking and optional vector search without agents needing to speak SQL.

**Structured entries with YAML frontmatter.** Each learning entry (`memory_entry.py`) carries typed metadata:
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
This is not undifferentiated prose. The metadata enables prominence scoring, temporal decay, and type-aware retrieval — a corrective learning with high reinforcement count surfaces ahead of a single-observation declarative one.

**Post-session extraction, not online learning.** Learning extraction runs after session completion, not during execution. This is a deliberate simplification: online learning during a session would require interrupting agent execution to reflect, and the signal quality from a single in-progress interaction is low. Post-session extraction can see the full arc of the work — what was attempted, what succeeded, what the human corrected.

**LLM as the extraction engine.** Learning extraction calls the LLM (Claude Haiku) to analyze conversation streams and produce structured entries across 10 extraction scopes. There is no separate ML pipeline. The LLM reads the conversation transcript and writes learnings in the same way an agent would. This keeps the architecture simple and leverages the same reasoning capability that runs the agents.

**Hybrid retrieval with optional embeddings.** `memory_indexer.py` implements two-phase retrieval: BM25 via FTS5 as the primary signal, with optional vector embeddings (OpenAI or Gemini) for re-ranking. When embeddings are available, scores blend at 70% vector / 30% BM25. When unavailable, BM25 alone provides retrieval. This follows the OpenClaw pattern described in the conceptual design — no hard dependency on embedding providers, graceful degradation to keyword search.

**Scoped hierarchy with promotion.** Learnings are stored at the most specific scope where they apply. Promotion moves validated learnings upward through the hierarchy (dispatch → team → session → project → global), with increasingly aggressive filtering at each level. This prevents scope pollution: a correction that applied to one specific task doesn't automatically become global policy.

**Promotion evaluation chain ([#217](https://github.com/dlewissandy/teaparty/issues/217)).** `promotion.py` implements three promotion gates evaluated at session close (after rollup scopes, before reinforcement tracking):
- **Session → Project:** `find_recurring_learnings()` walks `.sessions/*/tasks/` across all sessions, clusters by similarity (pluggable: embedding-based or exact-match fallback), and promotes entries recurring in 3+ distinct sessions. Already-promoted entries are detected via similarity against `project/tasks/` and skipped.
- **Proxy exclusion:** `is_proxy_learning()` filters proxy-sourced paths (`proxy.md`, `proxy-tasks/`) before clustering. Proxy learnings never promote.
- **Project → Global:** `filter_project_agnostic()` evaluates entries via a pluggable judge function (LLM judgment). Conservative default: nothing promotes on judge failure. Infrastructure-ready but not yet triggered automatically.

`MemoryEntry` carries optional `promoted_from` and `promoted_at` fields (empty-string defaults) for promotion provenance tracking.

---

## What Exists

**Learning extraction.** `extract_learnings` (in `learnings.py`) runs at session end, reading conversation streams and producing structured memory entries. Called from `session.py` after orchestrator completion.

**Learning extraction dimensions:** The extraction pipeline operates across independent dimensions:

- **Temporal dimension (WHEN):** All extraction happens **retrospective only** — post-session, after the orchestrator completes. Prospective and in-flight extraction are **design targets** (would pause at milestones to reflect during execution).
- **Spatial dimension (WHERE):** Entries are labeled by scope where they apply: team, session, project, global, dispatch. These are metadata labels, not extraction timing.
- **Type dimension (WHAT):** Entries are labeled by type/domain: observations, escalation, intent-alignment, corrective, procedural, directive, etc. These categorize what kind of learning the entry represents.

The "10 extraction scopes" refers to entries that can be **labeled** (in their YAML frontmatter) as belonging to these categories. All extraction runs post-session; the labels describe what the entries are about, not when they were extracted.

**Memory hierarchy on disk.** Learnings are stored at multiple scope levels:
```
projects/MEMORY.md                                          # global
projects/<project>/MEMORY.md                                # project
projects/<project>/institutional.md                         # institutional (always loaded)
projects/<project>/tasks/                                   # task learnings (fuzzy-retrieved)
projects/<project>/.sessions/<ts>/MEMORY.md                 # session
projects/<project>/.sessions/<ts>/<team>/MEMORY.md          # team
projects/<project>/.sessions/<ts>/<team>/<dispatch>/MEMORY.md  # dispatch
```

**SQLite FTS5 index.** `memory_indexer.py` maintains `.memory.db` with:
- **file_meta** — change detection (path, mtime, size, hash)
- **chunks** — document chunks with source path, char offset, and JSON metadata (preserved from YAML frontmatter)
- **chunks_fts** — FTS5 virtual table with BM25 ranking, Porter stemming, ASCII tokenization
- **embedding_cache** — optional vector embeddings (OpenAI/Gemini) keyed by content hash
- Entry-aware chunking that preserves YAML frontmatter boundaries

**Prominence scoring.** Retrieval ranks entries by:
```
prominence = importance × recency_decay × (1 + reinforcement_count)
recency_decay = max(DECAY_FLOOR, exp(-ln(2)/HALF_LIFE_DAYS × age_days))

HALF_LIFE_DAYS = 90        # generous half-life; 90-day-old entry decays to 50%
DECAY_FLOOR    = 0.1       # recency_decay never falls below 10%
scope_multiplier: team=1.5, project=1.2, global=1.0
```

The decay floor is applied to the `recency_decay` factor, not to the final prominence value. This means time alone cannot make an entry invisible (decay bottoms out at 10%), but importance and reinforcement still differentiate entries at the floor. An ancient high-importance entry (0.9 × 0.1 = 0.09) still ranks above an ancient low-importance entry (0.2 × 0.1 = 0.02). A prominence-level floor would instead clamp both to the same value, losing that ordering.

Retired entries are exempt — they return prominence 0.0 regardless of the floor. Institutional learnings are loaded unconditionally and are not ranked by prominence.

**Scope multipliers integrated.** Scope multipliers ARE integrated into retrieval. `memory_indexer.py` defines `SCOPE_MULTIPLIERS` (line 747), `apply_scope_multipliers()` (line 769), and calls it during retrieval (line 852, 983). Team-level memories surface higher than global memories at equal similarity, providing appropriate prioritization.

**Retrieval strategy.** `memory_indexer.py` implements a three-stage retrieval pipeline:

1. **Query construction.** Claude Haiku extracts 5–8 key search terms from the raw task description, filtering common words and focusing on domain concepts. Falls back to the first 500 characters of the task on error.
2. **Two-phase scoring.** BM25 via FTS5 provides the primary retrieval signal. When vector embeddings are available (OpenAI `text-embedding-3-small` or Gemini `embedding-001`), scores are blended: `0.7 × vector_score + 0.3 × BM25`. Falls back to BM25-only when embeddings are unavailable.
3. **Post-processing.** Results are weighted by prominence (`importance × max(DECAY_FLOOR, recency_decay) × (1 + reinforcement_count)`), multiplied by scope level (team=1.5×, project=1.2×, global=1.0×), then reranked for diversity using MMR with Jaccard-based similarity to avoid returning near-duplicate entries.

**Memory context injection.** Retrieved learnings are injected into agent prompts at session start, giving agents access to accumulated knowledge from previous work.

**Helper modules:**
- `memory_entry.py` — structured entry format with YAML frontmatter, type system, importance scoring
- `memory_indexer.py` — FTS5 indexing, hybrid retrieval, scope multipliers integrated, prominence scoring, MMR diversity reranking
- `summarize_session.py` — session summarization across extraction scopes
- `track_reinforcement.py` — reinforcement signal tracking (increments count for retrieved entries)
- `compact_memory.py` — deduplication (by ID), similarity merging (Jaccard > 0.8), retired entry removal

**Reinforcement integration.** Reinforcement tracking is wired in. `extract_learnings()` calls `reinforce_entries()` at session end (per issue #91, resolved). When a retrieved learning entry was used by an agent, its `reinforcement_count` is incremented, raising its future prominence.

---

## Implementation Status

**Full learning type differentiation.** Resolved by [#197](https://github.com/dlewissandy/teaparty/issues/197). `classify_learning_type()` maps source paths to learning categories (`institutional`, `task`, `proxy`). `retrieve()` accepts `learning_type` and `max_chars` parameters for type-aware filtering and budget caps. Session callers pass task-based sources to `retrieve()` with `learning_type='task'`; institutional.md is loaded unconditionally via raw file read. Proxy-task retrieval is supported and wired into callers via `proxy-tasks/` directories.

**Scoped retrieval with type-aware budget allocation.** Resolved by [#197](https://github.com/dlewissandy/teaparty/issues/197). Scope multipliers are integrated (team=1.5×, project=1.2×, global=1.0×). Type-aware budget allocation is integrated: `retrieve()` accepts `max_chars` for per-type character budgets and `learning_type` for type filtering. Institutional memories are loaded unconditionally, task-based memories are fuzzy-retrieved with a dedicated budget.

**Continuous skill refinement.** Resolved by [#229](https://github.com/dlewissandy/teaparty/issues/229). Three refinement signals are implemented: (1) Execution friction detection — `detect_friction_events()` in `procedural_learning.py` scans stream JSONL post-session for permission denials, file-not-found errors, and fallback retries. (2) Friction-aware skill refinement — `refine_skill_with_friction()` sends friction events to an LLM to improve skill templates, wired into `extract_learnings()` as the `skill-friction-refine` scope. (3) Per-skill quality monitoring — `update_skill_friction_stats()` accumulates friction counts in skill frontmatter and flags high-friction skills as `needs_review`. Degraded skills (`needs_review: true`) are excluded from `lookup_skill()` results. Gate correction refinement was previously implemented by [#146](https://github.com/dlewissandy/teaparty/issues/146).

**Proxy learning integration.** Resolved by [#198](https://github.com/dlewissandy/teaparty/issues/198). Proxy corrections emit YAML-frontmattered markdown entries to `proxy-tasks/`, indexed by `memory_indexer.py`. The proxy retrieves both task learnings (`tasks/`) and proxy learnings (`proxy-tasks/`) via `memory_indexer.retrieve()` at gate time. Bidirectional feedback is wired: proxy corrections reach agents (via task retrieval), and agent learnings reach the proxy (via proxy retrieval).

## Remaining Gaps

**In-flight and prospective extraction.** The conceptual design defines four learning moments: prospective (before execution), in-flight (at milestones), corrective (at mismatch), and retrospective (after completion). Only retrospective (post-session) is wired into the orchestrator lifecycle. In-flight extraction would require pausing at milestones to reflect; prospective extraction would require reflection before execution. These are design targets for future work.

**Skill crystallization.** Skill lookup is operational: `skill_lookup.py` matches tasks against stored skills via threshold-based retrieval, and `engine.py` seeds PLAN.md from matching skills at planning phase entry. However, skill crystallization (automatically generalizing repeated plans into reusable skills) is a design target. The skill library is manually seeded; it does not grow automatically from agents' own work.

**Resolved issues:**
- ~~[#217](https://github.com/dlewissandy/teaparty/issues/217): Learning promotion chain~~ — resolved: recurrence detection, proxy exclusion, project-agnostic filtering
- ~~[#115](https://github.com/dlewissandy/teaparty/issues/115): Learning extraction silently fails~~ — resolved
- ~~[#73–#80](https://github.com/dlewissandy/teaparty/issues/73): GAP A5.* — missing scopes in the learning pipeline~~ — all resolved
- ~~[#84](https://github.com/dlewissandy/teaparty/issues/84): memory_indexer.py needs retrieve() function~~ — resolved: `retrieve()` importable
- ~~[#85](https://github.com/dlewissandy/teaparty/issues/85): summarize_session.py needs promote() function~~ — resolved
- ~~[#86](https://github.com/dlewissandy/teaparty/issues/86): compact_memory.py not wired in~~ — resolved: `_try_compact()` in promotion pipeline
- ~~[#91](https://github.com/dlewissandy/teaparty/issues/91): track_reinforcement.py not wired in~~ — resolved: `reinforce_entries()` called from `extract_learnings()`
- ~~[#101](https://github.com/dlewissandy/teaparty/issues/101): Enable procedural learning (plans → skills)~~ — resolved: skill lookup and plan seeding implemented
