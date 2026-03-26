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

**Type-aware retrieval routing.** Adapted from AdaMem (Yan et al., 2026), retrieval queries are dispatched to type-specific stores rather than searched against a single undifferentiated index. The routing is caller-driven: `engine.py` requests task learnings with a dedicated token budget, `proxy_agent.py` requests proxy-task patterns with a separate budget, and institutional and proxy-preferential learnings are loaded unconditionally at matching scope. This replaces the single `retrieve()` call with per-type retrieval paths — each with its own budget, scoring strategy, and loading behavior. See [#197](https://github.com/dlewissandy/teaparty/issues/197).

**Persona distillation to Claude Code memory.** Stable user preferences discovered by the proxy are distilled from ACT-R episodic chunks and written as Claude Code memory files (`~/.claude/projects/<project>/memory/`). These files are automatically loaded into every Claude Code session — including proxy `claude -p` invocations — providing always-loaded preference access with no custom infrastructure. The human can see, edit, and correct these files, creating a transparent feedback loop. Distillation runs post-session alongside learning extraction. See [#197](https://github.com/dlewissandy/teaparty/issues/197).

**Scoped hierarchy with promotion.** Learnings are stored at the most specific scope where they apply. Promotion moves validated learnings upward through the hierarchy (dispatch → team → session → project → global), with increasingly aggressive filtering at each level. This prevents scope pollution: a correction that applied to one specific task doesn't automatically become global policy.

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
recency_decay = exp(-ln(2)/30 × age_days)
scope_multiplier: team=1.5, project=1.2, global=1.0
```

**Scope multipliers integrated.** Scope multipliers ARE integrated into retrieval. `memory_indexer.py` defines `SCOPE_MULTIPLIERS` (line 747), `apply_scope_multipliers()` (line 769), and calls it during retrieval (line 852, 983). Team-level memories surface higher than global memories at equal similarity, providing appropriate prioritization.

**Retrieval strategy.** `memory_indexer.py` implements a three-stage retrieval pipeline:

1. **Query construction.** Claude Haiku extracts 5–8 key search terms from the raw task description, filtering common words and focusing on domain concepts. Falls back to the first 500 characters of the task on error.
2. **Two-phase scoring.** BM25 via FTS5 provides the primary retrieval signal. When vector embeddings are available (OpenAI `text-embedding-3-small` or Gemini `embedding-001`), scores are blended: `0.7 × vector_score + 0.3 × BM25`. Falls back to BM25-only when embeddings are unavailable.
3. **Post-processing.** Results are weighted by prominence (`importance × recency_decay × (1 + reinforcement_count)`), multiplied by scope level (team=1.5×, project=1.2×, global=1.0×), then reranked for diversity using MMR with Jaccard-based similarity to avoid returning near-duplicate entries.

**Memory context injection.** Retrieved learnings are injected into agent prompts at session start, giving agents access to accumulated knowledge from previous work.

**Helper modules:**
- `memory_entry.py` — structured entry format with YAML frontmatter, type system, importance scoring
- `memory_indexer.py` — FTS5 indexing, hybrid retrieval, scope multipliers integrated, prominence scoring, MMR diversity reranking
- `summarize_session.py` — session summarization across extraction scopes
- `track_reinforcement.py` — reinforcement signal tracking (increments count for retrieved entries)
- `compact_memory.py` — deduplication (by ID), similarity merging (Jaccard > 0.8), retired entry removal

**Reinforcement integration.** Reinforcement tracking is wired in. `extract_learnings()` calls `reinforce_entries()` at session end (per issue #91, resolved). When a retrieved learning entry was used by an agent, its `reinforcement_count` is incremented, raising its future prominence.

---

## What Does Not Yet Exist

**Full learning type differentiation.** The conceptual design defines three retrieval categories: institutional (always loaded), task-based (fuzzy-retrieved), and proxy (five subtypes). The infrastructure exists (typed entries, separate `institutional.md` and `tasks/` directories). The retrieval approach is now specified: caller-driven type routing adapted from AdaMem (Yan et al., 2026), where `retrieve()` accepts a `learning_type` parameter and per-type token budgets. Implementation pending — see [#197](https://github.com/dlewissandy/teaparty/issues/197). **Severity:** 40% problem until implemented.

**Scoped retrieval with type-aware budget allocation.** Scope multipliers are integrated (team=1.5x, project=1.2x, global=1.0x). Type-aware budget allocation is specified: each learning type (institutional, task, proxy) gets a dedicated token budget, and retrieval queries are dispatched to the appropriate type store. The approach uses caller-driven routing rather than query classification — the caller (engine.py, proxy_agent.py) already knows what type of memory it needs. Implementation pending — see [#197](https://github.com/dlewissandy/teaparty/issues/197). **Severity:** 20% problem until implemented.

**In-flight and prospective extraction.** The conceptual design defines four learning moments: prospective (before execution), in-flight (at milestones), corrective (at mismatch), and retrospective (after completion). Only retrospective (post-session) is wired into the orchestrator lifecycle. In-flight extraction would require pausing at milestones to reflect; prospective extraction would require reflection before execution. **Severity:** This is a 60% problem for full vision realization but 0% for current extraction — these are design targets for future work.

**Proxy learning integration.** The approval gate stores interaction chunks in `proxy_memory.db` (ACT-R episodic memory) and EMA history in `.proxy-confidence-*.json`. These are not yet integrated with the broader learning system. The specified approach: post-session persona distillation extracts stable preferences from ACT-R chunks and writes them as Claude Code memory files (`~/.claude/projects/<project>/memory/`), where they are automatically loaded into all sessions including proxy invocations. This provides bidirectional feedback: the proxy's discoveries inform all agents, and human corrections to the memory files feed back into the proxy's model. **Severity:** 80% problem until implemented.

---

## Procedural Learning: System I / System II

The planning phase operates as a dual-process system. System I (fast path) checks whether a stored skill matches the current task. If it matches, the skill template becomes the plan directly — the planning agent never runs. System II (slow path) invokes the planning agent to produce a plan from scratch. The human or proxy reviews the result at PLAN_ASSERT regardless of which path produced it.

This is how collective procedural knowledge accumulates: agents solve problems (System II), successful solutions crystallize into reusable skills, and future similar tasks get the benefit of prior work without repeating the planning effort (System I). The mechanism has three stages.

### Stage 1: Skill lookup (implemented)

`skill_lookup.py` matches the current task description against stored skills in the `skills/` directory using threshold-based retrieval. When a match exceeds the threshold, `engine.py` seeds PLAN.md with the skill template at planning phase entry. The planning agent is bypassed.

### Stage 2: Skill crystallization (not yet wired)

`crystallize_skills()` exists in `procedural_learning.py` but is never called from the runtime. After successful sessions, approved plans are archived as skill candidates in `skill-candidates/`. When three or more candidates for the same category of work accumulate, crystallization generalizes them into a parameterized skill template — extracting the common structure and marking variable elements. The generalization is performed by an LLM call that reads the candidate plans and produces a skill with fixed structure and variable parameters.

The pipeline is: archive candidates (works) → crystallize into skills (**dead code**) → look up skills for future tasks (works but has nothing to find). Wiring crystallization into the post-session pipeline (`extract_learnings()`) closes the loop.

### Stage 3: Skill refinement

Once a skill is in use, it should improve from experience. Three categories of signal feed back into the skill after each session that used it.

**Gate feedback.** Every time a skill-as-plan passes through PLAN_ASSERT or WORK_ASSERT, the gate outcome is a signal about the skill's quality. The gate infrastructure already records approve/correct/reject counts, text differentials on corrections, and EMA approval rates. But approval with comments is also signal — the human or proxy may approve the plan while noting concerns, missing considerations, or areas that could be stronger. These comments reveal where the skill fell short of expectations even when the output was acceptable. A correction ("add a rollback step") is explicit ground truth. A comment ("this doesn't address the migration rollback case") is softer but equally valuable for refinement.

**Backtracks.** Not all backtracks mean the same thing. The CfA state machine distinguishes backtrack targets, and each tells you something different about what failed:

- **Execution → Planning** (e.g., WORK_ASSERT → revise-plan): execution uncovered an unanticipated corner case in the plan. The plan's structure was wrong for the actual work — a missing step, an incorrect assumption about dependencies, a gap the skill template should have covered. This is direct refinement signal for the skill.
- **Execution → Intent** or **Planning → Intent**: the intent was underspecified or misspecified. The skill may be fine — the problem was upstream. This is not a signal about the skill's quality; it's a signal about intent capture.
- **Task-level retries** within execution: a subtask failed and was retried. This may be skill-relevant (the skill's decomposition was wrong) or environmental (a flaky tool, a transient error). The distinction matters for refinement.

The key insight: execution-to-planning backtracks are the strongest skill refinement signal. The corrected plan produced by System II fallback reveals exactly what the skill got wrong and what the fix looks like. Planning-to-intent backtracks are not skill signal — they indicate intent problems.

**Execution friction.** A session that succeeds at the gates but encountered operational problems during execution — tool timeouts, permission denials, bash calls that were blocked, retries on flaky operations, missing file references — has valuable signal about what the skill's instructions failed to anticipate. These friction events are already visible in the agent's conversation stream. The skill should be refined to prevent recurrence: adding explicit file references so agents don't search blindly, providing example commands so agents don't guess at syntax, specifying permission requirements upfront, including fallback instructions for known failure modes.

Skill refinement invokes Claude Code's built-in skill creation capability, which understands the skill format natively. The refinement agent receives the existing skill, the human's comments and corrections from the gate, and the full execution trace from the session. The trace shows what actually happened — where the agent struggled, what it retried, what workarounds it found, what the backtrack revealed. The agent reads this material and considers the full range of improvements:

- **Rewording** — clarifying ambiguous instructions that led to misinterpretation, tightening language where agents went off track, restructuring steps that proved fragile
- **Extracting references** — pulling out file paths, API endpoints, configuration locations, and other concrete pointers that agents had to discover by searching, so future invocations find them immediately
- **Creating examples** — adding worked examples of expected inputs, outputs, or intermediate artifacts where agents guessed at format or structure
- **Scripting tools** — writing shell scripts, helper commands, or tool configurations that automate steps where agents repeatedly encountered friction (permission setup, environment configuration, file scaffolding) This is not a bespoke LLM reflect pass; it uses the same mechanism a human would use to improve a skill after observing it in action.

```
skill learning lifecycle:
    session starts
    task matches skill via System I lookup
    skill template becomes PLAN.md
    execution proceeds under that plan

    during execution:
        record friction events: timeouts, permission denials, tool failures, retries

    at PLAN_ASSERT or WORK_ASSERT:
        gate records outcome (approve / correct / reject)
        capture correction text, approval comments, or rejection reason

    on backtrack:
        if execution → planning: skill refinement signal (corner case in plan)
            archive corrected plan as evidence of what the skill got wrong
        if planning → intent or execution → intent: not skill signal (intent problem)
            do not attribute to skill

    post-session:
        collect signals: gate feedback + execution→planning backtracks + friction events
        if any signals recorded for the skill:
            invoke Claude Code skill refinement with existing skill + signals
            refined skill replaces original in skills/
        crystallize any pending candidates into new skills
```

Skills with persistently low approval rates or high correction counts are surfaced for review rather than silently continuing to produce plans that need fixing.
