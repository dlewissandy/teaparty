# Cognitive Architecture for Learning Agents

> *Scope narrowed 2026-04-18: Phase 1 (proxy ACT-R memory) is implemented — see the [human-proxy ACT-R docs](../systems/human-proxy/act-r/overview.md). This proposal covers only Phases 2–7: general agent memory, reflection engine, signal detection, multi-agent shared memory.*

This document proposes extending memory and learning capabilities to **all** TeaParty agents (intent, uber, team leads, subteam agents), building on the ACT-R proxy memory system that is already implemented for the human proxy. The goal is agents that learn, remember, and adapt over time -- grounded in cognitive science research and mapped to the existing system.

---

## 1. Research Foundations

A cognitive architecture is the infrastructure that sits *around* the reasoning engine (here, an LLM) -- providing memory, learning, goal management, and self-monitoring capabilities that the raw model lacks. Classical systems (ACT-R, Soar, CLARION, LIDA) share a common skeleton of working memory, declarative/episodic/procedural long-term memory, learning, and metacognition. Key insight from decades of cognitive science: **intelligence is not just reasoning -- it's the memory systems that feed reasoning, and the learning systems that update memory from experience.**

### 1.1 CoALA: the unifying framework

**CoALA** (Sumers, Yao, Narasimhan & Griffiths, 2024) maps classical cognitive architecture concepts onto LLM agents:

| CoALA Component | Classical Analog | LLM Agent Implementation |
|----------------|-----------------|-------------------------|
| Working Memory | ACT-R buffers, Soar WM | Context window contents |
| Episodic Memory | Soar episodic store | Conversation logs, event records |
| Semantic Memory | ACT-R declarative, Soar semantic | Knowledge base, embeddings |
| Procedural Memory | ACT-R productions, Soar rules | Prompt templates, tool definitions, learned skills |
| Decision Cycle | Soar propose-select-apply | Perceive → plan → act → observe loop |

### 1.2 Systems relevant to Phases 2–7

- **Generative Agents** (Park et al. 2023): memory streams with recency × relevance × importance retrieval; periodic *reflection* synthesizes recent memories into higher-level insights. Reflection was the critical ingredient.
- **Reflexion** (Shinn et al. 2023): verbal self-reflection, stored in memory and prepended to the next attempt. Near-human HumanEval after 2-3 cycles.
- **CLIN** (Majumder et al. 2024): extracts **causal abstractions** ("when X happens, doing Y leads to Z") that persist and transfer across similar tasks. Outperforms narrative reflection by ~23 points on ScienceWorld.
- **Voyager** (Wang et al. 2023): skill library as a growing codebase of verified procedures, retrieved by description. Procedural memory as executable code is more reliable than natural language.
- **MemGPT / Letta** (Packer et al. 2023-2024): give agents *tools* for memory management (`archival_memory_insert`, `archival_memory_search`) rather than automating it.
- **ExpeL** (Zhao et al. 2024): learns from *contrasting* successes and failures; insights transfer across tasks without repeated attempts.
- **AutoRefine** (2025): dual-form experience patterns with continuous scoring, pruning, and merging. Automatic extraction can outperform hand-crafted systems (27.1% vs 12.1% on TravelPlanner).
- **Mem0 / Mem0g** (2025): production structured-memory with graph variant. 26% accuracy boost, 91% lower p95 latency vs full-context.
- **FadeMem** (2025): biologically-inspired forgetting retains 82.1% of critical facts at 55% storage -- selective forgetting *improves* retention quality.

### 1.3 Key takeaways for TeaParty

1. **Memory is not monolithic.** Episodic, semantic, procedural, and working memory serve different purposes.
2. **Learning signals are diverse.** Explicit feedback, implicit success/failure, self-reflection, and inter-agent observation all contribute.
3. **Retrieval matters as much as storage.** Recency-importance-relevance weighting surfaces the right memory at the right time.
4. **Multi-agent memory needs access control.** Shared workgroup knowledge vs. private agent insights.
5. **The LLM context window *is* working memory.** What you put in the prompt determines what the agent can think about.

---

## 2. Memory Systems to Extend

Phase 1 gave the proxy activation-based memory. The remaining phases extend memory to all other agents across three additional stores.

### 2.1 Episodic Memory (What Happened)

Timestamped records of specific experiences -- "In conversation X, user Y asked about Z, and approach W worked well."

**What works in practice**:
- **Memory streams** (Generative Agents): simple chronological logs with retrieval scoring
- **Episode summaries** (CLIN): condensed takeaways, not raw logs
- **Indexed trajectories** (ExpeL): full task trajectories stored for replay as demonstrations

The **gold standard retrieval formula** (from Generative Agents, validated across multiple systems):

```
score = α·recency(m) + β·relevance(m, query) + γ·importance(m)

recency(m)    = exponential decay from last access time
relevance(m)  = cosine similarity of embedding vectors (memory description vs current context)
importance(m) = LLM-rated significance (1-10 scale, rated at creation time)
```

This is directly descended from ACT-R's activation-based retrieval -- the same foundation the proxy already uses, now applied to all agents.

### 2.2 Semantic Memory (What I Know)

General knowledge -- "User prefers concise responses", "This codebase uses FastAPI with SQLModel", "Markdown headers should use ATX style."

**What works in practice**:
- Self-extracted knowledge (Reflexion, CLIN)
- Key-value stores for factual knowledge
- Vector stores for fuzzy/semantic retrieval
- Hierarchical summaries at different levels of abstraction

### 2.3 Procedural Memory (How to Do Things)

Skills, strategies, workflows -- "When asked to review code, first read the PR diff, then check for security issues, then comment on style."

**What works in practice**:
- **Skill libraries** (Voyager): executable code/prompts indexed by capability description
- **Workflow templates**: structured plans that can be adapted (TeaParty already has workflows)
- Natural-language procedures are fragile; structured/executable forms are more reliable.

### 2.4 Working Memory (Active Context)

The information actively being reasoned about -- the LLM's context window.

**What works in practice**:
- Selective injection: retrieve only relevant memories
- Summarization: compress old context rather than dropping it
- Agent-managed tools: the agent explicitly manages what's in working memory

---

## 3. Learning Mechanisms

| Mechanism | How It Works | Cost | Reliability | Transfer |
|-----------|-------------|------|-------------|----------|
| **Self-reflection** (Reflexion) | Agent reviews output, extracts verbal feedback | 1 LLM call/episode | Moderate -- can hallucinate | Low -- trial-scoped |
| **Causal abstraction** (CLIN) | Extract situation→action→outcome rules | 1 LLM call/episode | High -- structured | High -- cross-task |
| **Contrastive learning** (ExpeL) | Compare successes vs failures, extract insights | 1 LLM call/batch | High -- grounded in evidence | Medium -- cross-task |
| **Skill libraries** (Voyager) | Store verified executable procedures | 1 LLM call + verification | High -- tested before storage | Medium -- domain-bound |
| **Outcome feedback** | Environment/user signals success or failure | Near-free | High signal but sparse | N/A |
| **Preference learning** | Track user corrections and stated preferences | Near-free | High for explicit signals | N/A |
| **Peer observation** | Learn from teammates' successes | Free (read shared memory) | Depends on trust/quality | Low |

### What makes learning work in LLM agents

1. **Reflection must be grounded.** Abstract reflection ("I should try harder") is useless. Effective reflection cites specific actions and outcomes. CLIN's causal format enforces this.
2. **Forgetting is essential.** FadeMem: 82.1% retention of critical facts at 55% storage, vs 78.4% at 100% storage.
3. **Learning should be opt-in, not forced.** Per "agents are agents" -- learning loops are *available* as tools, not imposed as mandatory post-processing.
4. **Transfer is hard.** Domain-specific memories are more useful than general ones. Causal rules transfer better than narrative reflections.
5. **Reflection without persistence is ephemeral.** Reflections must be indexed and retrievable, not just logged.

---

## 4. Social Cognition for Multi-Agent Workgroups

### 4.1 Theory of Mind

Agents in workgroups benefit from modeling other agents' knowledge, beliefs, and capabilities:

- **Capability maps**: "Agent X is good at code review; Agent Y is good at research"
- **Shared mental models**: common understanding of the task, plan, and each other's roles
- **Attribution**: understanding *why* a teammate did something, not just *what*

From CSCW research (25+ years): workgroups with better shared mental models coordinate more effectively with *less explicit communication*. Maintaining these models of other agents enables implicit coordination without constant messaging.

### 4.2 Collective Memory

| Pattern | Description | Trade-off |
|---------|-------------|-----------|
| **Shared knowledge base** | All agents read/write the same memory store | Rich but noisy; needs curation |
| **Broadcast learning** | Agent shares a lesson with all teammates | Simple but can overwhelm |
| **Selective sharing** | Agent shares only with relevant teammates | Targeted but requires routing intelligence |
| **Stigmergy** | Agents leave traces in shared artifacts | Natural in TeaParty; implicit rather than explicit |

Stigmergy is already the dominant pattern in TeaParty -- agents leave their work in shared files and conversations. The opportunity is to layer *explicit* knowledge sharing on top.

Broadcast learning and shared knowledge interact with the messaging proposal (see [messaging](../systems/messaging/index.md)). Team leads bridge uber and subteam contexts via liaisons, enabling implicit coordination through structured message passing.

---

## 5. TeaParty's Current State

### 5.1 Implemented (Phase 1)

Phase 1 (proxy ACT-R memory) is implemented; see [human-proxy ACT-R overview](../systems/human-proxy/act-r/overview.md). The proxy has activation-based chunk storage with recency/frequency/context weighting, two-stage retrieval with threshold filtering, temporal dynamics (decay, strengthening), two-pass prediction for surprise extraction, and post-session hierarchical learning extraction.

### 5.2 Still Missing (Phases 2–7)

1. **General agent memory**: Only the proxy has activation-based memory. Intent, uber, team lead, and subteam agents lack episodic/semantic recall.
2. **Semantic memory indexing**: Extracted patterns (from learning extraction) are not yet indexed or retrievable during task execution.
3. **Reflection engine**: No mechanism for agents to reflect on their own performance and extract learnings in-session or post-session.
4. **Procedural memory**: No skill libraries or learned action preferences.
5. **Metacognition**: Agents cannot monitor their own uncertainty or ask for help.
6. **Decay and consolidation**: No memory maintenance; learnings accumulate unbounded.

---

## 6. Proposed Architecture (Phases 2–7)

### 6.1 Design Principles

1. **Agents are agents** -- Memory and learning are *tools available to the agent*, not imposed pipelines. The agent chooses when to reflect, what to remember, and when to retrieve.
2. **Advisory, not mandatory** -- Cognitive systems inform but don't constrain.
3. **Minimal overhead** -- No latency or cost added to every interaction. Learning happens *asynchronously* after interactions, not blocking the response path.
4. **Build on what exists** -- Extend the proxy's activation-based memory and the existing learning extraction pipeline.
5. **Start with episodic + semantic** -- Procedural memory (skill libraries) and metacognition are later phases.

### 6.2 Memory System

```
+-------------------------------------------------------------------+
|                        WORKING MEMORY                              |
|  (context window = system prompt + conversation history + memories) |
+-------------------------------------------------------------------+
         |                    |                    |
         v                    v                    v
+----------------+  +------------------+  +-------------------+
| EPISODIC       |  | SEMANTIC         |  | PROCEDURAL        |
| Memory store   |  | Memory store     |  | Task context      |
| (timestamped)  |  | (indexed)        |  | (agent-managed)   |
+----------------+  +------------------+  +-------------------+
         |                    |                    |
         +--------------------+--------------------+
                              |
                    +---------v----------+
                    | RETRIEVAL ENGINE   |
                    | recency x relevance|
                    | x confidence       |
                    +--------------------+
```

#### Episodic memory

Compressed records of past conversations and significant events. Example record:

```json
{
  "timestamp": "2026-02-15T14:30:00Z",
  "task_id": "api-redesign-job",
  "summary": "Discussed API redesign with user. They wanted REST over GraphQL. We agreed on versioned endpoints. User was satisfied with the v2/resources pattern.",
  "outcome": "success",
  "confidence": 0.9
}
```

Created at task completion, or when a task exceeds N messages without a summary. A cheap LLM call summarizes the session into an episode. Retrieved by recency + relevance to current task context.

#### Semantic memory

Distilled knowledge -- patterns, insights, domain facts -- synthesized from multiple episodes and learning events.

```json
{
  "memory_type": "pattern",
  "content": "This workgroup prefers TypeScript over JavaScript for new modules.",
  "scope": "task-based",
  "confidence": 0.85,
  "extracted_at": "2026-02-20T10:00:00Z"
}
```

Created via the learning extraction system (post-session) or when an agent detects a recurring pattern across episodes. High-confidence memories relevant to the current context are indexed and retrieved for injection.

#### Procedural memory

How to do things -- preferred tools, response styles, task-specific strategies. Agent-scoped; always loaded with agent context.

```json
{
  "tool_preferences": {
    "code_review": ["Read", "Grep", "Edit"],
    "research": ["WebSearch", "WebFetch"]
  },
  "response_style": {
    "preferred_length": "medium",
    "format_preferences": ["uses code blocks", "includes examples"]
  }
}
```

Updated after successful tool-use sequences, after user feedback, or through explicit agent request.

### 6.3 Learning Cycle

Inspired by Soar's perceive-decide-act-learn cycle and Reflexion's verbal RL:

```
            Task begins
                 |
                 v
        +----------------------+
        |   1. PERCEIVE        |    Retrieve relevant memories
        |   Assemble context   |    from episodic and semantic stores
        +----------------------+
                 |
                 v
        +----------------------+
        |   2. RESPOND         |    Normal agent response
        |   (existing path)    |    in conversation
        +----------------------+
                 |
                 v
        +----------------------+
        |   3. OBSERVE         |    Detect learning signals:
        |   Extract signals    |    - explicit feedback
        +----------------------+    - task success/failure
                 |                  - correction patterns
                 v                  - new information
        +----------------------+
        |   4. LEARN           |    Write learning events,
        |   Update memory      |    update memory stores
        +----------------------+
                 |
                 v
        +----------------------+
        |   5. REFLECT         |    Post-session: synthesize
        |   (post-task, async) |    into semantic knowledge
        +----------------------+
```

#### Signal detection (Step 3)

| Signal | Detection Method | Example |
|--------|-----------------|---------|
| Explicit praise | Keyword + sentiment | "Great answer!", "Perfect" |
| Explicit correction | Keyword + negation | "Actually, it should be X", "No, I meant..." |
| Task outcome | Task completion status | Completed vs. cancelled |
| User re-engagement | Same topic in new task | User asks the same question again |
| Preference expression | Keyword patterns | "I prefer...", "Always use...", "Don't..." |
| Tool success/failure | Tool result analysis | Error in tool output vs. successful execution |

A lightweight post-response analyzer runs after each agent message. Keyword matching first (zero LLM cost), falling back to a cheap LLM call only when ambiguous.

#### Memory formation (Step 4)

On signal detection:
1. Write a learning event record (signal type, value, linked to message/task).
2. If the signal implies a durable fact: create or update a semantic memory record.
3. If the signal implies a procedural change: update procedural memory.

**Confidence scoring**:
- Single observation: 0.5
- Confirmed by second observation: 0.7
- Contradicted: decrease by 0.2
- Explicitly stated ("always do X"): 0.95

#### Reflection (Step 5)

Runs asynchronously after task completion:
1. Gather recent learning events for the agent.
2. Gather recent episodic memories.
3. Send to cheap LLM: "Given these recent experiences, what patterns, insights, or corrections should I remember?"
4. Store resulting insights as semantic memories, scoped appropriately.
5. Prune low-confidence, old, or contradicted memories.

### 6.4 Memory Retrieval for Prompt Assembly

How memories enter the agent's working memory (context window) when a new task starts:

1. Load procedural memory (task preferences, tools, styles).
2. Query episodic memories for relevant past tasks (by keyword/semantic match, recency).
3. Query semantic memories for relevant patterns and knowledge (high confidence, scope match).
4. Format into a natural-language block, budget-constrained to ~800 tokens.

Example injection:

```
From your experience:
- This workgroup prefers TypeScript for new modules (high confidence)
- User tends to ask for examples alongside explanations
- Previous task on this topic: discussed REST vs GraphQL, agreed on versioned endpoints
```

Retrieval scoring:

```
score = α·recency(m) + β·relevance(m, query) + γ·importance(m)

recency(m)    = exponential decay from m.created_at
relevance(m)  = keyword/embedding similarity to current task context
importance(m) = f(m.confidence, m.relevance_count)
α, β, γ       = tunable weights (default: 0.2, 0.5, 0.3)
```

Budget: retrieve at most **5–8 memories** per task to avoid context bloat.

### 6.5 Multi-Agent Learning and Messaging

**Shared workgroup knowledge**: Semantic memories at "institutional" or "task-based" scope are shared across agents working on the same task or in the same domain.

**Private agent memories**: Agent-specific observations and preferences remain private unless explicitly promoted to shared scope.

**Cross-agent messaging**: The messaging system (see [messaging](../systems/messaging/index.md)) enables agents to explicitly share learnings via liaisons. Team leads consolidate subteam experiences and broadcast institutional patterns upward.

### 6.6 Cross-Level Learning Flows

The shared memory pool enables learning to flow across hierarchy levels without explicit routing.

- **Upward**: When the human corrects a plan at a gate ("add a rollback strategy"), the proxy records the outcome. The next time the human asks the office manager "how's the POC project going?", the office manager retrieves that record and can report what happened.
- **Downward**: When the human tells the office manager "focus on security across all projects", a steering record is produced. The next time an agent reviews a plan, it retrieves that record and gives extra scrutiny to security aspects.
- **Lateral**: Patterns in one project inform another. Repeated corrections for missing error handling in one project surface when another project produces a similar plan.

Cross-level retrieval is an emergent property of shared memory with activation-based retrieval, not an engineered pipeline. Structural filters (state, task type) and semantic filters (embedding similarity) prevent noise.

**Risk: invisible retrieval errors.** Cross-level retrieval errors may be invisible because LLM output looks plausible. A chunk from a different context gets woven into a coherent-sounding response and nobody notices the reasoning was based on an irrelevant memory. Spot-checks should specifically look for plausible-but-wrong cross-level retrievals.

---

## 7. Implementation Phases

Phase 1 (proxy ACT-R memory) is **done** -- implemented in `teaparty/proxy/memory.py`, `teaparty/proxy/agent.py`, and `teaparty/learning/extract.py`. See the [human-proxy ACT-R docs](../systems/human-proxy/act-r/overview.md).

### Phase 2: General Agent Memory Retrieval

Extend memory retrieval to all agents (not just proxies):
- Episodic memory store (indexed by agent, task, timestamp).
- Semantic memory store (indexed by agent, scope, confidence).
- Retrieval pipeline: score by recency + relevance + importance.
- Integrate into agent prompt construction -- adapt the proxy's activation-based retrieval to intent, uber, team-lead, and subteam agents.

### Phase 3: Reflection Engine

Asynchronous post-task reflection:
- After task completion, trigger reflection cycle (async, non-blocking).
- Agent synthesizes learning events and episodic memories into semantic knowledge.
- Use a cheap LLM for reflection.
- Implements scoping and the promotion chain already established by the learning extraction system.

### Phase 4: Signal Detection and Learning Events

Automated learning-signal extraction:
- Keyword-based detection (explicit feedback, corrections, preferences).
- Fallback to a cheap LLM for ambiguous signals.
- Immutable learning-event records (audit trail).

### Phase 5: Shared Memory via Messaging

Cross-agent knowledge sharing:
- Semantic memories at "institutional" and "task-based" scope are shared.
- Team leads access subteam memories for consolidation.
- Messaging system (liaisons) handles explicit broadcast.
- Enables implicit coordination without conversation overload.

### Phase 6: Consolidation and Decay

Memory maintenance:
- Time-based decay: memories fade if unused.
- Importance-based retention: high-confidence memories persist.
- Consolidation: specific episodes → general knowledge patterns.

### Phase 7: Procedural Memory and Skill Libraries

Agent-authored procedures and capabilities:
- Agents can define reusable "skills" (structured task descriptions).
- Skills stored and indexed by capability description.
- Retrieved during prompt construction when relevant.
- Builds on the workflow system but is agent-authored rather than admin-defined.

---

## 8. Design Tensions and Trade-offs

**Autonomy vs. control.** Agent-managed memory (MemGPT) is well-supported, but unbounded writes risk cost (every memory is a retrieval candidate), quality (redundant or low-value memories), and privacy (memorizing sensitive information). *Mitigation*: rate limits, confidence thresholds, admin visibility.

**Persistence vs. forgetting.** Too much → context pollution. Too little → agents never develop. FadeMem: 82.1% retention at 55% storage with decay vs. 78.4% at 100% without. *Mitigation*: combine time-based decay with importance scoring; consolidation preserves essence while specifics fade.

**Individual vs. collective learning.** Individual memory is high-signal; shared memory enables coordination but introduces noise. *Mitigation*: default to private; sharing is an explicit agent action.

**Cost of reflection.** ~500–1000 tokens per call on a cheap model; ~80 calls/day for a 4-agent workgroup is negligible. But bad reflections pollute memory. *Mitigation*: disabled by default; enable per-workgroup; monitor memory quality.

**Latency.** Memory retrieval adds DB query + scoring per turn. Target <50ms for <1000 memories per agent. Reflection is fully async.

---

## 9. References

### Classical Cognitive Architectures
- Anderson. "An Integrated Theory of the Mind" (ACT-R), *Psychological Review*, 2004.
- Laird. *The Soar Cognitive Architecture*, MIT Press, 2012.
- Sun. "The CLARION Cognitive Architecture", 2016.
- Franklin et al. "LIDA: A Systems-level Architecture for Cognition, Emotion, and Learning", IEEE, 2014.
- Baars. *A Cognitive Theory of Consciousness*, Cambridge University Press, 1988.

### Modern LLM-Agent Architectures
- Sumers, Yao, Narasimhan & Griffiths. ["Cognitive Architectures for Language Agents"](https://arxiv.org/abs/2309.02427) (CoALA), TMLR 2024.
- Park et al. ["Generative Agents"](https://arxiv.org/abs/2304.03442), UIST 2023.
- Shinn et al. ["Reflexion"](https://arxiv.org/abs/2303.11366), NeurIPS 2023.
- Wang et al. ["Voyager"](https://arxiv.org/abs/2305.16291), 2023.
- Majumder et al. ["CLIN"](https://arxiv.org/abs/2310.10134), 2024.
- Packer et al. ["MemGPT"](https://arxiv.org/abs/2310.08560), 2023.
- Zhao et al. ["ExpeL"](https://arxiv.org/abs/2308.10144), AAAI 2024.
- ["AutoRefine"](https://arxiv.org/html/2601.22758v1), 2025.

### Memory Systems
- Chhikara et al. ["Mem0"](https://arxiv.org/abs/2504.19413), 2025.
- ["FadeMem"](https://www.co-r-e.com/method/agent-memory-forgetting), 2025.
- ["Episodic Memory is the Missing Piece for Long-Term LLM Agents"](https://arxiv.org/abs/2502.06975), 2025.

### Multi-Agent / Collaborative Memory
- Rezazadeh et al. ["Collaborative Memory: Multi-User Memory Sharing in LLM Agents"](https://arxiv.org/abs/2505.18279), ICML 2025.
- ["Memory as a Service (MaaS)"](https://arxiv.org/html/2506.22815v1), 2025.
- ["Theory of Mind for Multi-Agent Collaboration via LLMs"](https://arxiv.org/abs/2310.10701), 2024.
- Gross. "Supporting Effortless Coordination", *CSCW Journal*, 2013.

### Surveys and Related Work
- [Agent Memory Paper List](https://github.com/Shichun-Liu/Agent-Memory-Paper-List)
- "A Survey on the Memory Mechanism of Large Language Model-based Agents", ACM TOIS, 2025.
- [Letta (MemGPT)](https://github.com/letta-ai/letta)
- [LangGraph](https://www.langchain.com/langgraph)

---

## 10. Summary

Phase 1 gave the human proxy an activation-based memory system and learning-extraction pipeline (see [human-proxy ACT-R](../systems/human-proxy/act-r/overview.md)). Phases 2–7 extend those foundations to every other agent in TeaParty: general episodic/semantic stores, an asynchronous reflection engine, automated signal detection, shared workgroup memory, consolidation and decay, and agent-authored procedural skills.

The proposed architecture follows three principles from the research:

1. **Memory retrieval matters more than memory storage** -- the scoring and injection pipeline is the highest-value work.
2. **Reflection should be grounded and optional** -- agents reflect on specific interactions, not abstractly, and only when it's useful.
3. **Agents manage their own memory** -- following MemGPT, agents get tools for remember/recall/forget rather than having learning imposed on them.

Phase 2 (general agent memory retrieval) is the recommended starting point: adapt the proxy's activation-based retrieval pipeline to all agents, using similar episodic and semantic storage.
