# Cognitive Architecture for Learning Agents

A design document for equipping TeaParty agents with memory, reflection, and adaptive learning — grounded in cognitive science research and mapped to the existing system architecture.

---

## 1. Background: What Is a Cognitive Architecture?

A cognitive architecture is a theory of the fixed structures and processes that underlie intelligent behavior. In AI, it's the infrastructure that sits *around* the reasoning engine (here, an LLM) — providing memory, learning, goal management, and self-monitoring capabilities that the raw model lacks.

Classical cognitive architectures (ACT-R, SOAR, CLARION, LIDA) share a common skeleton:

| Component | Purpose | Classical Example |
|-----------|---------|-------------------|
| **Working Memory** | Active context for current reasoning | ACT-R buffers, SOAR working memory |
| **Long-Term Declarative Memory** | Facts and experiences | ACT-R chunks, SOAR semantic memory |
| **Long-Term Procedural Memory** | Skills and action patterns | ACT-R productions, SOAR procedural rules |
| **Episodic Memory** | Autobiographical experiences | SOAR episodic memory, LIDA transient episodic |
| **Perception** | Environment sensing | SOAR input-link, LIDA sensory memory |
| **Action Selection** | Choosing what to do | ACT-R conflict resolution, SOAR operator selection |
| **Learning** | Updating memories from experience | ACT-R utility learning, SOAR chunking |
| **Metacognition** | Monitoring and regulating own cognition | CLARION metacognitive subsystem |

The key insight from decades of cognitive science: **intelligence is not just reasoning — it's the memory systems that feed reasoning, and the learning systems that update memory from experience.**

---

## 2. LLM-Agent Cognitive Architectures (State of the Art)

Recent work has adapted these principles for LLM-based agents. The most influential frameworks:

### 2.1 CoALA — Cognitive Architectures for Language Agents

**Sumers, Yao, Narasimhan & Griffiths (2024)**

The most comprehensive theoretical framework. CoALA maps classical cognitive architecture concepts onto LLM agents:

- **Working memory** = the LLM context window (system prompt + conversation history + retrieved memories)
- **Long-term memory** = external stores (vector DBs, key-value stores, code repositories)
- **Action space** = tool use + text generation
- **Decision procedure** = the prompt + decoding strategy that selects actions
- **Learning** = writing to long-term memory stores after experiences

CoALA's key contribution is the taxonomy: agents differ in *what memory types they use*, *what their action space is*, and *how they learn*. It's not a single architecture but a design space.

### 2.2 Generative Agents (Stanford, Park et al. 2023)

Simulated 25 agents in a sandbox environment with:

- **Memory stream**: timestamped log of all observations and actions
- **Retrieval**: recency × relevance × importance scoring to surface memories
- **Reflection**: periodic synthesis of recent memories into higher-level insights ("I've noticed Klaus often avoids social events")
- **Planning**: daily plans decomposed into hourly actions, revised based on observations

Key finding: reflection was the critical ingredient. Without it, agents repeated patterns and failed to develop. With it, emergent social behaviors arose (party planning, opinion formation, relationship dynamics).

### 2.3 Reflexion (Shinn et al. 2023)

Agents that learn from failure through verbal self-reflection:

1. Agent attempts a task
2. Evaluator scores the attempt
3. Agent reflects on what went wrong (generating natural language feedback)
4. Reflection is stored in memory and prepended to next attempt

No weight updates — learning is entirely through accumulated reflective text in the context window. Achieved near-human performance on HumanEval coding after 2-3 reflection cycles.

### 2.4 Voyager (Wang et al. 2023)

Minecraft agent with a **skill library** — procedural memory implemented as a growing codebase:

- **Curriculum**: automatic task proposal based on current capabilities
- **Skill library**: verified JavaScript functions stored and retrieved by description
- **Iterative refinement**: failed skills are debugged via environment feedback

Key insight: procedural memory as *executable code* is more reliable than natural language instructions.

### 2.5 CLIN — Continually Learning from Interactions (Majumder et al. 2024)

Agents that persistently learn across task episodes:

- After each episode, agent extracts **causal abstractions** ("when X happens, doing Y leads to Z")
- Abstractions stored in a growing memory that persists across episodes
- Memory is retrieved and injected into the prompt for future tasks

CLIN showed that agents *do* improve over time with this approach, and that memories transfer across similar (but not identical) tasks.

### 2.6 MemGPT / Letta (Packer et al. 2023-2024)

Explicit memory management as an OS-like system:

- **Main context** (working memory): limited, actively managed
- **Archival memory**: unlimited long-term storage, searchable
- **Recall memory**: conversation history, paginated
- Agent explicitly calls `archival_memory_insert`, `archival_memory_search`, `conversation_search` tools

Key insight: give agents *tools* for memory management rather than automating it. The agent decides what to remember, what to forget, and when to retrieve.

### 2.7 ExpeL — Experiential Learning (Zhao et al. 2024)

Agents that learn from *contrasting* successes and failures:

- **Phase 1**: Agent attempts training tasks, recording full trajectories (both successes and failures)
- **Phase 2**: Agent *compares* failed and successful trajectories to identify what differed, then extracts cross-task patterns
- Extracted insights are iteratively refined: adding, editing, voting on importance

Key distinction from Reflexion: ExpeL learns from *contrasts* ("this worked, that didn't, and the difference was...") rather than from failures alone. Does NOT require repeated attempts at the same task — insights transfer across tasks.

### 2.8 AutoRefine (2025)

Automatically extracts **dual-form Experience Patterns**:

- **Specialized subagents** for recurring procedural subtasks
- **Skill patterns** (guidelines or code snippets) for static knowledge
- Continuous maintenance: scoring, pruning, and merging patterns to prevent degradation

Results: ALFWorld 98.4%, ScienceWorld 70.4%. On TravelPlanner, automatic extraction exceeds manually designed systems (27.1% vs 12.1%) — showing that learned patterns can outperform hand-crafted ones.

### 2.9 Mem0 (Chhikara et al. 2025)

Production-ready memory architecture with two variants:

- **Basic**: structured extraction + updation pipeline
- **Graph-enhanced (Mem0g)**: directed labeled graph of entities and relationships (nodes = entities, edges = relationships, labels = semantic types)

Results: 26% accuracy boost, 91% lower p95 latency, 90% token savings vs. full-context approaches. Demonstrates that persistent structured memory is practical at production scale.

### 2.10 Other Notable Work

- **FadeMem** (2025): Biologically-inspired decay/forgetting — retains 82.1% of critical facts using only 55% of storage (vs. 78.4% retention at 100% storage without decay). Selective forgetting *improves* retention quality.
- **LLM-ACTR** (Wu et al. 2024-2025): Integrates ACT-R's decision-making into LLMs via adapter layers — classical cognitive principles embedded in modern models.
- **Brain-Inspired MAP** (Nature Communications, 2025): Decomposes planning into brain-inspired modules (conflict monitoring, state prediction, task decomposition). Modular specialized agents outperform monolithic ones.
- **DSPy** (Khattab et al. 2024): Optimizing prompts as programs — a form of automated procedural learning.
- **LaMer** (2025): Meta-RL for LLM agents — cross-episode training with in-context policy adaptation via reflection.

---

## 3. Memory Systems: What Works

### 3.1 Episodic Memory (What Happened)

**What it is**: Timestamped records of specific experiences — "In conversation X, user Y asked about Z, and my approach of W worked well."

**What works in practice**:
- **Memory streams** (Generative Agents): simple chronological logs with retrieval scoring
- **Episode summaries** (CLIN): condensed takeaways after each interaction, not raw logs
- **Indexed trajectories** (ExpeL): full task trajectories stored for replay as demonstrations
- **Retrieval by similarity + recency + importance**: triple-weighted retrieval outperforms any single factor

The **gold standard retrieval formula** (from Generative Agents, validated across multiple systems):

```
score = α·recency(m) + β·relevance(m, query) + γ·importance(m)

recency(m)    = exponential decay from last access time
relevance(m)  = cosine similarity of embedding vectors (memory description vs current context)
importance(m) = LLM-rated significance (1-10 scale, rated at creation time)

All weights = 1.0, scores min-max normalized to [0,1]
```

This is directly descended from ACT-R's activation-based retrieval (combining recency, frequency, and contextual relevance) — validated for 40+ years in cognitive science.

Recent finding: "Episodic Memory is the Missing Piece for Long-Term LLM Agents" (2025) argues that most agent systems underweight episodic memory relative to semantic/procedural. Agents that can recall specific past experiences perform better than those relying only on general knowledge.

**For TeaParty**: Agents already generate messages stored in the `messages` table. The gap is *distilling* these into retrievable episodic memories and *scoring* them for retrieval.

### 3.2 Semantic Memory (What I Know)

**What it is**: General knowledge and facts — "User prefers concise responses", "The codebase uses FastAPI with SQLModel", "Markdown headers should use ATX style."

**What works in practice**:
- **Self-extracted knowledge** (Reflexion, CLIN): agent distills knowledge from experience
- **Key-value stores**: simple and effective for factual knowledge
- **Vector stores**: better for fuzzy/semantic retrieval but add infrastructure complexity
- **Hierarchical summaries**: knowledge at different levels of abstraction

**For TeaParty**: The `AgentMemory` model already supports this with `memory_type` categories. The `Agent.learned_preferences` JSON field is a lightweight semantic memory.

### 3.3 Procedural Memory (How to Do Things)

**What it is**: Skills, strategies, workflows — "When asked to review code, first read the PR diff, then check for security issues, then comment on style."

**What works in practice**:
- **Skill libraries** (Voyager): executable code/prompts indexed by capability description
- **Workflow templates**: structured plans that can be adapted (TeaParty already has workflows)
- **Prompt libraries**: curated prompts for specific tasks, refined through use
- **Natural language procedures** are fragile; structured/executable forms are more reliable

**For TeaParty**: Workflows already serve as a form of procedural memory. The gap is *agent-authored* procedures that emerge from experience rather than being pre-defined.

### 3.4 Working Memory (Active Context)

**What it is**: The information actively being reasoned about — the LLM's context window.

**What works in practice**:
- **Selective injection**: retrieve only relevant memories into the prompt
- **Summarization**: compress old context rather than dropping it
- **MemGPT's approach**: agent explicitly manages what's in working memory via tools

**For TeaParty**: Currently managed by `prompt_builder.py` which constructs the system prompt and message history. Claude's persistent sessions (`claude_session_id`) also serve as working memory across turns.

---

## 4. Learning Mechanisms

### 4.1 Learning Mechanisms Compared

| Mechanism | How It Works | Cost | Reliability | Transfer |
|-----------|-------------|------|-------------|----------|
| **Self-reflection** (Reflexion) | Agent reviews output, extracts verbal feedback | 1 LLM call/episode | Moderate — can hallucinate | Low — trial-scoped |
| **Causal abstraction** (CLIN) | Extract situation→action→outcome rules | 1 LLM call/episode | High — structured | High — cross-task |
| **Contrastive learning** (ExpeL) | Compare successes vs failures, extract insights | 1 LLM call/batch | High — grounded in evidence | Medium — cross-task |
| **Skill libraries** (Voyager) | Store verified executable procedures | 1 LLM call + verification | High — tested before storage | Medium — domain-bound |
| **Outcome feedback** | Environment/user signals success or failure | Near-free | High signal but sparse | N/A |
| **Preference learning** | Track user corrections and stated preferences | Near-free | High for explicit signals | N/A |
| **Peer observation** | Learn from teammates' successes | Free (read shared memory) | Depends on trust/quality | Low |

CLIN's causal abstractions outperform Reflexion's narrative reflections by 23 absolute points on ScienceWorld. The key difference: structured "when X, doing Y leads to Z" rules generalize better than "I should have done X instead."

### 4.2 What Makes Learning Work in LLM Agents

Research consensus points to several critical factors:

1. **Reflection must be grounded**: Abstract reflection ("I should try harder") is useless. Effective reflection cites specific actions and outcomes ("When I used `grep` instead of `find`, I found the file 3x faster because..."). CLIN's causal format enforces this.

2. **Forgetting is essential**: FadeMem (2025) demonstrates that selective forgetting *improves* quality — 82.1% retention of critical facts at 55% storage, vs 78.4% at 100% storage. Agents that forget strategically remember important things better.

3. **Learning should be opt-in, not forced**: Per the TeaParty philosophy of "agents are agents, not scripted" — learning loops should be *available* to agents as tools, not imposed as mandatory post-processing. Soar's impasse-driven model is the ideal: learn only when encountering a gap.

4. **Transfer is hard**: Memories from one context often don't apply cleanly in another. Domain-specific memories are more useful than general ones. CLIN's causal rules transfer better than narrative reflections.

5. **Reflection without persistence is ephemeral**: Self-reflection improves performance only if reflections are *persisted, indexed, and retrievable*. A reflection bank must be searchable and context-aware, not just a list.

---

## 5. Social Cognition for Multi-Agent Teams

### 5.1 Theory of Mind

Agents in teams benefit from modeling other agents' knowledge, beliefs, and capabilities:

- **Capability maps**: "Agent X is good at code review; Agent Y is good at research"
- **Shared mental models**: Common understanding of the task, the plan, and each other's roles
- **Attribution**: Understanding *why* a teammate did something, not just *what* they did

Research findings: LLMs show surprising Theory of Mind abilities in zero-shot settings (MetaMind achieves 81.0% accuracy on ToM tasks with GPT-4, up from 74.8% baseline). But maintaining consistent mental models of other agents over extended interactions remains an open challenge.

From CSCW research (25+ years): teams with better shared mental models coordinate more effectively with *less explicit communication*. This translates to agents maintaining models of other agents' capabilities, current state, and goals — enabling implicit coordination without constant messaging.

### 5.2 Collective Memory

Multi-agent teams can share knowledge in several ways:

| Pattern | Description | Trade-off |
|---------|-------------|-----------|
| **Shared knowledge base** | All agents read/write to the same memory store | Rich but noisy; needs curation |
| **Broadcast learning** | Agent shares a lesson with all teammates | Simple but can overwhelm |
| **Selective sharing** | Agent shares only with relevant teammates | Targeted but requires routing intelligence |
| **Stigmergy** | Agents leave traces in shared artifacts (files, messages) | Natural in TeaParty; implicit rather than explicit |

For TeaParty, **stigmergy** is already the dominant pattern — agents leave their work in shared files and conversations. The opportunity is to layer *explicit* knowledge sharing on top.

---

## 6. Current TeaParty Architecture: Cognitive Capabilities Audit

### 6.1 What Exists Today

| Capability | Current State | Location |
|------------|--------------|----------|
| **Working memory** | Context window via `prompt_builder`; persistent Claude sessions | `prompt_builder.py`, `Conversation.claude_session_id` |
| **Episodic memory** | Raw message history in `messages` table | `models.py:Message` |
| **Semantic memory** | `Agent.learning_state`, `Agent.learned_preferences` (JSON); `AgentMemory` table | `models.py:Agent`, `models.py:AgentMemory` |
| **Procedural memory** | Workflow system; agent tool definitions | `docs/workflows.md`, `Agent.tool_names` |
| **Learning events** | `AgentLearningEvent` table (schema exists) | `models.py:AgentLearningEvent` |
| **Perception** | Message history, file contents via materialization, team events | `agent_runtime.py`, `file_materializer.py` |
| **Action selection** | LLM decides; `@mention` routing; team lead delegation | `agent_runtime.py`, `team_bridge.py` |
| **Metacognition** | None | — |
| **Social cognition** | Team structure via `is_lead`; agent role descriptions | `Agent.is_lead`, `Agent.role` |

### 6.2 Key Gaps

1. **No memory retrieval pipeline**: `AgentMemory` exists but nothing reads from it during prompt construction. The injection point is `_build_prompt_body()` in `agent_definition.py:96-155` — between the conversation context block and the guidelines block.
2. **No reflection loop**: `AgentLearningEvent` exists but nothing triggers learning or writes to it. The hook point is `agent_runtime.py:473-483` — immediately after `session.add(agent_message)` / `session.flush()`.
3. **No memory decay/consolidation**: Memories accumulate without pruning
4. **No cross-agent knowledge sharing**: Each agent's memory is siloed. `AgentMemory` lacks a `workgroup_id` column for cross-conversation retrieval.
5. **No capability modeling**: Agents don't know what their teammates are good at
6. **No metacognition**: Agents can't monitor their own uncertainty or ask for help strategically
7. **No cross-conversation awareness**: Agents perceive only their current conversation (40-message window via `build_user_message`). No visibility into other conversations, past interactions, or workgroup-level patterns.

---

## 7. Proposed Cognitive Architecture

### 7.1 Design Principles

1. **Agents are agents**: Memory and learning are *tools available to the agent*, not imposed pipelines. The agent chooses when to reflect, what to remember, and when to retrieve.
2. **Minimal overhead**: Don't add latency or cost to every interaction. Learning happens *asynchronously* after interactions, not blocking the response path.
3. **Build on what exists**: Use the `AgentMemory`, `AgentLearningEvent`, and `learning_state` schemas that already exist.
4. **Start with episodic + semantic**: Procedural memory (skill libraries) and metacognition are later phases.

### 7.2 Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Agent Turn                            │
│                                                         │
│  ┌───────────┐    ┌─────────────┐    ┌──────────────┐   │
│  │ Perception │───▸│   Working   │───▸│    Action     │  │
│  │ (context   │    │   Memory    │    │  (LLM call   │  │
│  │  assembly) │    │ (prompt +   │    │   + tools)   │  │
│  │            │    │  memories)  │    │              │  │
│  └───────────┘    └─────────────┘    └──────┬───────┘  │
│        ▲                                     │          │
│        │           ┌─────────────┐           │          │
│        └───────────│  Long-Term  │◂──────────┘          │
│                    │   Memory    │                       │
│                    │             │     ┌──────────────┐  │
│                    │ • episodic  │◂────│  Reflection  │  │
│                    │ • semantic  │     │  (async,     │  │
│                    │ • shared    │     │   post-turn) │  │
│                    └─────────────┘     └──────────────┘  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 7.3 Component Details

#### A. Memory Store (Long-Term Memory)

Uses the existing `AgentMemory` table with an extended type system:

| `memory_type` | Description | Example |
|----------------|-------------|---------|
| `episode` | What happened in a specific interaction | "User asked me to refactor auth module; I used grep to find all auth references first" |
| `insight` | A generalized lesson from one or more episodes | "When refactoring, always map dependencies before changing code" |
| `preference` | A learned user or domain preference | "This workgroup prefers Python type hints on all functions" |
| `correction` | Something I got wrong and the right answer | "I assumed the config was in .env but it's in settings.toml" |
| `peer_skill` | Observed capability of a teammate | "Agent 'researcher' consistently finds relevant papers quickly" |

Schema extension to `AgentMemory`:

```python
# New fields (added via migration):
workgroup_id: str      # scope memories to workgroup (for shared access)
access_level: str      # "private" | "workgroup" — controls sharing
relevance_count: int   # how often this memory has been retrieved and used
last_accessed_at: datetime | None  # for decay calculation
embedding: bytes | None  # optional embedding for vector retrieval
```

#### B. Memory Retrieval (Perception Enhancement)

Before each agent turn, relevant memories are retrieved and injected into the system prompt. Retrieval is scored by:

```
score = α·recency(m) + β·relevance(m, query) + γ·importance(m)

where:
  recency(m)    = exponential decay from m.created_at
  relevance(m)  = keyword/embedding similarity to current conversation context
  importance(m) = f(m.confidence, m.relevance_count)
  α, β, γ       = tunable weights (default: 0.2, 0.5, 0.3)
```

Implementation location: **`prompt_builder.py`** — add a `_retrieve_memories()` step that queries `AgentMemory`, scores results, and appends a `## Relevant Memories` section to the system prompt.

Budget: retrieve at most **5-8 memories** per turn to avoid context bloat.

#### C. Reflection Engine (Learning)

A lightweight, asynchronous process that runs *after* an agent completes a turn:

1. **Trigger**: Agent's response is stored in the database
2. **Process**: A cheap LLM call reviews the agent's last interaction and extracts memories
3. **Store**: New memories written to `AgentMemory`; `AgentLearningEvent` records the learning event

The reflection prompt:

```
Review this interaction and extract any useful memories:
- What worked well? What didn't?
- Did you learn anything about the user's preferences?
- Did you discover any facts about the codebase or domain?
- Did you observe anything about your teammates' capabilities?

Return memories as structured JSON.
```

Key design choices:
- **Asynchronous**: reflection runs in a background thread, never blocking the response
- **Cheap model**: use `resolve_model(purpose="cheap")` for reflection calls
- **Opt-in**: reflection is triggered only when the interaction seems significant (not for simple acknowledgments)
- **Rate-limited**: at most one reflection per agent per conversation per 10 minutes

Implementation location: **New `teaparty_app/services/reflection.py`** called from `agent_runtime.py` after storing the agent's message.

#### D. Memory Decay and Consolidation

Memories that are never retrieved decay in relevance:

- `relevance_count` tracks how often a memory is retrieved and used
- `last_accessed_at` tracks recency of use
- **Consolidation**: periodically (daily or on-demand), merge similar memories into higher-level insights
- **Pruning**: memories below a confidence × relevance threshold are soft-deleted

This can be a background task triggered by the existing `process_triggered_todos` tick system.

#### E. Shared Memory (Social Cognition)

Agents in the same workgroup can access shared memories:

- Memories with `access_level = "workgroup"` are visible to all agents in that workgroup
- **Stigmergic sharing**: agents naturally share knowledge by writing to shared files (already works)
- **Explicit sharing**: a `share_memory` tool that copies a private memory to workgroup scope
- **Capability modeling**: `peer_skill` memories build an implicit capability map over time

#### F. Memory Management Tools

Following the MemGPT pattern, agents get tools for explicit memory management:

| Tool | Description |
|------|-------------|
| `remember(content, memory_type)` | Store a new memory |
| `recall(query, limit)` | Search memories by natural language query |
| `forget(memory_id)` | Mark a memory as no longer relevant |
| `share(memory_id)` | Share a private memory with the workgroup |

These are *client-side tools* — they execute on the TeaParty server, not in the LLM. They'd be added to the agent's tool definitions in `build_agent_json()`.

**Architectural challenge**: The current `claude -p` invocation is fire-and-forget (stdin→stdout). Intercepting tool calls mid-stream for `remember`/`recall` would require switching to bidirectional stream-json I/O. `TeamSession` already partially supports this for multi-agent mode, but single-agent mode does not.

**Simpler alternative for Phase 1**: Inject memories into the prompt at construction time (no mid-stream interception needed). Memory *writing* can be done via async post-response reflection. This avoids the bidirectional I/O challenge entirely. Agent memory tools requiring mid-stream interception can be deferred to a later phase when the architecture supports it.

---

## 8. API Implications

### 8.1 New Endpoints

```
GET  /api/agents/{agent_id}/memories
     Query params: type, query, limit, access_level
     Returns: list of AgentMemory objects, scored and ranked

POST /api/agents/{agent_id}/memories
     Body: { content, memory_type, confidence, access_level }
     Creates a new memory

DELETE /api/agents/{agent_id}/memories/{memory_id}
     Soft-delete a memory

GET  /api/workgroups/{workgroup_id}/shared-memories
     Returns workgroup-scoped memories across all agents

POST /api/agents/{agent_id}/reflect
     Trigger manual reflection on recent interactions
     (Primarily for debugging/admin use)

GET  /api/agents/{agent_id}/learning-events
     Returns learning event history
```

### 8.2 Modified Endpoints

- **`POST /api/conversations/{id}/messages`**: After storing the agent response, optionally trigger async reflection
- **Agent definition builder** (`build_agent_json`): Include retrieved memories in the system prompt and memory tools in the tool list

### 8.3 Database Schema Changes

```sql
-- Extend agent_memories table
ALTER TABLE agent_memories ADD COLUMN workgroup_id TEXT REFERENCES workgroups(id);
ALTER TABLE agent_memories ADD COLUMN access_level TEXT DEFAULT 'private';
ALTER TABLE agent_memories ADD COLUMN relevance_count INTEGER DEFAULT 0;
ALTER TABLE agent_memories ADD COLUMN last_accessed_at TIMESTAMP;
ALTER TABLE agent_memories ADD COLUMN is_archived BOOLEAN DEFAULT FALSE;

-- Index for retrieval
CREATE INDEX idx_agent_memories_retrieval
  ON agent_memories(agent_id, memory_type, is_archived)
  WHERE is_archived = FALSE;

CREATE INDEX idx_agent_memories_shared
  ON agent_memories(workgroup_id, access_level, is_archived)
  WHERE access_level = 'workgroup' AND is_archived = FALSE;
```

### 8.4 Config Changes

```python
# New settings in config.py
reflection_enabled: bool = True          # Global toggle
reflection_model: str = ""               # Override model for reflection (defaults to cheap)
memory_retrieval_limit: int = 8          # Max memories per prompt
memory_decay_days: int = 30              # Days before unused memories decay
memory_consolidation_enabled: bool = False  # Phase 2
```

---

## 9. Implementation Phases

### Phase 1: Memory Retrieval (Low Risk, High Value)

Wire up the existing `AgentMemory` table:

1. Add `_retrieve_memories()` to `prompt_builder.py` — query `agent_memories` for the current agent, score by recency + relevance + importance
2. Inject retrieved memories into the system prompt via `_build_prompt_body()` in `agent_definition.py:96-155` — new section between conversation context and guidelines
3. Add `GET /api/agents/{id}/memories` endpoint for admin inspection
4. Populate memories manually or via admin API to validate the retrieval pipeline before adding automatic learning

**Files touched**: `agent_definition.py`, `prompt_builder.py`, new router. No schema migration needed — the `agent_memories` table and `_ensure_agent_memory_table()` migration already exist in `db.py`.

**Estimated scope**: ~200 lines across 3 files.

### Phase 2: Reflection Engine (Medium Risk, High Value)

Add asynchronous post-turn reflection:

1. Create `teaparty_app/services/reflection.py` — uses `llm_client.create_message()` with `resolve_model(purpose="cheap")` for reflection calls
2. Hook into `agent_runtime.py:473-483` after `session.add(agent_message)` / `session.flush()` — fire reflection in background thread, similar to `_process_auto_responses_in_background()` pattern at `agent_runtime.py:583-602`
3. Add schema migration for new `AgentMemory` columns (`workgroup_id`, `access_level`, `relevance_count`, `last_accessed_at`, `is_archived`)
4. Add `POST /api/agents/{id}/reflect` admin endpoint for debugging

**Files touched**: new `reflection.py`, `agent_runtime.py`, `db.py` (migration), new router.

**Estimated scope**: ~300 lines, 1 new file, 1 migration.

### Phase 3: Shared Memory and Social Cognition (Medium Risk, Medium Value)

Enable cross-agent knowledge sharing:

1. Add `workgroup_id` and `access_level` to memory retrieval
2. Add `share` tool to agent definitions
3. Add `peer_skill` memory type with automatic extraction during team sessions
4. Add `GET /api/workgroups/{id}/shared-memories` endpoint

**Estimated scope**: ~200 lines across 4 files, extends Phase 2 migration.

### Phase 4: Memory Consolidation and Decay (Low Risk, Medium Value)

Prevent memory bloat:

1. Add consolidation task to the existing tick system (`process_triggered_todos`)
2. Implement decay scoring in retrieval
3. Add archival/pruning logic
4. Add admin UI for viewing and managing agent memories

**Estimated scope**: ~250 lines, background task integration.

### Phase 5: Procedural Memory / Skill Libraries (High Risk, High Value)

Agent-authored procedures and skills:

1. Agents can define reusable "skills" (structured prompts/plans)
2. Skills stored in a new table, indexed by capability description
3. Retrieved during prompt construction when relevant
4. Builds on workflow system but is agent-authored rather than admin-defined

This is the most architecturally complex phase and should wait until Phases 1-3 are validated.

---

## 10. Design Tensions and Trade-offs

### Autonomy vs. Control

The research strongly supports giving agents autonomy over their memory (MemGPT pattern). But unbounded memory writing could lead to:
- **Cost**: Every memory write is a future retrieval candidate, increasing prompt size
- **Quality**: Agents may store low-quality or redundant memories
- **Privacy**: Agents might memorize sensitive information

**Mitigation**: Rate limits on memory creation, confidence thresholds, and admin visibility.

### Memory Persistence vs. Forgetting

- Too much persistence → context pollution, outdated information
- Too little → agents never develop, repeat mistakes

Forgetting strategies from the literature:

| Strategy | Mechanism | Example System |
|----------|-----------|---------------|
| **Time-based decay** | Activation decreases with time | ACT-R, FadeMem |
| **Access-based decay** | Unused memories fade | Soar, Generative Agents |
| **Importance threshold** | Only memories above score retained | Generative Agents |
| **Consolidation** | Specific memories → general knowledge | Generative Agents reflection |
| **Capacity-based pruning** | Lowest-activation items removed when limit hit | FadeMem |

FadeMem results: With biologically-inspired decay, 82.1% retention of critical facts at 55% storage. Without decay: 78.4% at 100% storage. Selective forgetting actually *improves* what you remember.

**Mitigation**: Combine time-based decay with importance scoring. Memories fade naturally unless they're important or frequently accessed. Consolidation preserves the essence while allowing specifics to fade — mirroring the human trajectory from vivid episodes to general knowledge.

### Individual vs. Collective Learning

- Individual memory is private and high-signal
- Shared memory enables team coordination but introduces noise

**Mitigation**: Default to private; sharing is an explicit agent action. Workgroup admins can view all memories.

### Cost of Reflection

Each reflection call costs ~500-1000 tokens (using a cheap model). For a workgroup with 4 agents doing 20 interactions/day, that's ~80 extra cheap-model calls/day — negligible cost.

But reflection *quality* matters: bad reflections pollute memory. The cheap model may produce lower-quality insights than the main model.

**Mitigation**: Start with reflection disabled by default. Enable per-workgroup. Monitor memory quality.

### Latency

Memory retrieval adds a database query + scoring to each agent turn. This should be <50ms for typical memory sizes (<1000 memories per agent).

Reflection is fully async and adds zero latency to the user-facing response.

---

## 11. Research References

### Classical Architectures
- Anderson. "An Integrated Theory of the Mind" (ACT-R), *Psychological Review*, 2004. — Activation-based retrieval, production compilation.
- Laird. *The Soar Cognitive Architecture*, MIT Press, 2012. — Impasse-driven learning, chunking, three-store memory.
- Sun. "The CLARION Cognitive Architecture", 2016. — Dual-process implicit/explicit learning, metacognitive subsystem.
- Franklin et al. "LIDA: A Systems-level Architecture for Cognition, Emotion, and Learning", IEEE, 2014. — Global workspace, attention gating.
- Baars. *A Cognitive Theory of Consciousness* (Global Workspace Theory), Cambridge University Press, 1988.

### Modern LLM-Agent Architectures
- Sumers, Yao, Narasimhan & Griffiths. ["Cognitive Architectures for Language Agents"](https://arxiv.org/abs/2309.02427) (CoALA), TMLR 2024. — The unifying theoretical framework.
- Park et al. ["Generative Agents: Interactive Simulacra of Human Behavior"](https://arxiv.org/abs/2304.03442), UIST 2023. — Memory streams, three-factor retrieval, reflection.
- Shinn et al. ["Reflexion: Language Agents with Verbal Reinforcement Learning"](https://arxiv.org/abs/2303.11366), NeurIPS 2023. — Self-reflection for learning.
- Wang et al. ["Voyager: An Open-Ended Embodied Agent with Large Language Models"](https://arxiv.org/abs/2305.16291), 2023. — Skill libraries, auto-curriculum.
- Majumder et al. ["CLIN: A Continually Learning Language Agent"](https://arxiv.org/abs/2310.10134), 2024. — Causal abstraction learning, cross-episode persistence.
- Packer et al. ["MemGPT: Towards LLMs as Operating Systems"](https://arxiv.org/abs/2310.08560), 2023. — Agent-managed memory hierarchy.
- Zhao et al. ["ExpeL: LLM Agents Are Experiential Learners"](https://arxiv.org/abs/2308.10144), AAAI 2024. — Contrastive learning from successes and failures.
- ["AutoRefine"](https://arxiv.org/html/2601.22758v1), 2025. — Dual-form experience patterns, automatic extraction outperforming manual design.
- Wu et al. ["LLM-ACTR"](https://arxiv.org/abs/2408.09176), 2024-2025. — ACT-R decision-making embedded in LLMs.
- ["Brain-Inspired Modular Agentic Planner"](https://www.nature.com/articles/s41467-025-63804-5), Nature Communications, 2025.

### Memory Systems
- Chhikara et al. ["Mem0"](https://arxiv.org/abs/2504.19413), 2025. — Production-ready structured memory with graph variant.
- ["FadeMem"](https://www.co-r-e.com/method/agent-memory-forgetting), 2025. — Biologically-inspired forgetting, selective decay improves retention.
- ["Episodic Memory is the Missing Piece for Long-Term LLM Agents"](https://arxiv.org/abs/2502.06975), 2025.
- ["ACT-R-inspired Memory for LLM Agents"](https://dl.acm.org/doi/10.1145/3765766.3765803), 2024-2025.

### Social Cognition
- ["Theory of Mind for Multi-Agent Collaboration via LLMs"](https://arxiv.org/abs/2310.10701), 2024.
- MetaMind (Stanford, 2024). — Three-agent cognitive-social inference system.
- Gross. "Supporting Effortless Coordination", *CSCW Journal*, 2013. — 25 years of awareness research.

### Surveys and Meta-Analyses
- [Agent Memory Paper List](https://github.com/Shichun-Liu/Agent-Memory-Paper-List) — Curated bibliography.
- "A Survey on the Memory Mechanism of Large Language Model-based Agents", ACM TOIS, 2025.
- Khattab et al. "DSPy: Compiling Declarative Language Model Calls into Self-Improving Pipelines", 2024.
- Wu et al. "AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation", 2024.

---

## 12. Summary

TeaParty already has the *schema* for cognitive architecture — `AgentMemory`, `AgentLearningEvent`, `learning_state`, `learned_preferences`. What's missing is the *wiring*: retrieval during prompt construction, reflection after interactions, and agent tools for explicit memory management.

The proposed architecture follows three principles from the research:

1. **Memory retrieval matters more than memory storage** — the scoring and injection pipeline is the highest-value work
2. **Reflection should be grounded and optional** — agents reflect on specific interactions, not abstractly, and only when it's useful
3. **Agents manage their own memory** — following MemGPT, agents get tools for remember/recall/forget rather than having learning imposed on them

Phase 1 (memory retrieval) can be implemented with ~200 lines and zero schema changes, using the tables that already exist. This is the recommended starting point.
