# Cognitive Architecture for Learning Agents

This document proposes extending memory and learning capabilities to all TeaParty agents, building on the ACT-R proxy memory system that is already implemented for human proxy agents.

A design for giving TeaParty agents the ability to learn, remember, and adapt over time -- grounded in cognitive science research and mapped to the existing system.

---

## 1. Research Foundations

### 1.1 What Is a Cognitive Architecture?

A cognitive architecture is a theory of the fixed structures and processes that underlie intelligent behavior. In AI, it's the infrastructure that sits *around* the reasoning engine (here, an LLM) -- providing memory, learning, goal management, and self-monitoring capabilities that the raw model lacks.

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

The key insight from decades of cognitive science: **intelligence is not just reasoning -- it's the memory systems that feed reasoning, and the learning systems that update memory from experience.**

### 1.2 Classical Architectures Relevant to TeaParty

**ACT-R** (Anderson, Carnegie Mellon) models cognition as the interaction of declarative memory (facts, with activation levels that decay and strengthen) and procedural memory (production rules that fire when conditions match). Learning happens through *strengthening* -- chunks that get retrieved more often become easier to retrieve. The subsymbolic layer computes activation as a function of recency, frequency, and context, which determines what the agent "thinks of" in any given moment.

**Soar** (Laird, University of Michigan) uses a working-memory-centric cycle: perceive → propose operators → select → apply → detect impasses → subgoal. When an impasse is resolved, *chunking* compiles the solution into a new production rule, so the agent never encounters the same impasse twice. Soar also maintains episodic memory (timestamped snapshots of working memory) and semantic memory (long-term factual store) that are queried during deliberation.

**LIDA** (Franklin, University of Memphis) implements Global Workspace Theory -- a model of how consciousness arises from competing coalitions of information. Attention codelets form coalitions from the current situational model; the winning coalition gets "broadcast" globally, making it available to all modules simultaneously. This broadcast-then-learn cycle is the basis for all LIDA learning: perceptual, episodic, procedural, and attentional.

### 1.3 LLM-Agent Cognitive Architectures (State of the Art)

Recent work has adapted cognitive architecture principles for LLM-based agents.

#### 1.3.1 CoALA -- Cognitive Architectures for Language Agents

**Sumers, Yao, Narasimhan & Griffiths (2024)** provide the most comprehensive theoretical framework. CoALA maps classical cognitive architecture concepts onto LLM agents:

| CoALA Component | Classical Analog | LLM Agent Implementation |
|----------------|-----------------|-------------------------|
| Working Memory | ACT-R buffers, Soar WM | Context window contents |
| Episodic Memory | Soar episodic store | Conversation logs, event records |
| Semantic Memory | ACT-R declarative, Soar semantic | Knowledge base, embeddings |
| Procedural Memory | ACT-R productions, Soar rules | Prompt templates, tool definitions, learned skills |
| Decision Cycle | Soar propose-select-apply | Perceive → plan → act → observe loop |

CoALA's key contribution is the taxonomy: agents differ in *what memory types they use*, *what their action space is*, and *how they learn*. It's not a single architecture but a design space.

#### 1.3.2 Generative Agents (Stanford, Park et al. 2023)

Simulated 25 agents in a sandbox environment with:

- **Memory stream**: timestamped log of all observations and actions
- **Retrieval**: recency × relevance × importance scoring to surface memories
- **Reflection**: periodic synthesis of recent memories into higher-level insights ("I've noticed Klaus often avoids social events")
- **Planning**: daily plans decomposed into hourly actions, revised based on observations

Key finding: reflection was the critical ingredient. Without it, agents repeated patterns and failed to develop. With it, emergent social behaviors arose (party planning, opinion formation, relationship dynamics).

#### 1.3.3 Reflexion (Shinn et al. 2023)

Agents that learn from failure through verbal self-reflection:

1. Agent attempts a task
2. Evaluator scores the attempt
3. Agent reflects on what went wrong (generating natural language feedback)
4. Reflection is stored in memory and prepended to next attempt

No weight updates -- learning is entirely through accumulated reflective text in the context window. Achieved near-human performance on HumanEval coding after 2-3 reflection cycles.

#### 1.3.4 Voyager (Wang et al. 2023)

Minecraft agent with a **skill library** -- procedural memory implemented as a growing codebase:

- **Curriculum**: automatic task proposal based on current capabilities
- **Skill library**: verified JavaScript functions stored and retrieved by description
- **Iterative refinement**: failed skills are debugged via environment feedback

Key insight: procedural memory as *executable code* is more reliable than natural language instructions.

#### 1.3.5 CLIN -- Continually Learning from Interactions (Majumder et al. 2024)

Agents that persistently learn across task episodes:

- After each episode, agent extracts **causal abstractions** ("when X happens, doing Y leads to Z")
- Abstractions stored in a growing memory that persists across episodes
- Memory is retrieved and injected into the prompt for future tasks

CLIN showed that agents *do* improve over time with this approach, and that memories transfer across similar (but not identical) tasks.

#### 1.3.6 MemGPT / Letta (Packer et al. 2023-2024)

Explicit memory management as an OS-like system:

- **Main context** (working memory): limited, actively managed
- **Archival memory**: unlimited long-term storage, searchable
- **Recall memory**: conversation history, paginated
- Agent explicitly calls `archival_memory_insert`, `archival_memory_search`, `conversation_search` tools

Key insight: give agents *tools* for memory management rather than automating it. The agent decides what to remember, what to forget, and when to retrieve.

#### 1.3.7 ExpeL -- Experiential Learning (Zhao et al. 2024)

Agents that learn from *contrasting* successes and failures:

- **Phase 1**: Agent attempts training tasks, recording full trajectories (both successes and failures)
- **Phase 2**: Agent *compares* failed and successful trajectories to identify what differed, then extracts cross-task patterns
- Extracted insights are iteratively refined: adding, editing, voting on importance

Key distinction from Reflexion: ExpeL learns from *contrasts* ("this worked, that didn't, and the difference was...") rather than from failures alone. Does NOT require repeated attempts at the same task -- insights transfer across tasks.

#### 1.3.8 Recent Systems (2025)

**AutoRefine** -- Automatically extracts **dual-form Experience Patterns**:
- **Specialized subagents** for recurring procedural subtasks
- **Skill patterns** (guidelines or code snippets) for static knowledge
- Continuous maintenance: scoring, pruning, and merging patterns to prevent degradation

Results: ALFWorld 98.4%, ScienceWorld 70.4%. On TravelPlanner, automatic extraction exceeds manually designed systems (27.1% vs 12.1%) -- showing that learned patterns can outperform hand-crafted ones.

**Mem0** -- Production-ready memory architecture with two variants:
- **Basic**: structured extraction + updation pipeline
- **Graph-enhanced (Mem0g)**: directed labeled graph of entities and relationships

Results: 26% accuracy boost, 91% lower p95 latency, 90% token savings vs. full-context approaches.

**FadeMem** (2025) -- Biologically-inspired decay/forgetting -- retains 82.1% of critical facts using only 55% of storage (vs. 78.4% retention at 100% storage without decay). Selective forgetting *improves* retention quality.

### 1.4 Key Takeaways for TeaParty

1. **Memory is not monolithic.** Multiple types serve different purposes: episodic (what happened), semantic (what I know), procedural (how to do things), working (what I'm thinking about now).
2. **Learning signals are diverse.** Explicit feedback, implicit success/failure, self-reflection, and inter-agent observation all contribute.
3. **Retrieval is as important as storage.** Activation-based retrieval (ACT-R), recency-importance-relevance weighting (Generative Agents), and embedding similarity all solve the same problem: surfacing the right memory at the right time.
4. **Multi-agent memory needs access control.** Not all agents should see all memories. Shared workgroup knowledge vs. private agent insights.
5. **The LLM context window *is* working memory.** What you put in the prompt determines what the agent can think about.

---

## 2. Memory Systems: What Works

### 2.1 Episodic Memory (What Happened)

**What it is**: Timestamped records of specific experiences -- "In conversation X, user Y asked about Z, and my approach of W worked well."

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

This is directly descended from ACT-R's activation-based retrieval (combining recency, frequency, and contextual relevance) -- validated for 40+ years in cognitive science.

Recent finding: "Episodic Memory is the Missing Piece for Long-Term LLM Agents" (2025) argues that most agent systems underweight episodic memory relative to semantic/procedural. Agents that can recall specific past experiences perform better than those relying only on general knowledge.

### 2.2 Semantic Memory (What I Know)

**What it is**: General knowledge and facts -- "User prefers concise responses", "The codebase uses FastAPI with SQLModel", "Markdown headers should use ATX style."

**What works in practice**:
- **Self-extracted knowledge** (Reflexion, CLIN): agent distills knowledge from experience
- **Key-value stores**: simple and effective for factual knowledge
- **Vector stores**: better for fuzzy/semantic retrieval but add infrastructure complexity
- **Hierarchical summaries**: knowledge at different levels of abstraction

### 2.3 Procedural Memory (How to Do Things)

**What it is**: Skills, strategies, workflows -- "When asked to review code, first read the PR diff, then check for security issues, then comment on style."

**What works in practice**:
- **Skill libraries** (Voyager): executable code/prompts indexed by capability description
- **Workflow templates**: structured plans that can be adapted (TeaParty already has workflows)
- **Prompt libraries**: curated prompts for specific tasks, refined through use
- **Natural language procedures** are fragile; structured/executable forms are more reliable

### 2.4 Working Memory (Active Context)

**What it is**: The information actively being reasoned about -- the LLM's context window.

**What works in practice**:
- **Selective injection**: retrieve only relevant memories into the prompt
- **Summarization**: compress old context rather than dropping it
- **Agent-managed tools**: agent explicitly manages what's in working memory

---

## 3. Learning Mechanisms

### 3.1 Learning Mechanisms Compared

| Mechanism | How It Works | Cost | Reliability | Transfer |
|-----------|-------------|------|-------------|----------|
| **Self-reflection** (Reflexion) | Agent reviews output, extracts verbal feedback | 1 LLM call/episode | Moderate -- can hallucinate | Low -- trial-scoped |
| **Causal abstraction** (CLIN) | Extract situation→action→outcome rules | 1 LLM call/episode | High -- structured | High -- cross-task |
| **Contrastive learning** (ExpeL) | Compare successes vs failures, extract insights | 1 LLM call/batch | High -- grounded in evidence | Medium -- cross-task |
| **Skill libraries** (Voyager) | Store verified executable procedures | 1 LLM call + verification | High -- tested before storage | Medium -- domain-bound |
| **Outcome feedback** | Environment/user signals success or failure | Near-free | High signal but sparse | N/A |
| **Preference learning** | Track user corrections and stated preferences | Near-free | High for explicit signals | N/A |
| **Peer observation** | Learn from teammates' successes | Free (read shared memory) | Depends on trust/quality | Low |

CLIN's causal abstractions outperform Reflexion's narrative reflections by 23 absolute points on ScienceWorld. The key difference: structured "when X, doing Y leads to Z" rules generalize better than "I should have done X instead."

### 3.2 What Makes Learning Work in LLM Agents

Research consensus points to several critical factors:

1. **Reflection must be grounded**: Abstract reflection ("I should try harder") is useless. Effective reflection cites specific actions and outcomes ("When I used `grep` instead of `find`, I found the file 3x faster because..."). CLIN's causal format enforces this.

2. **Forgetting is essential**: FadeMem (2025) demonstrates that selective forgetting *improves* quality -- 82.1% retention of critical facts at 55% storage, vs 78.4% at 100% storage. Agents that forget strategically remember important things better.

3. **Learning should be opt-in, not forced**: Per the TeaParty philosophy of "agents are agents, not scripted" -- learning loops should be *available* to agents as tools, not imposed as mandatory post-processing. Soar's impasse-driven model is the ideal: learn only when encountering a gap.

4. **Transfer is hard**: Memories from one context often don't apply cleanly in another. Domain-specific memories are more useful than general ones. CLIN's causal rules transfer better than narrative reflections.

5. **Reflection without persistence is ephemeral**: Self-reflection improves performance only if reflections are *persisted, indexed, and retrievable*. A reflection bank must be searchable and context-aware, not just a list.

---

## 4. Social Cognition for Multi-Agent Workgroups

### 4.1 Theory of Mind

Agents in workgroups benefit from modeling other agents' knowledge, beliefs, and capabilities:

- **Capability maps**: "Agent X is good at code review; Agent Y is good at research"
- **Shared mental models**: Common understanding of the task, the plan, and each other's roles
- **Attribution**: Understanding *why* a teammate did something, not just *what* they did

Research findings: LLMs show surprising Theory of Mind abilities in zero-shot settings. But maintaining consistent mental models of other agents over extended interactions remains an open challenge.

From CSCW research (25+ years): workgroups with better shared mental models coordinate more effectively with *less explicit communication*. This translates to agents maintaining models of other agents' capabilities, current state, and goals -- enabling implicit coordination without constant messaging.

### 4.2 Collective Memory

Multi-agent workgroups can share knowledge in several ways:

| Pattern | Description | Trade-off |
|---------|-------------|-----------|
| **Shared knowledge base** | All agents read/write to the same memory store | Rich but noisy; needs curation |
| **Broadcast learning** | Agent shares a lesson with all teammates | Simple but can overwhelm |
| **Selective sharing** | Agent shares only with relevant teammates | Targeted but requires routing intelligence |
| **Stigmergy** | Agents leave traces in shared artifacts (files, messages) | Natural in TeaParty; implicit rather than explicit |

For TeaParty, **stigmergy** is already the dominant pattern -- agents leave their work in shared files and conversations. The opportunity is to layer *explicit* knowledge sharing on top.

**Note on broadcast learning and messaging**: Broadcast learning and shared knowledge are addressed by the messaging proposal (see [messaging.md](messaging.md)). Team leads bridge uber and subteam contexts via liaisons, enabling implicit coordination through structured message passing.

---

## 5. TeaParty's Current State

### 5.1 Proxy Memory (Implemented)

The **ACT-R proxy memory system** (`proxy_memory.py`) provides cognitive foundations for human proxy agents:

- **Activation-based chunk storage**: Memories stored as chunks with computed activation levels
- **Two-stage retrieval**: (1) activation computation based on recency, frequency, and context; (2) retrieval threshold filtering
- **Temporal dynamics**: Decay of unused memories, strengthening through access

This foundation is production-ready and used by the human proxy in the POC orchestrator.

### 5.2 Two-Pass Prediction (Implemented)

The **two-pass prediction system** (`proxy_agent.py`) extracts learning signals from agent interactions:

- **Prior prediction**: Agent predicts outcome before taking action
- **Posterior update**: Agent observes actual result
- **Surprise extraction**: Mismatch between prior and posterior reveals unexpected patterns

This enables proxy agents to identify when their assumptions were violated -- a key learning signal.

### 5.3 Learning Extraction (Implemented)

The **learning extraction system** (`learnings.py`) runs post-session and hierarchically structures discoveries:

- **Institutional learning**: Patterns applicable to all agents in the system
- **Task-based learning**: Patterns specific to a task type or domain
- **Proxy learning**: Proxy-specific heuristics and preferences
- **Promotion chain**: Learnings propagate from narrow (proxy) to broad (institutional) scope
- **Hierarchical scoping**: 10-level taxonomy from specific to general

Details are in [learning-system.md](../conceptual-design/learning-system.md).

### 5.4 Still Missing

TeaParty does not yet have:

1. **General agent memory**: Only proxy agents have activation-based memory. Intent and uber agents lack episodic/semantic recall.
2. **Semantic memory**: Extracted patterns (from learning extraction) are not yet indexed or retrievable during task execution.
3. **Reflection**: No mechanism for agents to reflect on their own performance and extract learnings in-session.
4. **Procedural memory**: No skill libraries or learned action preferences.
5. **Metacognition**: Agents cannot monitor their own uncertainty or ask for help.
6. **Decay and consolidation**: No memory maintenance mechanisms; learnings accumulate unbounded.

---

## 6. Proposed Cognitive Architecture

### 6.1 Design Principles

Following TeaParty's philosophy:

1. **Agents are agents** -- Memory and learning are *tools available to the agent*, not imposed pipelines. The agent chooses when to reflect, what to remember, and when to retrieve.
2. **Advisory, not mandatory** -- cognitive systems inform but don't constrain
3. **Minimal overhead** -- Don't add latency or cost to every interaction. Learning happens *asynchronously* after interactions, not blocking the response path.
4. **Build on what exists** -- Use the activation-based proxy memory and learning extraction that already work.
5. **Start with episodic + semantic** -- Procedural memory (skill libraries) and metacognition are later phases.

### 6.2 Memory System

Mapping cognitive architecture research to TeaParty:

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
|                |  |                  |  |                   |
| Conversation   |  | Synthesized      |  | "When doing code  |
| summaries,     |  | knowledge from   |  |  review, use file |
| key moments,   |  | many episodes    |  |  tools first"     |
| outcomes       |  |                  |  |                   |
|                |  | "User prefers    |  |                   |
| "Last Tuesday  |  |  concise answers"|  |                   |
|  we discussed  |  |                  |  |                   |
|  the API..."   |  | "The codebase    |  |                   |
|                |  |  uses FastAPI"   |  |                   |
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

#### 6.2.1 Episodic Memory

**What:** Compressed records of past conversations and significant events.

**Storage:** Timestamped memory store indexed by agent, task, and timestamp.

**Contents:**
```json
{
  "timestamp": "2026-02-15T14:30:00Z",
  "task_id": "api-redesign-job",
  "summary": "Discussed API redesign with user. They wanted REST over GraphQL. We agreed on versioned endpoints. User was satisfied with the v2/resources pattern.",
  "outcome": "success",
  "confidence": 0.9
}
```

**When created:** At task completion, or when a task exceeds N messages without a summary. A "cheap" LLM call summarizes the session into an episode.

**Retrieval:** By recency (most recent episodes first) and relevance (keyword/semantic match to current task context).

#### 6.2.2 Semantic Memory

**What:** Distilled knowledge -- patterns, insights, domain facts -- synthesized from multiple episodes and learning events.

**Storage:** Indexed memory store with memory type, confidence score, and scope level.

**Contents:**
```json
{
  "memory_type": "pattern",
  "content": "This workgroup prefers TypeScript over JavaScript for new modules.",
  "scope": "task-based",
  "confidence": 0.85,
  "extracted_at": "2026-02-20T10:00:00Z"
}
```

**When created:** Via the learning extraction system (post-session), or when an agent detects a recurring pattern across episodes.

**Retrieval:** All high-confidence semantic memories relevant to the current context are indexed and retrieved for injection.

#### 6.2.3 Procedural Memory

**What:** How to do things -- preferred tools, response styles, task-specific strategies.

**Storage:** Agent-scoped configuration, always loaded with agent context.

**Contents:**
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

**When updated:** After successful tool use sequences, after user feedback, or through explicit agent request.

**Retrieval:** Always included (lives with agent context).

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
                    |               - correction patterns
                    v               - new information
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

#### 6.3.1 Signal Detection (Step 3: OBSERVE)

Learning signals extracted from task flow:

| Signal | Detection Method | Example |
|--------|-----------------|---------|
| Explicit praise | Keyword + sentiment | "Great answer!", "Perfect" |
| Explicit correction | Keyword + negation | "Actually, it should be X", "No, I meant..." |
| Task outcome | Task completion status | Completed vs. cancelled |
| User re-engagement | Same topic in new task | User asks the same question again |
| Preference expression | Keyword patterns | "I prefer...", "Always use...", "Don't..." |
| Tool success/failure | Tool result analysis | Error in tool output vs. successful execution |

**Implementation:** A lightweight post-response analyzer runs after each agent message. Uses keyword matching first (zero LLM cost), falling back to a cheap LLM call only when ambiguous.

#### 6.3.2 Memory Formation (Step 4: LEARN)

When a signal is detected:
1. Write a learning event record (signal type, value, linked to message/task)
2. If the signal implies a durable fact: create or update a semantic memory record
3. If the signal implies a procedural change: update procedural memory

**Confidence scoring:**
- Single observation: 0.5
- Confirmed by second observation: 0.7
- Contradicted: decrease by 0.2
- Explicitly stated by user ("always do X"): 0.95

#### 6.3.3 Reflection (Step 5: REFLECT)

Inspired by Generative Agents' reflection process. Runs asynchronously after task completion:

**Trigger:** When a task completes, or when an agent accumulates N learning events since last reflection.

**Process:**
1. Gather recent learning events for the agent
2. Gather recent episodic memories
3. Send to cheap LLM: "Given these recent experiences, what patterns, insights, or corrections should I remember?"
4. Store resulting insights as semantic memories, scoped appropriately
5. Prune low-confidence, old, or contradicted memories

### 6.4 Memory Retrieval for Prompt Assembly

The critical integration point -- how memories enter the agent's working memory (context window):

When preparing an agent for a new task:
1. Load procedural memory (task preferences, tools, styles)
2. Query episodic memories for relevant past tasks (by keyword/semantic match, recency)
3. Query semantic memories for relevant patterns and knowledge (high confidence, scope match)
4. Format into a natural-language block, budget-constrained to ~800 tokens

**Example prompt injection:**
```
From your experience:
- This workgroup prefers TypeScript for new modules (high confidence)
- User tends to ask for examples alongside explanations
- Previous task on this topic: discussed REST vs GraphQL, agreed on versioned endpoints
```

**Retrieval scoring:**

```
score = α·recency(m) + β·relevance(m, query) + γ·importance(m)

where:
  recency(m)    = exponential decay from m.created_at
  relevance(m)  = keyword/embedding similarity to current task context
  importance(m) = f(m.confidence, m.relevance_count)
  α, β, γ       = tunable weights (default: 0.2, 0.5, 0.3)
```

Budget: retrieve at most **5-8 memories** per task to avoid context bloat.

### 6.5 Multi-Agent Learning and Messaging

In workgroup sessions, agents can learn from observing each other and from structured communication:

**Shared workgroup knowledge:** Semantic memories at "institutional" or "task-based" scope are shared across agents working on the same task or in the same domain.

**Private agent memories:** Agent-specific observations and preferences remain private unless explicitly promoted to shared scope.

**Cross-agent messaging:** The messaging system (see [messaging.md](messaging.md)) enables agents to explicitly share learnings via liaisons. Team leads consolidate subteam experiences and broadcast institutional patterns upward.

---

## 8. Implementation Phases

### Phase 1: ACT-R Proxy Memory (DONE)

- Activation-based chunk storage with recency/frequency/context weighting
- Two-stage retrieval with threshold filtering
- Temporal dynamics (decay, strengthening)
- Status: Implemented in `proxy_memory.py` and deployed in the POC

### Phase 2: General Agent Memory Retrieval

Extend memory retrieval to all agents (not just proxies):
- Implement episodic memory store (indexed by agent, task, timestamp)
- Implement semantic memory store (indexed by agent, scope, confidence)
- Implement retrieval pipeline: score by recency + relevance + importance
- Integrate into agent prompt construction (similar to proxy memory but expanded to all agents)

### Phase 3: Reflection Engine

Add asynchronous post-task reflection:
- After task completion, trigger reflection cycle (async, non-blocking)
- Agent synthesizes learning events and episodic memories into semantic knowledge
- Use cheap LLM for reflection (lower cost than full model)
- Implements scoping and promotion chain for hierarchical learning

### Phase 4: Signal Detection and Learning Events

Implement automated learning signal extraction:
- Keyword-based signal detection (explicit feedback, corrections, preferences)
- Fallback to cheap LLM for ambiguous signals
- Write learning event records (immutable audit trail)
- Low cost, high signal reliability

### Phase 5: Shared Memory via Messaging

Enable cross-agent knowledge sharing:
- Semantic memories scoped to "institutional" and "task-based" levels are shared
- Team leads access subteam memories for consolidation
- Messaging system (liaisons) handles explicit broadcast
- Enables implicit coordination without conversation overload

### Phase 6: Consolidation and Decay

Implement memory maintenance:
- Time-based decay: memories fade if unused
- Importance-based retention: high-confidence memories persist
- Consolidation: specific episodes → general knowledge patterns
- Prevents memory bloat and improves recall quality

### Phase 7: Procedural Memory and Skill Libraries

Agent-authored procedures and capabilities:
- Agents can define reusable "skills" (structured task descriptions)
- Skills stored and indexed by capability description
- Retrieved during prompt construction when relevant
- Builds on workflow system but is agent-authored rather than admin-defined

---

## 9. Design Tensions and Trade-offs

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

**Mitigation**: Combine time-based decay with importance scoring. Memories fade naturally unless they're important or frequently accessed. Consolidation preserves the essence while allowing specifics to fade -- mirroring the human trajectory from vivid episodes to general knowledge.

### Individual vs. Collective Learning

- Individual memory is private and high-signal
- Shared memory enables workgroup coordination but introduces noise

**Mitigation**: Default to private; sharing is an explicit agent action. Workgroup admins can view all memories.

### Cost of Reflection

Each reflection call costs ~500-1000 tokens (using a cheap model). For a workgroup with 4 agents doing 20 interactions/day, that's ~80 extra cheap-model calls/day -- negligible cost.

But reflection *quality* matters: bad reflections pollute memory. The cheap model may produce lower-quality insights than the main model.

**Mitigation**: Start with reflection disabled by default. Enable per-workgroup. Monitor memory quality.

### Latency

Memory retrieval adds a database query + scoring to each agent turn. This should be <50ms for typical memory sizes (<1000 memories per agent).

Reflection is fully async and adds zero latency to the user-facing response.

---

## 10. References

### Classical Cognitive Architectures
- Anderson. "An Integrated Theory of the Mind" (ACT-R), *Psychological Review*, 2004. -- Activation-based retrieval, production compilation.
- Laird. *The Soar Cognitive Architecture*, MIT Press, 2012. -- Impasse-driven learning, chunking, three-store memory.
- Sun. "The CLARION Cognitive Architecture", 2016. -- Dual-process implicit/explicit learning, metacognitive subsystem.
- Franklin et al. "LIDA: A Systems-level Architecture for Cognition, Emotion, and Learning", IEEE, 2014. -- Global workspace, attention gating.
- Baars. *A Cognitive Theory of Consciousness* (Global Workspace Theory), Cambridge University Press, 1988.

### Modern LLM-Agent Architectures
- Sumers, Yao, Narasimhan & Griffiths. ["Cognitive Architectures for Language Agents"](https://arxiv.org/abs/2309.02427) (CoALA), TMLR 2024. -- The unifying theoretical framework.
- Park et al. ["Generative Agents: Interactive Simulacra of Human Behavior"](https://arxiv.org/abs/2304.03442), UIST 2023. -- Memory streams, three-factor retrieval, reflection.
- Shinn et al. ["Reflexion: Language Agents with Verbal Reinforcement Learning"](https://arxiv.org/abs/2303.11366), NeurIPS 2023. -- Self-reflection for learning.
- Wang et al. ["Voyager: An Open-Ended Embodied Agent with Large Language Models"](https://arxiv.org/abs/2305.16291), 2023. -- Skill libraries, auto-curriculum.
- Majumder et al. ["CLIN: A Continually Learning Language Agent"](https://arxiv.org/abs/2310.10134), 2024. -- Causal abstraction learning, cross-episode persistence.
- Packer et al. ["MemGPT: Towards LLMs as Operating Systems"](https://arxiv.org/abs/2310.08560), 2023. -- Agent-managed memory hierarchy.
- Zhao et al. ["ExpeL: LLM Agents Are Experiential Learners"](https://arxiv.org/abs/2308.10144), AAAI 2024. -- Contrastive learning from successes and failures.
- ["AutoRefine"](https://arxiv.org/html/2601.22758v1), 2025. -- Dual-form experience patterns, automatic extraction outperforming manual design.
- Wu et al. ["LLM-ACTR"](https://arxiv.org/abs/2408.09176), 2024-2025. -- ACT-R decision-making embedded in LLMs.
- ["Brain-Inspired Modular Agentic Planner"](https://www.nature.com/articles/s41467-025-63804-5), Nature Communications, 2025.

### Memory Systems
- Chhikara et al. ["Mem0"](https://arxiv.org/abs/2504.19413), 2025. -- Production-ready structured memory with graph variant.
- ["FadeMem"](https://www.co-r-e.com/method/agent-memory-forgetting), 2025. -- Biologically-inspired forgetting, selective decay improves retention.
- ["Episodic Memory is the Missing Piece for Long-Term LLM Agents"](https://arxiv.org/abs/2502.06975), 2025.
- ["ACT-R-inspired Memory for LLM Agents"](https://dl.acm.org/doi/10.1145/3765766.3765803), 2024-2025.

### Multi-Agent / Collaborative Memory
- Rezazadeh et al. ["Collaborative Memory: Multi-User Memory Sharing in LLM Agents"](https://arxiv.org/abs/2505.18279), ICML 2025.
- ["Memory as a Service (MaaS)"](https://arxiv.org/html/2506.22815v1), 2025.
- ["Theory of Mind for Multi-Agent Collaboration via LLMs"](https://arxiv.org/abs/2310.10701), 2024.
- Gross. "Supporting Effortless Coordination", *CSCW Journal*, 2013. -- 25 years of awareness research.

### Surveys and Related Work
- [Agent Memory Paper List](https://github.com/Shichun-Liu/Agent-Memory-Paper-List) -- Curated bibliography.
- "A Survey on the Memory Mechanism of Large Language Model-based Agents", ACM TOIS, 2025.
- Khattab et al. ["DSPy: Compiling Declarative Language Model Calls into Self-Improving Pipelines"](https://arxiv.org/abs/2310.19115), 2024.
- Wu et al. ["AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation"](https://arxiv.org/abs/2308.08155), 2024.
- [Letta (MemGPT)](https://github.com/letta-ai/letta) -- Stateful agent platform with tiered memory
- [LangGraph](https://www.langchain.com/langgraph) -- Agent orchestration with persistence

---

## 11. Summary

TeaParty's proxy agents have **activated, working memory systems** (ACT-R basis, two-pass prediction, learning extraction). The next step is extending these capabilities to all agents in the POC orchestrator.

The proposed architecture follows three principles from the research:

1. **Memory retrieval matters more than memory storage** -- the scoring and injection pipeline is the highest-value work
2. **Reflection should be grounded and optional** -- agents reflect on specific interactions, not abstractly, and only when it's useful
3. **Agents manage their own memory** -- following MemGPT, agents get tools for remember/recall/forget rather than having learning imposed on them

Phase 1 and Phase 2 (general agent memory retrieval) can be implemented by adapting the proxy memory retrieval pipeline to all agents, using similar episodic and semantic storage. This is the recommended starting point.
