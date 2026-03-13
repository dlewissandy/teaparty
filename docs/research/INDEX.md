# TeaParty Research Library

Master catalog of peer-reviewed and authoritative research informing TeaParty design decisions.

Research is organized by topic file. Each entry includes: title, authors/year, tags, and a one-line summary.

See [learning-system.md](../learning-system.md) for the conceptual design of TeaParty's learning system, which builds on the research foundations in this index.

---

## How to Use This Index

- Browse by tag to find papers relevant to a specific design question.
- Each entry links to the detail file where full citations and implications are recorded.
- "COGARCH" entries are cataloged in `/docs/cognitive-architecture.md` (the primary cognitive architecture document).
- "SUPPLEMENT" entries are in `docs/research/cognitive-architectures-supplement.md`.

---

## Tag Reference

`#memory` `#episodic` `#semantic` `#procedural` `#working-memory` `#forgetting`
`#multi-agent` `#collective` `#coordination` `#stigmergy` `#knowledge-sharing`
`#metacognition` `#uncertainty` `#self-monitoring` `#self-evolving`
`#production` `#security` `#failure-modes` `#evaluation`
`#human-ai` `#trust` `#teaparty-direct`
`#context-injection` `#retrieval` `#claude-code` `#openclaw`
`#tui` `#ui-events` `#textual` `#widget`
`#state-machine` `#async` `#orchestration` `#workflow`

---

## Cognitive Architectures — Foundational

| Title | Authors, Year | Tags | One-line Summary | Source |
|-------|--------------|------|-----------------|--------|
| Cognitive Architectures for Language Agents (CoALA) | Sumers et al., 2024 | `#memory` `#multi-agent` `#teaparty-direct` | The unifying taxonomy: maps classical cognitive architecture (ACT-R, SOAR) onto LLM agents across memory types, action space, and learning. | COGARCH §2.1 |
| Generative Agents | Park et al., 2023 | `#memory` `#episodic` `#reflection` `#teaparty-direct` | 25 simulated agents with memory streams, three-factor retrieval (recency × relevance × importance), and periodic reflection. Reflection was the critical ingredient for emergent behavior. | COGARCH §2.2 |
| Reflexion | Shinn et al., 2023 | `#episodic` `#self-evolving` | Verbal self-reflection stored as persistent memory enables learning without weight updates. Near-human HumanEval performance after 2-3 cycles. | COGARCH §2.3 |
| Voyager | Wang et al., 2023 | `#procedural` `#skill-library` | Skill library of verified executable JavaScript functions in Minecraft. Procedural memory as code is more reliable than natural language. | COGARCH §2.4 |
| CLIN | Majumder et al., 2024 | `#episodic` `#semantic` `#self-evolving` | Causal abstraction learning (when X, doing Y leads to Z) persists across episodes. Outperforms Reflexion by 23 points on ScienceWorld. | COGARCH §2.5 |
| MemGPT / Letta | Packer et al., 2023 | `#memory` `#working-memory` `#teaparty-direct` | Agent-managed memory hierarchy (main context, archival, recall) via explicit tools. Agents decide what to remember and forget. | COGARCH §2.6 |
| ExpeL | Zhao et al., 2024 | `#episodic` `#self-evolving` | Contrastive learning from successes vs. failures extracts cross-task insights. More transferable than Reflexion's failure-only approach. | COGARCH §2.7 |
| AutoRefine | 2025 | `#procedural` `#self-evolving` | Dual-form experience patterns (subagents + skill patterns); automatic extraction beats manually designed systems (27.1% vs 12.1% on TravelPlanner). | COGARCH §2.8 |
| Mem0 | Chhikara et al., 2025 | `#memory` `#production` `#teaparty-direct` | Production memory with graph variant. 26% accuracy boost, 91% lower p95 latency, 90% token savings vs. full-context. | COGARCH §2.9 |
| FadeMem | 2025 | `#forgetting` | Biologically-inspired decay: 82.1% retention of critical facts at 55% storage. Selective forgetting improves retention quality. | COGARCH §2.10 |
| LLM-ACTR | Wu et al., 2025 | `#memory` | ACT-R decision-making integrated into LLMs via adapter layers. | COGARCH §2.10 |
| Brain-Inspired MAP | Nature Communications, 2025 | `#multi-agent` `#coordination` | Modular brain-inspired planning agents outperform monolithic ones. | COGARCH §2.10 |
| DSPy | Khattab et al., 2024 | `#procedural` | Optimizing prompts as programs — automated procedural learning via compilation. | COGARCH §2.10 |
| LaMer | 2025 | `#self-evolving` `#episodic` | Meta-RL for LLM agents: cross-episode training with in-context policy adaptation via reflection. | COGARCH §2.10 |

---

## Cognitive Architectures — 2025-2026 Developments

| Title | Authors, Year | Tags | One-line Summary | Source |
|-------|--------------|------|-----------------|--------|
| Applying Cognitive Design Patterns to General LLM Agents | Wray et al., 2025 | `#procedural` `#metacognition` | Catalogs cognitive design patterns across classical and LLM architectures; predicts gaps in agents lacking impasse-driven learning and goal-stack management. | SUPPLEMENT §Theme 1 |
| Galaxy | 2025 | `#metacognition` `#self-evolving` `#multi-agent` | Cognition Forest unifies cognitive modeling and system design; separates proactive from responsive behavior as distinct cognitive layers. | SUPPLEMENT §Theme 1 |
| Cognitive Control Architecture (CCA) | 2025 | `#production` `#security` | Intent Graph + Tiered Adjudicator for full-lifecycle cognitive supervision and alignment in autonomous agents. | SUPPLEMENT §Theme 1 |
| Agentic AI: Architectures, Taxonomies, and Evaluation | 2026 | `#multi-agent` `#evaluation` | Six-dimensional taxonomy; identifies code-as-action, MCP, and typed-state orchestration as the emerging production standard. | SUPPLEMENT §Theme 1 |

---

## Memory Management

| Title | Authors, Year | Tags | One-line Summary | Source |
|-------|--------------|------|-----------------|--------|
| A-MEM: Agentic Memory for LLM Agents | Xu et al., NeurIPS 2025 | `#memory` `#episodic` `#semantic` `#teaparty-direct` | Zettelkasten-inspired linked memory notes; retrieval traverses semantic links rather than flat nearest-neighbor search. Superior on all six tested models. | SUPPLEMENT §Theme 2 |
| MemR3: Memory Retrieval via Reflective Reasoning | 2025 | `#memory` `#episodic` `#teaparty-direct` | Retrieve-reflect-answer loop with global evidence-gap tracker; avoids confident-wrong answers from partial retrieval. | SUPPLEMENT §Theme 2 |
| Mem-alpha: Learning Memory Construction via RL | 2025-2026 | `#memory` `#self-evolving` | RL trains agents to decide what to store, how, and when; generalizes from 30k to 400k token contexts (13x). | SUPPLEMENT §Theme 2 |
| MemEngine: Unified Modular Memory Library | 2025 | `#memory` `#forgetting` | 15+ memory strategies as pluggable modules (encoding, retrieval, summarization, forgetting, meta-learning); 89-95% compression. | SUPPLEMENT §Theme 2 |
| Memory in the Age of AI Agents (Survey) | 2024 | `#memory` `#episodic` `#semantic` | Three forms of memory (token-level, parametric, latent); functional taxonomy; emerging research frontiers. | SUPPLEMENT §Theme 2 |
| Rethinking Memory Mechanisms in the Second Half (Survey) | 2026 | `#memory` `#forgetting` `#episodic` | 218 papers; three-dimension taxonomy (substrate, cognitive mechanism, subject); "second half" challenge is real-world utility, not benchmark scores. | SUPPLEMENT §Theme 2 |
| Episodic Memory is the Missing Piece for Long-Term LLM Agents | 2025 | `#episodic` | Most systems underweight episodic vs. semantic/procedural memory; agents recalling specific past experiences outperform those relying on general knowledge. | COGARCH §3.1 |
| ACT-R-Inspired Memory for LLM Agents | 2024-2025 | `#memory` `#episodic` | Human-like remembering and forgetting via ACT-R activation function in agent context. | COGARCH §11 |

---

## Multi-Agent Coordination and Collective Cognition

| Title | Authors, Year | Tags | One-line Summary | Source |
|-------|--------------|------|-----------------|--------|
| Emergent Collective Memory in Decentralized Multi-Agent AI Systems | Khushiyant, 2024 | `#multi-agent` `#collective` `#stigmergy` `#teaparty-direct` | Individual memory (+68.7% gain) is necessary infrastructure for stigmergy to work; collective memory phase-transitions above critical agent density. | SUPPLEMENT §Theme 3 |
| Collaborative Memory: Multi-User Sharing with Dynamic Access Control | 2025 | `#multi-agent` `#memory` `#teaparty-direct` | Two-tier private/shared memory with dynamic bipartite access graphs; fine-grained per-user-agent read/write policies. | SUPPLEMENT §Theme 3 |
| Towards a Science of Collective AI | Fan et al., 2026 | `#multi-agent` `#evaluation` | Defines "collaboration gain" (Gamma) metric; most multi-agent systems do NOT outperform single agents with equivalent compute. | SUPPLEMENT §Theme 3 |
| SEDM: Scalable Self-Evolving Distributed Memory | Xu et al., NeurIPS 2025 | `#multi-agent` `#memory` `#self-evolving` | Verifiable write admission (A/B replay for marginal utility); self-scheduling retrieval; near-duplicate merging. | SUPPLEMENT §Theme 3 |
| Multi-Agent Collaboration Mechanisms: A Survey | 2025 | `#multi-agent` `#coordination` | Role specialization is the most reliable predictor of multi-agent advantage; debate-based coordination improves quality for complex decisions. | SUPPLEMENT §Theme 7 |
| Memory in LLM-based Multi-Agent Systems (Survey) | 2025 | `#multi-agent` `#memory` `#collective` | Network topology significantly affects collective cognition; noise accumulation and uncontrolled expansion are primary challenges. | SUPPLEMENT §Theme 3 |

---

## Metacognition

| Title | Authors, Year | Tags | One-line Summary | Source |
|-------|--------------|------|-----------------|--------|
| ReMA: Learning to Meta-Think via Multi-Agent RL | NeurIPS 2025 | `#metacognition` `#multi-agent` | High-level meta-thinking agent + low-level execution agent trained jointly via RL; 53.2% on MATH, beats single-agent RL baselines. | SUPPLEMENT §Theme 4 |
| Language Models Are Capable of Metacognitive Monitoring | Li et al., 2025 | `#metacognition` `#self-monitoring` | LLMs can monitor and control a limited subset of internal activations; metacognitive space has much lower dimensionality than neural space. | SUPPLEMENT §Theme 4 |
| What Do LLM Agents Do When Left Alone? | 2025 | `#metacognition` `#self-monitoring` | Three spontaneous meta-cognitive patterns (project production, self-inquiry, self-conceptualization) emerge; highly model-specific. | SUPPLEMENT §Theme 4 |
| Metacognitive Reuse: Turning Recurring LLM Reasoning into Concise Behaviors | Didolkar et al., Meta AI, 2025 | `#procedural` `#metacognition` `#teaparty-direct` | Behavior handbook extracted from reasoning traces; 46% token reduction on MATH/AIME while matching or improving accuracy. | SUPPLEMENT §Theme 4 |
| Metacognition and Uncertainty Communication in Humans and LLMs | Steyvers & Peters, 2025 | `#metacognition` `#human-ai` `#trust` | LLMs are systematically over/underconfident; explicit uncertainty sharing improves human-LLM team calibration. | SUPPLEMENT §Theme 4 |

---

## Self-Evolving Agents

| Title | Authors, Year | Tags | One-line Summary | Source |
|-------|--------------|------|-----------------|--------|
| ReasoningBank | Google Cloud AI, 2025 | `#self-evolving` `#episodic` `#semantic` | Strategy-level memory from successes + failures; +34.2% effectiveness, -16% steps vs. raw-trajectory memory. | SUPPLEMENT §Theme 5 |
| MemRL: Self-Evolving Agents via Runtime RL on Episodic Memory | 2026 | `#self-evolving` `#episodic` | Q-value-based retrieval selection decouples stable reasoning from plastic memory; no weight updates; beats SOTA on multiple benchmarks. | SUPPLEMENT §Theme 5 |
| Building Self-Evolving Agents via Experience-Driven Lifelong Learning (EvoAgentX) | 2025 | `#self-evolving` | +20% on GAIA, +10% MBPP from continuous learning; StuLife benchmark for evaluating long-horizon agent development. | SUPPLEMENT §Theme 5 |
| Self-Consolidation for Self-Evolving Agents (EvoSC) | 2026 | `#self-evolving` `#memory` | Non-parametric contrastive extraction + parametric consolidation (into compact learnable prompts) addresses context-window limits for lifetime history. | SUPPLEMENT §Theme 5 |

---

## Failure Modes and Evaluation

| Title | Authors, Year | Tags | One-line Summary | Source |
|-------|--------------|------|-----------------|--------|
| HaluMem: Evaluating Hallucinations in Memory Systems | 2025 | `#failure-modes` `#evaluation` `#memory` | First memory-specific hallucination benchmark; errors compound through extract → update → QA pipeline. | SUPPLEMENT §Theme 6 |
| MemoryGraft: Persistent Memory Poisoning | 2024 | `#failure-modes` `#security` | Attackers can plant poisoned memories via normal ingestion-level content; effect persists across sessions; no complete defense exists. | SUPPLEMENT §Theme 6 |
| MemoryAgentBench | Hu et al., ICLR 2026 | `#evaluation` `#memory` | Four competencies: accurate retrieval, test-time learning, long-range understanding, selective forgetting. Current systems fail to master all four. | SUPPLEMENT §Theme 6 |
| The Problem with AI Agent Memory (practitioner) | Giannone, 2025 | `#failure-modes` `#memory` | Context poisoning and context distraction; embedding similarity missing temporal relevance; vector DBs store text not understanding. | SUPPLEMENT §Theme 6 |
| MINJA: Memory Injection Attack via Query-Only Interaction | 2025 | `#security` `#failure-modes` | Regular users (no elevated privileges) can poison agent memory through ordinary queries using bridging steps and indication prompts. | SUPPLEMENT §Theme 6 |

---

## Production Deployments and Industry Standards

| Title | Org, Year | Tags | One-line Summary | Source |
|-------|----------|------|-----------------|--------|
| Amazon Bedrock AgentCore Memory | AWS, 2025 | `#production` `#memory` `#episodic` | Production memory service: 200ms retrieval, 20-40s consolidation; episodic functionality with reflection agent validates COGARCH.md's reflection engine design. | SUPPLEMENT §Theme 7 |
| Agent Skills | Anthropic, 2025 | `#procedural` `#production` `#teaparty-direct` | File-based procedural memory (SKILL.md directories) with progressive disclosure; open standard adopted across the ecosystem. | SUPPLEMENT §Theme 7 |
| Model Context Protocol (MCP) | Anthropic / Linux Foundation, 2025 | `#production` `#teaparty-direct` | De facto standard for agent tool connectivity; 97M monthly SDK downloads; donated to Linux Foundation Dec 2025. | SUPPLEMENT §Theme 7 |
| Microsoft Agent Framework | Microsoft, 2025 | `#production` `#multi-agent` | Unification of AutoGen + Semantic Kernel; asynchronous event-driven messaging; cross-language support. | SUPPLEMENT §Theme 7 |

---

## Human-AI Collaboration

| Title | Authors, Year | Tags | One-line Summary | Source |
|-------|--------------|------|-----------------|--------|
| Cognitive Challenges in Human-AI Collaboration | Logg et al., 2022 | `#human-ai` `#trust` | Teams improve only when AI delegates to humans, not when humans delegate to AI — challenges assumptions about AI as pure assistant. | SUPPLEMENT §Theme 7 |
| Theory of Mind for Multi-Agent Collaboration | 2024 | `#multi-agent` `#human-ai` | MetaMind achieves 81% on ToM tasks; maintaining consistent agent models across extended interactions remains open. | COGARCH §5.1 |
| Supporting Effortless Coordination (25 years of CSCW awareness research) | Gross, 2013 | `#human-ai` `#coordination` | Teams with better shared mental models coordinate with less explicit communication — validated design principle for agent team architecture. | COGARCH §5.1 |

---

## Claude Code Memory System and Retrieval Architecture

| Title | Authors/Org, Year | Tags | One-line Summary | Source |
|-------|------------------|------|-----------------|--------|
| Claude Code Memory System (official docs) | Anthropic, 2025-2026 | `#memory` `#context-injection` `#production` `#teaparty-direct` | MEMORY.md first 200 lines load verbatim at session start; topic files are read on demand; no semantic retrieval. Full four-scope hierarchy (managed, project, local, user). | `claude-code-memory-system.md` §1-3 |
| Claude Code Subagent Persistent Memory | Anthropic, 2026 | `#memory` `#multi-agent` `#production` `#teaparty-direct` | `memory: user/project/local` frontmatter gives each subagent its own MEMORY.md with same 200-line injection rule; identical mechanics to main session memory. | `claude-code-memory-system.md` §3 |
| OpenClaw Memory Architecture | Steinberger et al., 2025-2026 | `#memory` `#retrieval` `#openclaw` `#production` | Hybrid sqlite-vec + FTS5 retrieval over chunked Markdown; selective injection vs. Claude Code's flat injection; open-sourced as memsearch by Zilliz. | `claude-code-memory-system.md` §5 |

---

## TUI Framework — Textual Widget Events

| Title | Authors/Org, Year | Tags | One-line Summary | Source |
|-------|------------------|------|-----------------|--------|
| Textual ListView.Highlighted Event | Textualize docs, 2024-2025 | `#tui` `#ui-events` `#textual` `#widget` | Fires on arrow key navigation; `event.item` is the ListItem widget; no built-in data payload; use parallel index list or ListItem subclass. | `textual-tui-selection-widgets.md` §1 |
| Textual OptionList.OptionHighlighted Event | Textualize docs, 2024-2025 | `#tui` `#ui-events` `#textual` `#widget` | Fires on arrow keys; `event.option_id` gives the string key set at Option construction — cleanest data-attachment pattern of the three main list widgets. | `textual-tui-selection-widgets.md` §2 |
| Textual Tree.NodeHighlighted Event | Textualize docs, 2024-2025 | `#tui` `#ui-events` `#textual` `#widget` | Fires on arrow keys; `event.node.data` carries arbitrary typed payload set at node creation — most ergonomic for structured data. | `textual-tui-selection-widgets.md` §3 |
| Textual SelectionList.SelectionHighlighted Event | Textualize docs, 2024-2025 | `#tui` `#ui-events` `#textual` `#widget` | Designed for multi-select checkbox lists; wrong widget for single-selection panel-update patterns. | `textual-tui-selection-widgets.md` §4 |
| Textual prevent() Context Manager | Textualize docs, 2024-2025 | `#tui` `#ui-events` `#textual` | Universal gate for suppressing spurious events during programmatic widget rebuilds; canonical solution for clear/repopulate refresh patterns. | `textual-tui-selection-widgets.md` §5 |
| OptionList as DataTable Replacement for Project List | Synthesized, 2025 | `#tui` `#widget` `#teaparty-direct` | OptionList + set_options() + prevent(OptionHighlighted) eliminates the DataTable CursorMoved async race condition in dashboard.py; Option(id=slug) removes parallel index list. | `textual-tui-selection-widgets.md` §6 |

---

## Python State Machine and Workflow Libraries

| Library | Year surveyed | Tags | One-line Summary | Source |
|---------|--------------|------|-----------------|--------|
| python-statemachine (fgmacedo) v3.0.0 | 2026 | `#state-machine` `#async` `#orchestration` `#teaparty-direct` | **Recommended.** Native asyncio auto-detection, fluent declarative DSL, full statecharts (compound/parallel/history states), guards, enter/exit actions. MIT, actively maintained. | `python-state-machine-libraries.md` |
| python-statemachine — Persistence and Resumption | 2026 | `#state-machine` `#orchestration` `#persistence` `#teaparty-direct` | No built-in serialization; official pattern is a persistent domain model that owns `model.state`. `start_value` param restores flat machines. Compound/history state recovery is partial — `history_values` is in-memory only and not persistable without custom code. | `python-statemachine-persistence.md` |
| transitions (pytransitions) v0.9.x | 2026 | `#state-machine` `#async` `#orchestration` | Battle-tested (6,500 stars), native AsyncMachine + HierarchicalAsyncMachine, dict-based API, MIT. Solid second choice; more ceremony than python-statemachine. | `python-state-machine-libraries.md` |
| sismic v1.6.11 | 2026 | `#state-machine` `#workflow` | Academic SCXML statechart interpreter; thread-based async incompatible with asyncio; YAML-file DSL; LGPL. Reject for asyncio-first code. | `python-state-machine-libraries.md` |
| temporalio (Temporal Python SDK) | 2026 | `#workflow` `#orchestration` | Durable async workflow execution with first-class asyncio; requires Temporal server cluster; determinism constraints; correct for distributed multi-service orchestration, overkill for in-process. | `python-state-machine-libraries.md` |
| dramatiq v2.1.0 | 2026 | `#workflow` | Distributed task queue (Redis/RabbitMQ), not a state machine. Wrong tool for in-process state management. | `python-state-machine-libraries.md` |
| prefect | 2026 | `#workflow` `#orchestration` | Data pipeline orchestration framework; requires Prefect server; designed for DAG-style batch jobs, not agent session lifecycle. | `python-state-machine-libraries.md` |
| automat (glyph) | 2026 | `#state-machine` | Twisted-era, callback-model async; no hierarchical states; MIT. Reject for asyncio projects. | `python-state-machine-libraries.md` |
| xstate-python (Stately) | 2026 | `#state-machine` | Official Python port of XState; explicitly "work in progress" as of 2026; not production-ready. | `python-state-machine-libraries.md` |

---

## Conferences and Workshops to Monitor

| Event | Date | Topic |
|-------|------|-------|
| ICLR 2026 MemAgents Workshop | April 26-27, 2026, Rio | Memory architectures for LLM-based agentic systems |
| ICLR 2026 Lifelong Agents Workshop | April 2026 | Cross-episode learning, alignment, evolution |
| AAAI 2026 WMAC Workshop | 2026 | LLM-based multi-agent collaboration |
| NeurIPS 2026 (expected) | December 2026 | Full proceedings from current preprints |
