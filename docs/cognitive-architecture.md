# Cognitive Architecture for Learning Agents

A design for giving TeaParty agents the ability to learn, remember, and adapt over time — grounded in cognitive science research and mapped to the existing system.

## 1. Research Foundations

### 1.1 Classical Cognitive Architectures

The field of cognitive architecture has spent decades modeling how minds work. Three systems are most relevant to TeaParty:

**ACT-R** (Anderson, Carnegie Mellon) models cognition as the interaction of declarative memory (facts, with activation levels that decay and strengthen) and procedural memory (production rules that fire when conditions match). Learning happens through *strengthening* — chunks that get retrieved more often become easier to retrieve. The subsymbolic layer computes activation as a function of recency, frequency, and context, which determines what the agent "thinks of" in any given moment.

**Soar** (Laird, University of Michigan) uses a working-memory-centric cycle: perceive → propose operators → select → apply → detect impasses → subgoal. When an impasse is resolved, *chunking* compiles the solution into a new production rule, so the agent never encounters the same impasse twice. Soar also maintains episodic memory (timestamped snapshots of working memory) and semantic memory (long-term factual store) that are queried during deliberation.

**LIDA** (Franklin, University of Memphis) implements Global Workspace Theory — a model of how consciousness arises from competing coalitions of information. Attention codelets form coalitions from the current situational model; the winning coalition gets "broadcast" globally, making it available to all modules simultaneously. This broadcast-then-learn cycle is the basis for all LIDA learning: perceptual, episodic, procedural, and attentional.

### 1.2 CoALA: The Bridge to LLM Agents

The **Cognitive Architectures for Language Agents** framework (Sumers et al., 2024, TMLR) maps classical cognitive architecture concepts onto LLM-based systems. Its key insight: an LLM agent's cognition can be decomposed into:

| CoALA Component | Classical Analog | LLM Agent Implementation |
|----------------|-----------------|-------------------------|
| Working Memory | ACT-R buffers, Soar WM | Context window contents |
| Episodic Memory | Soar episodic store | Conversation logs, event records |
| Semantic Memory | ACT-R declarative, Soar semantic | Knowledge base, embeddings |
| Procedural Memory | ACT-R productions, Soar rules | Prompt templates, tool definitions, learned skills |
| Decision Cycle | Soar propose-select-apply | Perceive → plan → act → observe loop |

### 1.3 Modern LLM Learning Patterns

**MemGPT/Letta** — Two-tier memory: core memory (in-context, self-editable persona + user info) and archival/recall memory (out-of-context, searchable). The agent moves data between tiers via tool calls, creating an illusion of unlimited memory. Letta V1 has evolved this into a production framework.

**Reflexion** (Shinn et al., 2023) — Verbal reinforcement learning. After task failure, the agent writes a natural-language reflection ("I failed because X, next time I should Y") stored in a reflection buffer. On subsequent attempts, reflections are included in the prompt. No weight updates; all learning is in-context.

**Voyager** (Wang et al., 2023) — Lifelong skill accumulation in Minecraft. Three components: (1) automatic curriculum proposing increasingly hard tasks, (2) iterative code generation with self-verification, (3) a *skill library* of named, reusable programs indexed by description embedding. New skills build on old ones. Achieved 3.3x more unique items than baselines.

**Generative Agents** (Park et al., 2023) — Agents with a memory stream of all observations, a retrieval function weighting recency + importance + relevance, and a *reflection* process that periodically synthesizes higher-level insights from raw memories.

**Collaborative Memory** (Rezazadeh et al., 2025, ICML) — Multi-user, multi-agent memory with access control. Each agent has private + shared memory tiers. Write policies project interactions into structured fragments; read policies construct agent-specific views based on permissions.

**Memory as a Service** (MaaS, 2025) — Decouples memory from agents entirely. Memory Containers package data with access policies; a Memory Routing Layer dispatches queries to the right containers. Enables cross-agent, cross-session memory sharing.

### 1.4 Key Takeaways for TeaParty

1. **Memory is not monolithic.** Multiple types serve different purposes: episodic (what happened), semantic (what I know), procedural (how to do things), working (what I'm thinking about now).
2. **Learning signals are diverse.** Explicit feedback, implicit success/failure, self-reflection, and inter-agent observation all contribute.
3. **Retrieval is as important as storage.** Activation-based retrieval (ACT-R), recency-importance-relevance weighting (generative agents), and embedding similarity all solve the same problem: surfacing the right memory at the right time.
4. **Multi-agent memory needs access control.** Not all agents should see all memories. Shared workgroup knowledge vs. private agent insights.
5. **The LLM context window *is* working memory.** What you put in the prompt determines what the agent can think about.

---

## 2. TeaParty's Current State

### 2.1 Existing Infrastructure

TeaParty already has significant scaffolding for agent learning, though most of it is unused:

**Agent model fields** (`models.py:115-137`):
- `learning_state: JSONDict` — empty, general-purpose learning state
- `sentiment_state: JSONDict` — empty, intended for emotional/sentiment tracking
- `learned_preferences: JSONDict` — empty, intended for user preference learning

**AgentLearningEvent** (`models.py:180-188`):
- Stores discrete learning signals tied to specific messages
- Fields: `agent_id`, `message_id`, `signal_type`, `value` (JSON)
- Not currently written to by any code path

**AgentMemory** (`models.py:191-201`):
- Stores typed memories: "insight", "correction", "pattern", "domain_knowledge"
- Fields: `agent_id`, `conversation_id`, `memory_type`, `content`, `source_summary`, `confidence`
- Not currently written to or read by any code path

### 2.2 Current Agent Cognition Flow

```
User message
    |
    v
agent_runtime.run_agent_auto_responses()
    |
    +--> _agents_for_auto_response()       # Who responds?
    +--> _run_single_agent_responses() OR   # Single agent
         _run_team_response()               # Multi-agent team
             |
             v
         build_agent_json()                 # Build identity prompt
         build_user_message()               # Build conversation history
             |
             v
         run_claude()                       # Shell out to claude CLI
             |
             v
         Store Message, record LLM usage
```

**What agents currently "know":**
- Their identity (name, role, personality, backstory) — from `Agent` record
- The conversation context (kind, name, description) — from `Conversation` record
- Recent conversation history (last 40 messages, max 12K chars) — from `build_user_message()`
- Workflow skills (if matched by name) — from workgroup files
- Teammate roster (if lead in multi-agent mode)

**What agents currently lack:**
- Memory of past conversations
- Knowledge of what worked and what didn't
- Ability to learn user preferences over time
- Cross-conversation knowledge transfer
- Self-reflection on their own performance

### 2.3 Extension Points

The architecture has clean seams where cognitive capabilities can be added:

1. **`build_agent_json()` / `_build_prompt_body()`** — The prompt assembly point. New memory sections can be injected here.
2. **Post-response hook** — After `run_claude()` returns, before the message is committed. Learning extraction can happen here.
3. **`Agent` model JSON fields** — `learning_state`, `sentiment_state`, `learned_preferences` are ready for structured data.
4. **`AgentMemory` and `AgentLearningEvent` tables** — Already defined, waiting for write/read logic.
5. **`AgentTodoItem` trigger system** — Existing proactive agent trigger infrastructure could drive reflection cycles.

---

## 3. Proposed Cognitive Architecture

### 3.1 Design Principles

Following TeaParty's philosophy:

- **Agents are agents** — learning happens autonomously, not through prescriptive rules
- **Advisory, not mandatory** — cognitive systems inform but don't constrain
- **Minimal overhead** — no learning system should add more than ~200ms to response latency
- **Transparent** — all learning state is inspectable and editable by users

### 3.2 Memory System

Mapping CoALA to TeaParty:

```
+-------------------------------------------------------------------+
|                        WORKING MEMORY                              |
|  (context window = system prompt + conversation history + memories) |
+-------------------------------------------------------------------+
         |                    |                    |
         v                    v                    v
+----------------+  +------------------+  +-------------------+
| EPISODIC       |  | SEMANTIC         |  | PROCEDURAL        |
| AgentMemory    |  | AgentMemory      |  | Agent.learning    |
| type=episode   |  | type=insight     |  |   _state          |
|                |  | type=pattern     |  | (skill refs,      |
| Conversation   |  | type=domain      |  |  tool prefs,      |
| summaries,     |  |   _knowledge     |  |  response styles) |
| key moments,   |  |                  |  |                   |
| outcomes       |  | Synthesized      |  | "When asked about |
|                |  | knowledge from   |  |  code, use the    |
| "Last Tuesday  |  | many episodes    |  |  file tools first"|
|  we discussed  |  |                  |  |                   |
|  the API..."   |  | "User prefers    |  |                   |
|                |  |  concise answers"|  |                   |
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

#### 3.2.1 Episodic Memory

**What:** Compressed records of past conversations and significant events.

**Storage:** `AgentMemory` rows with `memory_type = "episode"`

**Contents:**
```json
{
  "content": "Discussed API redesign with user. They wanted REST over GraphQL. We agreed on versioned endpoints. User was satisfied with the v2/resources pattern.",
  "source_summary": "job:API Redesign, 3 messages",
  "confidence": 0.9
}
```

**When created:** At conversation archival, or when a conversation exceeds N messages without a summary. A "cheap" LLM call summarizes the conversation into an episode.

**Retrieval:** By recency (most recent episodes first) and relevance (keyword/semantic match to current conversation topic).

#### 3.2.2 Semantic Memory

**What:** Distilled knowledge — patterns, insights, domain facts — synthesized from multiple episodes.

**Storage:** `AgentMemory` rows with `memory_type` in ("insight", "pattern", "domain_knowledge")

**Contents:**
```json
{
  "memory_type": "pattern",
  "content": "This team prefers TypeScript over JavaScript for new modules.",
  "confidence": 0.85
}
```

**When created:** Periodically via a reflection cycle (see 3.3), or when the agent notices a recurring pattern across episodes.

**Retrieval:** All high-confidence semantic memories relevant to the current context are included in the prompt.

#### 3.2.3 Procedural Memory

**What:** How to do things — preferred tools, response styles, task-specific strategies.

**Storage:** `Agent.learning_state` JSON field (compact, always loaded)

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
  },
  "skill_proficiencies": {
    "python": 0.9,
    "rust": 0.3
  }
}
```

**When updated:** After successful tool use sequences, after user feedback.

**Retrieval:** Always included (lives on the Agent record).

### 3.3 Learning Cycle

Inspired by Soar's perceive-decide-act-learn cycle and Reflexion's verbal RL:

```
            User message arrives
                    |
                    v
        +----------------------+
        |   1. PERCEIVE        |    Retrieve relevant memories
        |   Assemble context   |    for current conversation
        +----------------------+
                    |
                    v
        +----------------------+
        |   2. RESPOND         |    Normal agent response
        |   (existing path)    |    via claude CLI
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
        |   4. LEARN           |    Write AgentLearningEvent,
        |   Update memory      |    update AgentMemory,
        +----------------------+    adjust learning_state
                    |
                    v
        +----------------------+
        |   5. REFLECT         |    Periodic: synthesize
        |   (async, batched)   |    episodes into insights
        +----------------------+
```

#### 3.3.1 Signal Detection (Step 3: OBSERVE)

Learning signals extracted from conversation flow:

| Signal | Detection Method | Example |
|--------|-----------------|---------|
| Explicit praise | Keyword + sentiment | "Great answer!", "Perfect" |
| Explicit correction | Keyword + negation | "Actually, it should be X", "No, I meant..." |
| Task outcome | Conversation archival status | Job completed vs. cancelled |
| User re-engagement | Same topic in new conversation | User asks the same question again |
| Preference expression | Keyword patterns | "I prefer...", "Always use...", "Don't..." |
| Tool success/failure | Tool result analysis | Error in tool_result vs. successful output |

**Implementation:** A lightweight post-response analyzer runs after each agent message. Uses keyword matching first (zero LLM cost), falling back to a cheap LLM call only when ambiguous.

#### 3.3.2 Memory Formation (Step 4: LEARN)

When a signal is detected:
1. Write an `AgentLearningEvent` record (signal_type, value, linked to message)
2. If the signal implies a durable fact: create/update an `AgentMemory` record
3. If the signal implies a procedural change: update `Agent.learning_state`

**Confidence scoring:**
- Single observation: 0.5
- Confirmed by second observation: 0.7
- Contradicted: decrease by 0.2
- Explicitly stated by user ("always do X"): 0.95

#### 3.3.3 Reflection (Step 5: REFLECT)

Inspired by generative agents' reflection process. Runs asynchronously, not on the hot path:

**Trigger:** When an agent accumulates N new learning events since last reflection (default: 10), or on a time schedule via `AgentTodoItem` triggers.

**Process:**
1. Gather recent `AgentLearningEvent` records
2. Gather recent `AgentMemory` episodes
3. Send to cheap LLM: "Given these recent experiences, what patterns, insights, or corrections should I remember?"
4. Store resulting insights as semantic memories
5. Prune low-confidence, old, or contradicted memories

### 3.4 Memory Retrieval for Prompt Assembly

The critical integration point — how memories enter the agent's working memory (context window):

```python
def _build_prompt_body(agent, conversation, workgroup, ...):
    parts = []

    # ... existing identity, context, team roster ...

    # COGNITIVE EXTENSION: inject relevant memories
    memory_block = retrieve_agent_memories(
        agent_id=agent.id,
        conversation=conversation,
        max_tokens=800,  # budget for memory in prompt
    )
    if memory_block:
        parts.append("")
        parts.append(memory_block)

    # ... existing guidelines ...
```

The retrieval function:
1. Loads `Agent.learning_state` (procedural memory — always included, compact)
2. Queries `AgentMemory` for relevant semantic memories (high confidence, keyword match)
3. Queries `AgentMemory` for recent episodic memories (if same topic/participants)
4. Formats into a natural-language block, budget-constrained

**Example prompt injection:**
```
From your experience:
- This team prefers TypeScript for new modules (high confidence)
- User tends to ask for examples alongside explanations
- Previous conversation on this topic: discussed REST vs GraphQL, agreed on versioned endpoints
```

### 3.5 Multi-Agent Learning

In team sessions, agents can learn from observing each other:

**Shared workgroup knowledge:** Semantic memories with `memory_type = "domain_knowledge"` are shared across all agents in a workgroup. When one agent learns a domain fact, all agents in the workgroup can access it.

**Private agent memories:** Insights, corrections, and patterns are private to each agent unless explicitly promoted to shared.

**Team reflection:** After a multi-agent job completes, a reflection cycle runs for each participating agent, with access to the full conversation (not just their own contributions).

---

## 4. API Implications

### 4.1 New Endpoints

```
# Memory CRUD
GET    /api/agents/{agent_id}/memories                  # List memories with filters
POST   /api/agents/{agent_id}/memories                  # Manually create a memory
PATCH  /api/agents/{agent_id}/memories/{memory_id}      # Edit memory content/confidence
DELETE /api/agents/{agent_id}/memories/{memory_id}      # Remove a memory

# Learning events (read-only audit trail)
GET    /api/agents/{agent_id}/learning-events            # List learning signals

# Learning state (procedural memory)
GET    /api/agents/{agent_id}/learning-state             # Current learning state
PATCH  /api/agents/{agent_id}/learning-state             # Manual adjustment

# Reflection trigger
POST   /api/agents/{agent_id}/reflect                    # Trigger reflection cycle

# Workgroup shared knowledge
GET    /api/workgroups/{wg_id}/knowledge                 # Shared knowledge base
POST   /api/workgroups/{wg_id}/knowledge                 # Add shared knowledge
```

### 4.2 Modified Endpoints

```
# Existing agent endpoint — add memory stats to response
GET    /api/agents/{agent_id}
  + memory_count: int
  + last_reflection_at: datetime | null
  + learning_event_count: int

# Existing conversation archive — trigger episode creation
POST   /api/conversations/{conv_id}/archive
  + (side effect) Creates episodic memory for participating agents
```

### 4.3 Database Changes

**New columns on `Agent`:**
```python
last_reflection_at: datetime | None = Field(default=None)
memory_budget_tokens: int = Field(default=800)  # max tokens for memory in prompt
```

**New index on `AgentMemory`:**
```python
# For efficient retrieval by agent + type + confidence
Index("ix_agent_memory_retrieval", "agent_id", "memory_type", "confidence")
```

**New columns on `AgentMemory`:**
```python
access_scope: str = Field(default="private")  # "private" | "workgroup"
last_accessed_at: datetime | None = Field(default=None)  # for activation decay
access_count: int = Field(default=0)  # for activation strengthening
```

### 4.4 Service Layer Changes

**New service: `teaparty_app/services/agent_memory.py`**
```
retrieve_agent_memories(agent_id, conversation, max_tokens) -> str
store_learning_event(agent_id, message_id, signal_type, value) -> AgentLearningEvent
create_memory(agent_id, conversation_id, memory_type, content, ...) -> AgentMemory
run_reflection(agent_id) -> list[AgentMemory]
detect_learning_signals(agent_id, message, conversation) -> list[dict]
```

**Modified service: `agent_definition.py`**
- `_build_prompt_body()` gains a memory retrieval call

**Modified service: `agent_runtime.py`**
- Post-response: call `detect_learning_signals()` and `store_learning_event()`
- On conversation archive: call `create_memory()` for episodic summary

---

## 5. Implementation Phases

### Phase 1: Memory Retrieval (read path)
- Implement `retrieve_agent_memories()`
- Inject memory block into `_build_prompt_body()`
- Add memory CRUD endpoints
- Allow manual memory creation via admin workspace

This is immediately useful — humans can seed agent memories manually.

### Phase 2: Signal Detection (observation)
- Implement `detect_learning_signals()` with keyword-based detection
- Write `AgentLearningEvent` records after each agent response
- Surface learning events in the admin UI

### Phase 3: Automatic Memory Formation
- Convert learning events into `AgentMemory` records
- Implement confidence scoring and deduplication
- Episodic memory creation on conversation archive

### Phase 4: Reflection Cycle
- Implement `run_reflection()` using cheap LLM
- Wire into `AgentTodoItem` trigger system for periodic reflection
- Memory pruning and consolidation

### Phase 5: Multi-Agent Knowledge Sharing
- Implement workgroup-scoped memories
- Team reflection after multi-agent jobs
- Knowledge promotion (private → shared)

---

## 6. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Memory pollution (wrong/outdated memories) | Agent gives bad advice | Confidence decay over time; user can edit/delete memories; reflection cycle prunes |
| Prompt bloat (too many memories) | Slower responses, higher cost | Token budget cap (`memory_budget_tokens`); retrieval scoring |
| Privacy leakage (cross-user memories) | Security concern | Memories scoped to agent + workgroup; access_scope field; no cross-workgroup sharing |
| Hallucinated learning signals | False pattern detection | Conservative keyword matching first; require multiple observations for high confidence |
| Reflection cost | LLM cost for reflection cycles | Use cheap model; batch reflections; rate-limit |

---

## 7. References

### Classical Cognitive Architectures
- Anderson, J.R. (2007). *How Can the Human Mind Occur in the Physical Universe?* Oxford University Press. (ACT-R)
- Laird, J.E. (2012). *The Soar Cognitive Architecture.* MIT Press. (Soar)
- Franklin, S. et al. (2016). "LIDA: A Systems-level Architecture for Cognition, Emotion, and Learning." (LIDA)

### LLM Agent Architectures
- [Sumers et al. (2024). "Cognitive Architectures for Language Agents." TMLR.](https://arxiv.org/abs/2309.02427) (CoALA)
- [Packer et al. (2023). "MemGPT: Towards LLMs as Operating Systems."](https://arxiv.org/abs/2310.08560)
- [Shinn et al. (2023). "Reflexion: Language Agents with Verbal Reinforcement Learning."](https://arxiv.org/abs/2303.11366)
- [Wang et al. (2023). "Voyager: An Open-Ended Embodied Agent with Large Language Models."](https://arxiv.org/abs/2305.16291)
- [Park et al. (2023). "Generative Agents: Interactive Simulacra of Human Behavior."](https://arxiv.org/abs/2304.03442)

### Multi-Agent Memory
- [Rezazadeh et al. (2025). "Collaborative Memory: Multi-User Memory Sharing in LLM Agents." ICML.](https://arxiv.org/abs/2505.18279)
- [Memory as a Service (MaaS, 2025).](https://arxiv.org/html/2506.22815v1)

### Integration Research
- [Wang et al. (2024). "Cognitive LLMs: Towards Integrating Cognitive Architectures and Large Language Models."](https://arxiv.org/pdf/2408.09176)
- [Rosenbloom et al. (2025). "Applying Cognitive Design Patterns to General LLM Agents."](https://arxiv.org/html/2505.07087v2)

### Frameworks
- [Letta (MemGPT)](https://github.com/letta-ai/letta) — Stateful agent platform with tiered memory
- [LangGraph](https://www.langchain.com/langgraph) — Agent orchestration with persistence
- [DSPy](https://dspy.ai/) — Declarative prompting and optimization