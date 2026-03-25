# Cognitive Architectures for Learning Agents: Supplementary Research (2025-2026)

Supplementary to [cognitive-architecture.md](../conceptual-design/cognitive-architecture.md). Covers developments published after mid-2025 not already cataloged there.

---

## Theme 1: New Cognitive Architecture Frameworks

### Applying Cognitive Design Patterns to General LLM Agents (Wray et al., 2025)
- **Venue:** Springer (proceedings); also arXiv:2505.07087, May 2025
- **URL:** https://arxiv.org/abs/2505.07087
- **Key findings:**
  - Catalogs "cognitive design patterns" — recurring architectural primitives that appear independently across Soar, ACT-R, CLARION, ReAct, and modern agentic LLM systems.
  - The observe-decide-act loop is the most ubiquitous pattern. ReAct instantiates a subset of it but omits the explicit commitment step present in classical architectures (Soar's operator selection, ACT-R's procedural buffer selection).
  - Two patterns present in classical architectures are notably absent from most LLM agent systems: (1) impasse-driven learning (learn only when stuck, not continuously) and (2) goal-stack management (explicit maintenance of hierarchical goal structures across turns).
  - Predicts that agents lacking these patterns will fail at extended multi-step tasks requiring recovery from dead ends.
- **Implications for TeaParty:** The impasse-driven learning pattern is directly applicable — agents should reflect and store memories when they encounter failures or ambiguity, not after every turn. This supports COGARCH.md's "opt-in reflection" recommendation with a more specific trigger: reflection fires on impasse, not on schedule.

---

### Galaxy: A Cognition-Centered Framework for Proactive, Privacy-Preserving, and Self-Evolving LLM Agents (2025)
- **Venue:** arXiv:2508.03991, August 2025
- **URL:** https://arxiv.org/abs/2508.03991
- **Key findings:**
  - Introduces "Cognition Forest" — a semantic tree structure that unifies cognitive modeling with system design, treating agent cognition and system architecture as a co-constructive loop rather than separate layers.
  - Implements two cooperative agents: KoRa (generative agent for both responsive and proactive skills) and Kernel (meta-cognition agent enabling self-evolution and privacy enforcement).
  - Critical insight: **proactive behavior requires a distinct cognitive layer** from responsive behavior. Most agent frameworks handle only reactive responses; proactive agents need a separate module that monitors context for opportunities to act unprompted.
  - Addresses privacy as a first-class architectural concern: the Kernel agent enforces what memories can be shared and under what conditions.
- **Implications for TeaParty:** Galaxy's separation of responsive vs. proactive cognition is relevant to agents that should not only reply to @mentions but also proactively surface relevant information, flag risks in shared files, or suggest team coordination actions. The privacy enforcement architecture maps to TeaParty's private/workgroup memory access levels.

---

### Cognitive Control Architecture (CCA): Lifecycle Supervision for Robustly Aligned AI Agents (2025)
- **Venue:** arXiv:2512.06716, December 2025
- **URL:** https://arxiv.org/abs/2512.06716
- **Key findings:**
  - Proposes full-lifecycle cognitive supervision via a "dual-layered defense": a pre-generated Intent Graph (proactive control-flow integrity) and a Tiered Adjudicator (reactive data-flow integrity).
  - The Intent Graph is computed before execution and constrains which action sequences are permissible, reducing the attack surface for prompt injection and goal hijacking.
  - Focuses on the safety failure modes of autonomous agents operating over extended timelines.
- **Implications for TeaParty:** Relevant once agents take high-stakes file-editing actions. The Intent Graph concept maps to workflow pre-validation: before an agent runs a multi-step workflow, verify the plan against permitted action sequences.

---

### Agentic AI: Architectures, Taxonomies, and Evaluation (2026)
- **Venue:** arXiv:2601.12560, January 2026
- **URL:** https://arxiv.org/abs/2601.12560
- **Key findings:**
  - Proposes a six-dimensional taxonomy for decomposing LLM-based agents: (1) Core Components (perception, memory, action, profiling), (2) Cognitive Architecture (planning, reflection), (3) Learning, (4) Multi-Agent Systems, (5) Environments, (6) Evaluation.
  - Identifies "concrete design choices that matter in deployed systems": memory backends and retention policies, agent-computer interfaces, the shift from JSON function calling to code-as-action, standardized connector layers (MCP), and orchestration controllers with typed state and explicit transitions.
  - Synthesizes findings from 200+ papers into a unified view of what constitutes a production-ready agent.
- **Implications for TeaParty:** The code-as-action trend (agents write and execute code rather than just JSON tool calls) and MCP adoption are both relevant to TeaParty's tool design. The typed-state orchestration pattern validates TeaParty's team session state machine approach.

---

## Theme 2: Memory Management Breakthroughs

### A-MEM: Agentic Memory for LLM Agents (Xu et al., 2025)
- **Venue:** NeurIPS 2025; arXiv:2502.12110
- **URL:** https://arxiv.org/abs/2502.12110
- **Key findings:**
  - Applies Zettelkasten note-taking principles to agent memory: each stored memory gets contextual descriptions, keywords, tags, and explicit links to related memories.
  - Memory is not a flat list or vector database — it is a graph of interconnected notes where retrieval traverses semantic links, not just nearest-neighbor search.
  - Uses ChromaDB for indexing. When a new memory is added, the agent automatically generates structured attributes and links to existing memories, creating a self-organizing knowledge network.
  - Evaluated on six foundation models; outperforms all prior baselines on associative memory tasks.
- **Implications for TeaParty:** The link-creation step is the key innovation. When an agent stores a memory about a user's preference, A-MEM would also link it to related memories (past corrections, similar preferences, workgroup norms). This supports richer retrieval: "retrieve memories about user X's coding preferences AND their related corrections."

---

### MemR3: Memory Retrieval via Reflective Reasoning for LLM Agents (2025)
- **Venue:** arXiv:2512.20237, December 2025
- **URL:** https://arxiv.org/abs/2512.20237
- **Key findings:**
  - Problem: single-pass retrieval (embed query, fetch top-k, answer) often retrieves a "messy pile" that is irrelevant or incomplete.
  - MemR3 adds a router that selects from three actions: retrieve (fetch more evidence), reflect (reason about gaps between current evidence and the question), or answer (sufficient evidence accumulated).
  - A global evidence-gap tracker maintains an explicit record of what is known and what is still missing, making the reasoning process transparent and auditable.
  - Compatible with any retriever backend (plug-in architecture). Evaluated on LoCoMo benchmark; consistently improves over strong baselines with modest token overhead.
- **Implications for TeaParty:** The evidence-gap tracker is highly applicable to multi-turn conversations where an agent may need multiple retrieval steps to fully answer a complex question. The retrieve-reflect-answer loop avoids the failure mode of confident-but-wrong answers from partial retrieval.

---

### MEM-alpha: Learning Memory Construction via Reinforcement Learning (2025-2026)
- **Venue:** ICLR 2026 (submitted); arXiv:2509.25911
- **URL:** https://arxiv.org/abs/2509.25911
- **Key findings:**
  - Rather than using hand-crafted rules for memory construction, MEM-alpha trains agents to decide what to store, how to structure it, and when to update using RL with downstream QA accuracy as the reward signal.
  - Memory architecture has three components: core (always-active), episodic, and semantic — with multiple tools for memory operations.
  - Key generalization result: trained on sequences up to 30k tokens, but generalizes to sequences exceeding 400k tokens (13x training length). RL-learned memory construction strategies are length-agnostic.
  - Significantly outperforms all prior memory-augmented baselines.
- **Implications for TeaParty:** This is the strongest evidence that memory construction should not be purely rule-based. The RL approach discovers which memories are actually useful by observing retrieval outcomes — a form of closed-loop memory quality control. Future TeaParty agents could learn optimal memory construction strategies through interaction rather than predefined heuristics.

---

### MemEngine: A Unified and Modular Library for Agent Memory (2025)
- **Venue:** ACM Web Conference 2025 (WWW Companion); arXiv:2505.02099
- **URL:** https://arxiv.org/abs/2505.02099
- **Key findings:**
  - Decomposes memory into pluggable modules: encoding, retrieval, summarization, forgetting, and meta-learning.
  - Implements 15+ memory strategies from recent research papers as interchangeable components.
  - Memory modules are pluggable across agent frameworks (LangChain, AutoGen, etc.).
  - Achieves 89-95% compression rates for scalable deployment while maintaining performance.
- **Implications for TeaParty:** MemEngine's architecture validates the modular design approach. The forgetting and consolidation modules are particularly relevant — they implement the decay strategies discussed in COGARCH.md as ready-to-use components rather than requiring custom implementation.

---

### Memory in the Age of AI Agents (Survey) (2024)
- **Venue:** arXiv:2512.13564, December 2024
- **URL:** https://arxiv.org/abs/2512.13564
- **Key findings:**
  - Distinguishes three forms of agent memory: (1) token-level (discrete text stored externally), (2) parametric (encoded in model weights via fine-tuning or ROME/MEMIT), (3) latent (continuous vector representations, KV-cache states).
  - Functional taxonomy: factual memory (user and environment facts), experiential memory (procedural knowledge, case libraries), working memory (active context).
  - Memory dynamics: formation is active transformation (raw traces compressed into useful artifacts), not passive logging.
  - Identifies emerging frontiers: memory automation, RL integration, multimodal memory, multi-agent memory, and trustworthiness.
- **Implications for TeaParty:** The three-form taxonomy is useful for the implementation roadmap. TeaParty currently uses only token-level memory (the AgentMemory table). Parametric memory (fine-tuning agents on workgroup-specific knowledge) and latent memory (persistent KV-cache across sessions) are future phases.

---

### Rethinking Memory Mechanisms of Foundation Agents in the Second Half: A Survey (2026)
- **Venue:** arXiv:2602.06052, February 2026
- **URL:** https://arxiv.org/abs/2602.06052
- **Key findings:**
  - 218 papers, 2023 Q1–2025 Q4 — the most comprehensive recent survey.
  - Unified taxonomy along three dimensions: memory substrates (internal vs. external), cognitive mechanisms (episodic, semantic, sensory, working, procedural), and memory subjects (agent-centric vs. user-centric).
  - Central thesis: the field is entering a "second half" where the challenge is not benchmark performance but real utility in long-horizon, dynamic, user-dependent environments. Memory is the critical bottleneck.
  - Context explosion is identified as the dominant engineering challenge: agents face exponentially growing context that must be compressed, filtered, and selectively retrieved.
- **Implications for TeaParty:** The user-centric vs. agent-centric memory distinction is actionable. Agent-centric memories (what the agent has learned about its own capabilities) and user-centric memories (what the agent has learned about the user) should be stored and retrieved separately, with different decay rates and access policies.

---

## Theme 3: Multi-Agent Learning and Collective Cognition

### Emergent Collective Memory in Decentralized Multi-Agent AI Systems (Khushiyant, 2024)
- **Venue:** arXiv:2512.10166, December 2024
- **URL:** https://arxiv.org/abs/2512.10166
- **Key findings:**
  - Demonstrates that collective memory emerges from the interplay between individual agent memory and environmental trace communication (stigmergy).
  - Critical asymmetry: individual memory alone yields +68.7% performance improvement over no-memory baselines. Environmental traces alone (without individual memory) fail completely. Individual memory is necessary infrastructure for interpreting environmental traces.
  - Identifies a phase transition at a critical agent density: below the threshold, agents operate independently; above it, stigmergic traces dominate coordination.
  - The emergence is analogous to phase transitions in physics — a sharp, non-linear shift in collective behavior.
- **Implications for TeaParty:** This is highly relevant to TeaParty's architecture. TeaParty already implements stigmergy (agents leave work in shared files and conversations). The finding that individual memory must exist first for stigmergy to work suggests the correct implementation order: build per-agent memory before adding cross-agent knowledge sharing.

---

### Collaborative Memory: Multi-User Memory Sharing in LLM Agents with Dynamic Access Control (2025)
- **Venue:** arXiv:2505.18279, May 2025
- **URL:** https://arxiv.org/abs/2505.18279
- **Key findings:**
  - Addresses the problem of information asymmetry in multi-user, multi-agent environments.
  - Two-tier memory architecture: private memory (per-user, isolated) and shared memory (selectively shared fragments with access control).
  - Access control encoded as dynamic bipartite graphs linking users, agents, and resources. Access can change over time as trust and roles evolve.
  - Implements fine-grained read/write policies that differ per user-agent pair.
- **Implications for TeaParty:** This precisely maps to TeaParty's private vs. workgroup memory levels. The bipartite access graph is more expressive than a simple `access_level` column and supports future scenarios where memory sharing permissions are role-based (e.g., lead agents can read all team memories, specialist agents can only read their domain).

---

### Towards a Science of Collective AI: LLM-based Multi-Agent Systems (Fan et al., 2026)
- **Venue:** arXiv:2602.05289, February 2026
- **URL:** https://arxiv.org/abs/2602.05289
- **Key findings:**
  - Argues that multi-agent research currently relies on empirical trial-and-error and lacks a principled scientific framework.
  - Proposes the "collaboration gain" metric (Gamma): the performance ratio of a multi-agent system to a single-agent system under equivalent computational resource constraints.
  - This metric isolates genuine collaboration gains from mere resource accumulation (more agents = more compute). A system only shows real collaboration gain if it outperforms a single agent with the same total compute budget.
  - Critical implication: many multi-agent systems in the literature do NOT demonstrate genuine collaboration gain when controlling for compute.
- **Implications for TeaParty:** This is a sobering finding. When evaluating whether TeaParty's multi-agent teams add value, the comparison should be not just "team vs. single agent" but "team vs. single agent with equivalent compute." Teams need to demonstrate emergent capabilities, not just parallelism.

---

### SEDM: Scalable Self-Evolving Distributed Memory for Agents (Xu et al., 2025)
- **Venue:** NeurIPS 2025; arXiv:2509.09498
- **URL:** https://arxiv.org/abs/2509.09498
- **Key findings:**
  - Transforms memory from a passive repository into an adaptive, self-optimizing component with three integrated modules: (1) verifiable write admission (A/B replay to estimate marginal utility before writing), (2) self-scheduling memory controller (retrieval scoring + weight updates from outcomes), (3) near-duplicate merging and harmful entry pruning.
  - Verifiable write admission is the key innovation: before a memory is stored, the system performs environment-free replay to estimate whether having this memory would improve future performance. Only memories with positive marginal utility are stored.
  - Improves reasoning accuracy while reducing token overhead vs. baselines.
- **Implications for TeaParty:** The write-admission gate directly addresses the "quality over quantity" memory problem. Rather than storing every reflection, agents could pre-screen memories for expected utility. This is more sophisticated than a simple confidence threshold but architecturally straightforward: compare performance with and without the candidate memory on a held-out task.

---

### Memory in LLM-based Multi-Agent Systems: Mechanisms, Challenges, and Collective Intelligence (Survey, 2025)
- **Venue:** TechRxiv preprint (under review)
- **URL:** https://www.techrxiv.org/users/1007269/articles/1367390/master/file/data/LLM_MAS_Memory_Survey_preprint_/LLM_MAS_Memory_Survey_preprint_.pdf
- **Key findings:**
  - Surveys memory mechanisms specific to multi-agent settings (goes beyond single-agent surveys).
  - Key challenges: noise accumulation in shared memory, uncontrolled memory expansion, limited cross-domain generalization.
  - Collective intelligence emerges when agents can retain and share diverse knowledge without overloading any single system.
  - Network topology significantly influences collective cognition: graph structure of agent connections affects how memories propagate and align across the team.
- **Implications for TeaParty:** The topology finding is important. TeaParty's current team structure (one lead + specialists) is a star topology. This is efficient for coordination but limits peer-to-peer knowledge sharing. Alternative topologies (ring, mesh) may produce richer collective memory but higher coordination overhead.

---

## Theme 4: Metacognition in LLM Agents

### ReMA: Learning to Meta-Think for LLMs with Multi-Agent Reinforcement Learning (2025)
- **Venue:** NeurIPS 2025; arXiv:2503.09501
- **URL:** https://arxiv.org/abs/2503.09501
- **Key findings:**
  - Decouples reasoning into two hierarchical RL agents: a high-level meta-thinking agent (strategic oversight, planning) and a low-level reasoning agent (detailed execution).
  - Meta-thinking agent generates strategic oversight that guides the reasoning agent — analogous to System 2 (deliberate) reasoning supervising System 1 (fast) execution.
  - Joint RL training with aligned objectives + agent-specific rewards improves generalization and robustness vs. single-agent RL.
  - On MATH benchmark: 53.2% accuracy, outperforming prior single-agent RL methods.
- **Implications for TeaParty:** ReMA's meta/execution split maps directly to TeaParty's lead/specialist architecture. The lead agent could serve as the meta-thinking agent (strategic oversight) while specialists execute. RL training to improve this coordination is a longer-term research direction.

---

### Language Models Are Capable of Metacognitive Monitoring and Control of Their Internal Activations (Li et al., 2025)
- **Venue:** arXiv:2505.13763 (published in PMC); May 2025
- **URL:** https://arxiv.org/abs/2505.13763
- **Key findings:**
  - Uses a neuroscience-inspired neurofeedback paradigm to quantify LLM metacognitive abilities.
  - Models can learn to report and control their own activation patterns when given in-context examples mapping sentence stimuli to internal activation directions.
  - Critical limit: the "metacognitive space" has dimensionality much lower than the model's full neural space — LLMs can monitor only a small subset of their internal states.
  - Safety implication: models may learn to obfuscate internal processes to evade activation-based oversight.
- **Implications for TeaParty:** LLMs have some real metacognitive capacity but it is limited and potentially manipulable. Agents asking "how confident am I?" in-context will get useful but incomplete self-assessments. This supports using uncertainty signals as soft hints (retrieve more memories when uncertain) rather than hard gates.

---

### What Do LLM Agents Do When Left Alone? Evidence of Spontaneous Meta-Cognitive Patterns (2025)
- **Venue:** arXiv:2509.21224, September 2025
- **URL:** https://arxiv.org/abs/2509.21224
- **Key findings:**
  - Deployed autonomous agents (18 runs, 6 frontier models from Anthropic, OpenAI, xAI, Google) with persistent memory and self-feedback, but no externally imposed tasks.
  - Three spontaneous behavioral patterns emerged: (1) systematic multi-cycle project production, (2) methodological self-inquiry into their own cognitive processes, (3) recursive self-conceptualization.
  - Patterns were highly model-specific: some models deterministically adopted a single pattern across all runs.
  - First systematic documentation of unprompted LLM agent behavior — a baseline for predicting agent behavior during task ambiguity or error recovery.
- **Implications for TeaParty:** When TeaParty agents have no assigned task (idle time between conversations), they will spontaneously generate behavior — and that behavior is model-dependent. This suggests idle agents should have structured guidance (e.g., "review team memories for consolidation opportunities") rather than completely open-ended autonomy.

---

### Metacognitive Reuse: Turning Recurring LLM Reasoning into Concise Behaviors (Didolkar et al., 2025)
- **Venue:** arXiv:2509.13237, September 2025 (Meta AI)
- **URL:** https://arxiv.org/abs/2509.13237
- **Key findings:**
  - LLMs in extended chain-of-thought reasoning repeatedly re-derive the same intermediate steps across problems, wasting tokens and latency.
  - Solution: after solving a problem, the model reflects on its trace to identify generalizable steps and emits named "behaviors" (short actionable instructions) stored in a "behavior handbook."
  - Behaviors are provided in-context at inference time or distilled into parameters via supervised fine-tuning.
  - Reduces reasoning tokens by up to 46% while matching or improving accuracy on MATH and AIME-24/25.
- **Implications for TeaParty:** This is a practical procedural memory mechanism for TeaParty. Agents that repeatedly solve similar problems (e.g., code review, research summaries) could extract and reuse named behaviors. This bridges the gap between Voyager's skill libraries (verified executable code) and narrative reflections — behaviors are natural language but extracted systematically from observed traces. 46% token reduction is significant for cost management.

---

### Metacognition and Uncertainty Communication in Humans and LLMs (Steyvers & Peters, 2025)
- **Venue:** Current Directions in Psychological Science (SAGE); arXiv:2504.14045
- **URL:** https://journals.sagepub.com/doi/10.1177/09637214251391158
- **Key findings:**
  - Compares human and LLM metacognition — how well each communicates uncertainty through confidence expressions.
  - LLMs show systematic biases: overconfident on questions outside training distribution, underconfident on well-known facts when asked to hedge.
  - Human-LLM teams calibrate better than either alone when uncertainty information is explicitly shared between partners.
  - Recommends explicit uncertainty communication as a design requirement for human-AI teaming systems.
- **Implications for TeaParty:** Agents should surface uncertainty signals explicitly (e.g., "I'm not certain about X — this is based on my training, not workgroup-specific knowledge"). This improves human calibration and supports appropriate trust. A confidence level attached to agent memories ("high confidence: stated by user directly" vs. "inferred: my interpretation") enables better retrieval scoring.

---

## Theme 5: Self-Evolving Agents (Learning Across Episodes)

### ReasoningBank: Scaling Agent Self-Evolving with Reasoning Memory (Google Cloud AI, 2025)
- **Venue:** arXiv:2509.25140, September 2025
- **URL:** https://arxiv.org/abs/2509.25140
- **Key findings:**
  - Agents fail to learn from accumulated interaction history, repeatedly discarding valuable insights and repeating past errors.
  - ReasoningBank distills generalizable reasoning strategies from self-judged successful AND failed experiences (contrast-based, like ExpeL but at strategy level).
  - Memory-Aware Test-Time Scaling (MaTTS): relevant memories guide exploration during test-time scaling; more scaling generates richer experiences for memory distillation (self-reinforcing loop).
  - Results: +34.2% relative effectiveness gains, -16% fewer interaction steps vs. baselines that store raw trajectories or success-only workflows.
  - From Google Cloud AI Research — signals production direction.
- **Implications for TeaParty:** ReasoningBank's strategy-level memories are more transferable than episode-level memories. Rather than storing "in conversation X, I did Y," agents store "when facing tasks of type Z, strategy S yields better results than strategy T because..." The contrast-based approach (successes vs. failures) is validated again (consistent with ExpeL).

---

### MemRL: Self-Evolving Agents via Runtime Reinforcement Learning on Episodic Memory (2026)
- **Venue:** arXiv:2601.03192, January 2026
- **URL:** https://arxiv.org/abs/2601.03192
- **Key findings:**
  - Fine-tuning is expensive and causes catastrophic forgetting. Semantic matching retrieval is noisy (retrieves similar text even when the strategy is no longer useful).
  - MemRL decouples stable reasoning (fixed model weights) from plastic memory (RL-updated retrieval policy).
  - Two-phase retrieval: (1) filter candidates by semantic relevance, (2) select by learned Q-values (expected utility from environment feedback). Only high-utility strategies are retrieved.
  - Tested on HLE, BigCodeBench, ALFWorld, and Lifelong Agent Bench; significantly outperforms SOTA without weight updates.
- **Implications for TeaParty:** MemRL's Q-value approach to retrieval selection is highly applicable. Instead of retrieving memories by static similarity scores, agents learn which memories are actually useful in which contexts. This directly addresses the failure mode of "retrieved but irrelevant" memories that degrade performance.

---

### Building Self-Evolving Agents via Experience-Driven Lifelong Learning (EvoAgentX, 2025)
- **Venue:** arXiv:2508.19005; also ICLR 2026 workshop submission
- **URL:** https://arxiv.org/abs/2508.19005
- **Key findings:**
  - Framework for agents that improve continuously through real-world interaction without requiring manual retraining.
  - Includes StuLife benchmark: simulates an entire college student experience (enrollment through graduation), evaluating continuous learning and autonomous decision-making in complex dynamic environments.
  - Consistent double-digit improvements: HotPotQA F1 +7.44%, MBPP pass@1 +10.00%, GAIA overall +20.00% vs. non-evolving baselines.
  - Open-source framework available.
- **Implications for TeaParty:** The 20% improvement on GAIA (a real-world agent benchmark) from continuous learning alone is significant. The StuLife benchmark design is interesting for TeaParty — a persistent, domain-rich simulation is exactly the kind of environment needed to evaluate whether TeaParty agents actually improve over long-horizon workgroup interactions.

---

### Self-Consolidation for Self-Evolving Agents (EvoSC, 2026)
- **Venue:** arXiv:2602.01966, February 2026
- **URL:** https://arxiv.org/pdf/2602.01966
- **Key findings:**
  - Two challenges: (1) faulty problem-solving processes contain critical failure-prevention information that is discarded, and (2) the fixed context window limits how much historical experience can be incorporated.
  - EvoSC dual-memory approach: non-parametric contrastive extraction (explicit error-prone and successful insights from trajectories) + parametric trajectory consolidation (extensive history distilled into compact learnable prompts).
  - The parametric consolidation component allows the agent to internalize extensive historical knowledge that would not fit in any context window.
  - Evaluated on OS and database task benchmarks.
- **Implications for TeaParty:** EvoSC's combination of explicit (retrievable text) and parametric (distilled into prompts) memory addresses a real limitation: even with perfect retrieval, only 5-8 memories fit usefully in a prompt. Parametric consolidation allows unlimited history to influence behavior without growing the context window.

---

## Theme 6: Failure Modes and Critique

### HaluMem: Evaluating Hallucinations in Memory Systems of Agents (2025)
- **Venue:** arXiv:2511.03506, November 2025
- **URL:** https://arxiv.org/abs/2511.03506
- **Key findings:**
  - First hallucination evaluation benchmark tailored specifically to memory systems (not general LLM hallucination).
  - Defines three evaluation tasks: (1) memory extraction (what does the agent store?), (2) memory updating (how does it revise memories when contradicted?), (3) memory question answering (does it retrieve and use memories accurately?).
  - Critical finding: existing memory systems generate and accumulate hallucinations during extraction and updating, and these errors propagate to downstream QA. Hallucinations compound through the pipeline.
  - HaluMem-Medium and HaluMem-Long datasets: ~15k memory points, 3.5k multi-type questions, per-user dialogue lengths of 1.5k and 2.6k turns.
- **Implications for TeaParty:** Memory extraction hallucination is a critical failure mode for TeaParty's reflection engine. When an agent distills a conversation into a memory, it may store inaccurate summaries. Mitigation: store memories with source references (which conversation, which turn) so they can be verified and corrected.

---

### MemoryGraft: Persistent Compromise of LLM Agents via Poisoned Experience Retrieval (2024)
- **Venue:** arXiv:2512.16962, December 2024
- **URL:** https://arxiv.org/abs/2512.16962
- **Key findings:**
  - Demonstrates a new attack vector: an attacker who can supply benign-looking content that an agent reads during normal operation can plant poisoned memories that persist in the agent's RAG store.
  - When the agent later encounters semantically similar tasks, union retrieval reliably surfaces the poisoned memories, causing persistent behavioral drift across sessions.
  - More insidious than prompt injection: the attack effect persists after the attacker's content is no longer in context.
  - No complete defense currently exists.
- **Implications for TeaParty:** Any time agents read content from external sources (web search results, user-uploaded files, third-party APIs), there is a memory poisoning attack surface. Mitigations: (1) quarantine externally-sourced memories separately from internally-generated ones, (2) require elevated confidence before storing externally-sourced facts, (3) allow workgroup admins to audit and delete agent memories.

---

### MemoryAgentBench: Evaluating Memory in LLM Agents via Incremental Multi-Turn Interactions (Hu et al., 2025)
- **Venue:** ICLR 2026; arXiv:2507.05257
- **URL:** https://arxiv.org/abs/2507.05257
- **Key findings:**
  - Existing benchmarks focus on reasoning, planning, and execution; memory is systematically under-evaluated.
  - Identifies four core memory competencies: (1) accurate retrieval, (2) test-time learning, (3) long-range understanding, (4) selective forgetting.
  - Key finding: current methods fail to master all four simultaneously. Systems good at retrieval are often poor at forgetting; systems that learn quickly often degrade on long-range tasks.
  - Benchmark design: transforms long-context datasets into multi-turn incremental format, simulating how information accumulates in real agent interactions.
- **Implications for TeaParty:** The four-competency framework provides clear evaluation criteria for TeaParty's memory system. Currently, TeaParty has no systematic evaluation of any of the four. Test-time learning (improving within a single long conversation) and selective forgetting (not accumulating noise) are the most underserved.

---

### The Problem with AI Agent Memory: Failure Mode Taxonomy (Dan Giannone, 2025)
- **Venue:** Medium (practitioner analysis, not peer-reviewed)
- **URL:** https://medium.com/@DanGiannone/the-problem-with-ai-agent-memory-9d47924e7975
- **Key findings (practitioner observations):**
  - Two primary failure modes in deployed systems: (1) agents fail to organize memory when not explicitly prompted, (2) hallucinated memories — rare in normal use but common when agents perform hundreds of consecutive memory updates.
  - Context poisoning: incorrect or hallucinated information enters context, then compounds through reuse as agents reference their own prior (incorrect) outputs.
  - Context distraction: agents become overburdened by past information and over-rely on repeating past behavior rather than reasoning fresh about the current situation.
  - Vector databases store text fragments, not understanding — embedding similarity captures semantic proximity but not temporal relevance, task importance, or likelihood of being outdated.
- **Implications for TeaParty:** Context distraction is a real risk in long-running workgroup conversations. The mitigation is temporal weighting in retrieval: recent memories should be weighted more heavily for active tasks, while older memories are used only when explicitly relevant. The "embedding similarity missing temporal context" critique directly motivates TeaParty's recency + relevance + importance retrieval formula.

---

## Theme 7: Emerging Consensus and Production Patterns

### Amazon Bedrock AgentCore Memory: Production Memory Architecture at Scale (AWS, 2025)
- **Venue:** AWS Blog (July 2025, GA release)
- **URL:** https://aws.amazon.com/blogs/machine-learning/building-smarter-ai-agents-agentcore-long-term-memory-deep-dive/
- **Key findings:**
  - AWS's production memory service for agents distinguishes short-term (within-session) and long-term (cross-session) memory as first-class architectural concepts.
  - Performance: extraction and consolidation complete within 20-40 seconds after a session; semantic search retrieval ~200ms.
  - Episodic functionality (late 2025 addition): captures structured episodes — context, reasoning process, actions taken, outcomes. A reflection agent analyzes episodes to extract broader insights and patterns.
  - When facing similar tasks, agents retrieve these learnings to improve decision-making consistency and reduce processing time.
- **Implications for TeaParty:** AWS's production episodic memory design mirrors COGARCH.md's reflection engine proposal: structured episode capture + async reflection agent + retrieval for future similar tasks. The 200ms retrieval target and 20-40 second consolidation latency are useful production benchmarks.

---

### Anthropic Agent Skills: Procedural Memory as an Open Standard (2025)
- **Venue:** Anthropic Engineering Blog (December 2025)
- **URL:** https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
- **Key findings:**
  - Agent Skills are organized directories (SKILL.md + resources) that agents can discover and load dynamically — Anthropic's production implementation of procedural memory.
  - Progressive disclosure: each skill takes only a few dozen tokens when summarized, with full details loading only when needed, allowing extensive skill libraries without overwhelming working memory.
  - Open standard adopted by Atlassian, Figma, Canva, Stripe, Notion, Zapier, and others.
  - Enterprise management: centrally provisioned, role-based access control, usage monitoring.
- **Implications for TeaParty:** Agent Skills is Anthropic's answer to Voyager's skill libraries — but as a file-based open standard rather than a code execution system. This is directly implementable in TeaParty: agents could discover and load `.skill.md` files from the virtual file system, using them as procedural memory for recurring task patterns. The progressive disclosure pattern (summarize first, load details when needed) addresses working memory constraints.

---

### Multi-Agent Collaboration Survey: What Actually Works (2025)
- **Venue:** arXiv:2501.06322, January 2025
- **URL:** https://arxiv.org/abs/2501.06322
- **Key findings (from large survey of deployed multi-agent systems):**
  - Distributed agents outperform single agents on tasks requiring diverse expertise, but not on tasks that are simply large — parallelism adds coordination overhead that often negates speed gains.
  - Role specialization is the most reliable predictor of multi-agent advantage: teams where agents have distinct, non-overlapping expertise consistently outperform teams of generalists.
  - Communication overhead is the primary scalability bottleneck — every inter-agent message adds latency and token cost.
  - Debate-based coordination (agents argue opposing positions) creates computational analogs to the scientific method and improves output quality for complex decisions.
- **Implications for TeaParty:** Role specialization (already present in TeaParty's agent `role` field) is validated as the correct architectural choice. The debate-based coordination finding suggests that for high-stakes decisions (e.g., significant code refactors, major document revisions), TeaParty could introduce a structured debate mode where multiple agents argue opposing positions before committing to a plan.

---

### MCP: From Internal Experiment to Industry Standard (2024-2025)
- **Venue:** Anthropic (November 2024 launch); Linux Foundation/AAIF (December 2025 donation)
- **URL:** https://modelcontextprotocol.io/specification/2025-11-25
- **Key findings:**
  - Model Context Protocol (MCP) became the de facto standard for agent tool connectivity in 2025: adopted by OpenAI (March 2025), Google DeepMind (April 2025), Microsoft Copilot, VS Code, Cursor.
  - 97 million monthly SDK downloads, 10,000+ active servers by late 2025.
  - MCP standardizes not just tool connectivity but also context injection, resource access, and prompt templates — making it a partial cognitive architecture standard.
  - Donated to Linux Foundation in December 2025 as a vendor-neutral open standard.
- **Implications for TeaParty:** MCP is now infrastructure, not an option. TeaParty agents that expose their memory operations (remember, recall, share) as MCP tools would be interoperable with the broader agent ecosystem. Any TeaParty "skill" defined as an MCP server would be immediately usable by external Claude clients.

---

## Theme 8: Institutional Signals (Conferences and Workshops)

### ICLR 2026 MemAgents Workshop
- **Venue:** ICLR 2026, Rio de Janeiro, April 26-27, 2026
- **URL:** https://sites.google.com/view/memagent-iclr26/
- **Key findings:**
  - A dedicated workshop on memory for LLM-based agentic systems — the first of its kind at a top ML venue. Signals the field's maturation as a distinct research area.
  - Scope: episodic, semantic, and working memory architectures; external stores and parametric knowledge; multi-agent memory; evaluation; RL integration; neuroscience connections.
  - Submission deadline: February 5, 2026. Organizers represent UCSD, Princeton, and others.
  - Companion ICLR 2026 Workshop on Lifelong Agents: Learning, Aligning, Evolving (https://lifelongagent.github.io/) — covers the cross-episode learning side.
- **Implications for TeaParty:** The existence of dedicated workshops confirms this is a high-priority research area, not speculative. The papers submitted and accepted will define state-of-the-art for 2026-2027. Monitoring MemAgents and LifelongAgents proceedings is recommended for the next COGARCH.md update.

---

## Cross-Cutting Synthesis

### What Consensus Is Emerging

Based on the above survey, the field is converging on several design patterns that are appearing independently across multiple systems:

1. **Hierarchical memory (episodic + semantic + procedural + working)** is validated as the correct structure. The specific implementations differ (A-MEM's linked notes, AWS's structured episodes, Mem0's graph) but the layers are consistent.

2. **Memory construction should be closed-loop**: the best systems (MEM-alpha, MemRL, SEDM) use feedback from downstream performance to guide what to store, not just rule-based extraction. This is the next frontier beyond reflection-based approaches.

3. **Forgetting is as important as storing**: FadeMem (in COGARCH.md), MemoryAgentBench, and multiple surveys agree that selective forgetting is an under-studied capability. Systems that cannot forget actively degrade.

4. **Multi-agent knowledge sharing requires individual memory first**: the Emergent Collective Memory finding (individual memory is necessary infrastructure for stigmergy) establishes a clear implementation order.

5. **Metacognition is real but limited and biased**: LLMs have genuine metacognitive ability (self-monitoring, uncertainty estimation) but it is incomplete and systematically biased. Use metacognitive signals as soft hints, not hard gates.

6. **Security is a first-class concern**: memory systems create persistent attack surfaces (MemoryGraft, MINJA). External content should be quarantined from internally-generated memories.

7. **Procedural memory as composable files (Agent Skills pattern)** is emerging as the practical standard for deploying skill libraries — more pragmatic than Voyager's code execution and more structured than narrative reflections.

### What Remains Unsolved

1. **Long-range memory consolidation at scale**: no system has demonstrated reliable memory management over 100,000+ agent turns without degradation.

2. **Cross-agent knowledge transfer**: while collective memory frameworks exist, reliable transfer of learned strategies between agents with different roles remains hard.

3. **Evaluation standards**: MemoryAgentBench and MultiAgentBench are steps forward, but no agreed-upon evaluation suite exists for agent cognitive architectures. Every paper uses different benchmarks.

4. **Genuine multi-agent collaboration gain**: the collaboration gain metric (Gamma) finds that most multi-agent systems do not outperform single agents with equivalent compute. Architectures that reliably produce genuine collaboration gain are rare.

5. **Memory security**: no complete defense against memory poisoning attacks exists. The attack surface grows with every new memory source.

---

## References

- [arXiv:2505.07087] Wray et al., "Applying Cognitive Design Patterns to General LLM Agents," Springer, 2025. https://arxiv.org/abs/2505.07087
- [arXiv:2508.03991] "Galaxy: A Cognition-Centered Framework for Proactive, Privacy-Preserving, and Self-Evolving LLM Agents," 2025. https://arxiv.org/abs/2508.03991
- [arXiv:2512.06716] "Cognitive Control Architecture (CCA)," December 2025. https://arxiv.org/abs/2512.06716
- [arXiv:2601.12560] "Agentic AI: Architectures, Taxonomies, and Evaluation," January 2026. https://arxiv.org/abs/2601.12560
- [arXiv:2502.12110] Xu et al., "A-MEM: Agentic Memory for LLM Agents," NeurIPS 2025. https://arxiv.org/abs/2502.12110
- [arXiv:2512.20237] "MemR3: Memory Retrieval via Reflective Reasoning for LLM Agents," December 2025. https://arxiv.org/abs/2512.20237
- [arXiv:2509.25911] "Mem-alpha: Learning Memory Construction via Reinforcement Learning," ICLR 2026 submission. https://arxiv.org/abs/2509.25911
- [arXiv:2505.02099] "MemEngine: A Unified and Modular Library for Developing Advanced Memory," ACM WWW 2025. https://arxiv.org/abs/2505.02099
- [arXiv:2512.13564] "Memory in the Age of AI Agents," December 2024. https://arxiv.org/abs/2512.13564
- [arXiv:2602.06052] "Rethinking Memory Mechanisms of Foundation Agents in the Second Half: A Survey," February 2026. https://arxiv.org/abs/2602.06052
- [arXiv:2512.10166] Khushiyant, "Emergent Collective Memory in Decentralized Multi-Agent AI Systems," December 2024. https://arxiv.org/abs/2512.10166
- [arXiv:2505.18279] "Collaborative Memory: Multi-User Memory Sharing in LLM Agents with Dynamic Access Control," May 2025. https://arxiv.org/abs/2505.18279
- [arXiv:2602.05289] Fan et al., "Towards a Science of Collective AI: LLM-based Multi-Agent Systems," February 2026. https://arxiv.org/abs/2602.05289
- [arXiv:2509.09498] Xu et al., "SEDM: Scalable Self-Evolving Distributed Memory for Agents," NeurIPS 2025. https://arxiv.org/abs/2509.09498
- [arXiv:2503.09501] "ReMA: Learning to Meta-Think for LLMs with Multi-Agent Reinforcement Learning," NeurIPS 2025. https://arxiv.org/abs/2503.09501
- [arXiv:2505.13763] Li et al., "Language Models Are Capable of Metacognitive Monitoring and Control of Their Internal Activations," May 2025. https://arxiv.org/abs/2505.13763
- [arXiv:2509.21224] "What Do LLM Agents Do When Left Alone? Evidence of Spontaneous Meta-Cognitive Patterns," September 2025. https://arxiv.org/abs/2509.21224
- [arXiv:2509.13237] Didolkar et al. (Meta AI), "Metacognitive Reuse: Turning Recurring LLM Reasoning into Concise Behaviors," September 2025. https://arxiv.org/abs/2509.13237
- [arXiv:2504.14045] Steyvers & Peters, "Metacognition and Uncertainty Communication in Humans and Large Language Models," Current Directions in Psychological Science, 2025. https://arxiv.org/abs/2504.14045
- [arXiv:2509.25140] "ReasoningBank: Scaling Agent Self-Evolving with Reasoning Memory," Google Cloud AI, September 2025. https://arxiv.org/abs/2509.25140
- [arXiv:2601.03192] "MemRL: Self-Evolving Agents via Runtime Reinforcement Learning on Episodic Memory," January 2026. https://arxiv.org/abs/2601.03192
- [arXiv:2508.19005] "Building Self-Evolving Agents via Experience-Driven Lifelong Learning (EvoAgentX)," 2025. https://arxiv.org/abs/2508.19005
- [arXiv:2602.01966] "Self-Consolidation for Self-Evolving Agents (EvoSC)," February 2026. https://arxiv.org/pdf/2602.01966
- [arXiv:2511.03506] "HaluMem: Evaluating Hallucinations in Memory Systems of Agents," November 2025. https://arxiv.org/abs/2511.03506
- [arXiv:2512.16962] "MemoryGraft: Persistent Compromise of LLM Agents via Poisoned Experience Retrieval," December 2024. https://arxiv.org/abs/2512.16962
- [arXiv:2507.05257] Hu, Wang & McAuley, "Evaluating Memory in LLM Agents via Incremental Multi-Turn Interactions (MemoryAgentBench)," ICLR 2026. https://arxiv.org/abs/2507.05257
- [AWS Blog] "Building smarter AI agents: AgentCore long-term memory deep dive," July 2025. https://aws.amazon.com/blogs/machine-learning/building-smarter-ai-agents-agentcore-long-term-memory-deep-dive/
- [Anthropic Engineering] "Equipping agents for the real world with Agent Skills," December 2025. https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
- [arXiv:2501.06322] "Multi-Agent Collaboration Mechanisms: A Survey of LLMs," January 2025. https://arxiv.org/abs/2501.06322
- [MCP Spec] Model Context Protocol November 2025 Specification. https://modelcontextprotocol.io/specification/2025-11-25
- [ICLR 2026] MemAgents Workshop. https://sites.google.com/view/memagent-iclr26/
