# TeaParty Research Library

Master catalog of peer-reviewed and authoritative research informing TeaParty design decisions.

Research is organized by topic file. Each entry includes: title, authors/year, tags, and a one-line summary.

See [learning-system.md](../conceptual-design/learning-system.md) for the conceptual design of TeaParty's learning system, which builds on the research foundations in this index.

## Scope and Research Positioning

This bibliography covers five areas that directly inform TeaParty's design: cognitive architectures for LLM agents, memory management and retrieval, multi-agent coordination, human-AI collaboration and oversight, and production deployment patterns. It also includes implementation-level references for the specific libraries and frameworks used in the POC. The collection spans foundational academic work (2022–2024) and active 2025–2026 research, reflecting the rapid development of the field. For TeaParty's positioning relative to this body of work — what it builds on and what it adds — see the Research Positioning section in [docs/index.md](../index.md).

---

## How to Use This Index

- Browse by tag to find papers relevant to a specific design question.
- Each entry links to the detail file where full citations and implications are recorded.
- "COGARCH" entries are cataloged in `/docs/proposals/cognitive-architecture.md` (the primary cognitive architecture document).
- "SUPPLEMENT" entries are in `docs/research/cognitive-architectures-supplement.md`.
- [act-r.md](act-r.md) — Vanilla ACT-R declarative memory: theory, equations, parameters.
- [soar.md](soar.md) — Soar cognitive architecture: memory systems, decision cycle, chunking, RL.

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
`#adjustable-autonomy` `#concept-drift` `#implicit-feedback` `#bandit` `#proxy-agent`
`#active-learning` `#preference-learning` `#calibration` `#prediction` `#cold-start` `#bayesian`

---

## Cognitive Architectures — Foundational

| Title | Authors, Year | Tags | One-line Summary | Source |
|-------|--------------|------|-----------------|--------|
| Cognitive Architectures for Language Agents (CoALA) | Sumers et al., 2024 | `#memory` `#multi-agent` `#teaparty-direct` | The unifying taxonomy: maps classical cognitive architecture (ACT-R, SOAR) onto LLM agents across memory types, action space, and learning. | COGARCH §2.1 |
| Soar Cognitive Architecture — Memory Systems Reference | Laird et al. (University of Michigan) | `#memory` `#working-memory` `#episodic` `#semantic` `#procedural` | Self-contained reference covering Soar's decision cycle, WMEs, production memory, smem (base-level + spreading activation), epmem (snapshot + graph-match retrieval), chunking, and Soar-RL update rule. | `soar.md` |
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

## Proxy Prediction and Active Learning

Research on forming explicit predictions about human responses, using prediction error (delta) as a learning signal, and calibrating confidence to regulate question-asking. Covers Bayesian preference models, active learning / uncertainty sampling, instance-based cognitive architectures, RLHF/DPO (contrasted as negative examples), conformal calibration, and practical deployed systems. See `docs/research/proxy-prediction-and-active-learning.md` for full citations and synthesis.

| Title | Authors, Year | Tags | One-line Summary | Source |
|-------|--------------|------|-----------------|--------|
| Preference Learning with Gaussian Processes | Chu & Ghahramani, ICML 2005 | `#preference-learning` `#bayesian` `#cold-start` `#proxy-agent` | Foundational GP model for latent utility from pairwise comparisons; posterior variance is calibrated confidence; works at N=5-50. | `proxy-prediction-and-active-learning.md` §1 |
| Tutorial: Learning from Preferences with Gaussian Processes | Benavoli et al., 2024 | `#preference-learning` `#bayesian` `#cold-start` | GPs train on small datasets; complexity grows automatically with data; PrefGP Python library available. | `proxy-prediction-and-active-learning.md` §1 |
| Active Preference-Based GP Regression for Reward Learning | Biyik, Huynh, Kochenderfer & Sadigh, IJRR 2024 | `#preference-learning` `#active-learning` `#bayesian` `#teaparty-direct` | GP + active query selection; demonstrated on real humans; 10-30 queries to reliable prediction; directly implements ask-when-uncertain. | `proxy-prediction-and-active-learning.md` §1 |
| Beta-Bernoulli Bayesian Updating | Classical (Gundersen review, 2020) | `#bayesian` `#cold-start` `#prediction` `#proxy-agent` | Binary prediction with posterior variance; works at N=1; update rule is addition; no library needed. | `proxy-prediction-and-active-learning.md` §1 |
| Active Learning Literature Survey | Settles, 2009 | `#active-learning` `#uncertainty` `#proxy-agent` | Canonical taxonomy of query strategies: uncertainty sampling, QBC, expected model change, information gain. | `proxy-prediction-and-active-learning.md` §2 |
| Understanding Uncertainty Sampling | Nguyen & Huynh, arXiv 2023 | `#active-learning` `#uncertainty` `#calibration` | First formal generalization bounds for uncertainty sampling; calibration required for guarantees. | `proxy-prediction-and-active-learning.md` §2 |
| BALD: Bayesian Active Learning by Disagreement | Houlsby et al., 2011 | `#active-learning` `#bayesian` `#uncertainty` `#proxy-agent` | Query the point that maximally reduces epistemic uncertainty; information-theoretic ask/skip criterion. | `proxy-prediction-and-active-learning.md` §2 |
| Expected Predictive Information Gain (EPIG) | Bickford Smith et al., AISTATS 2023 | `#active-learning` `#bayesian` `#uncertainty` | BALD improved: conditions on actual future query distribution; avoids wasteful outlier queries. | `proxy-prediction-and-active-learning.md` §2 |
| Active Learning Benchmark for Small-Sample Regression | Dunn et al., Scientific Reports 2025 | `#active-learning` `#cold-start` | Empirical: active learning advantages largest in 10-50 observation range; QBC needs ≥15 initial samples. | `proxy-prediction-and-active-learning.md` §2 |
| Instance-Based Learning in Dynamic Decision Making | Gonzalez, Lerch & Lebiere, Cognitive Science 2003 | `#episodic` `#prediction` `#cold-start` `#proxy-agent` | IBLT: store (situation, decision, utility) triplets; blending predicts from similar past instances; works with very few examples. | `proxy-prediction-and-active-learning.md` §3 |
| SpeedyIBL: Implementation of IBLT | Nguyen et al., Behavior Research Methods 2022 | `#episodic` `#prediction` `#proxy-agent` | Python library for IBLT; decay parameter controls recency weighting; off-the-shelf for small-N prediction. | `proxy-prediction-and-active-learning.md` §3 |
| RLHF Deciphered | Casper et al., ACM CSUR 2023 | `#preference-learning` `#calibration` | RLHF is population-level, not individual-level; needs thousands of examples; not the right approach for per-individual proxy. | `proxy-prediction-and-active-learning.md` §4 |
| Direct Preference Optimization (DPO) | Rafailov et al., NeurIPS 2023 | `#preference-learning` | Simpler than RLHF but still large-data; confirms calibration as first-class concern. Not for per-individual small-data use. | `proxy-prediction-and-active-learning.md` §4 |
| Deep Bayesian Active Learning for Preference Modeling | Cao et al., NeurIPS 2024 | `#active-learning` `#bayesian` `#preference-learning` | Bayesian active learning + preference modeling reduces human feedback needed; validates GP + BALD for preference use case. | `proxy-prediction-and-active-learning.md` §4 |
| Conformal Prediction (Introduction) | Angelopoulos & Bates, JMLR 2021 | `#calibration` `#uncertainty` | Distribution-free calibrated intervals; guaranteed coverage at any N; wraps any predictor. | `proxy-prediction-and-active-learning.md` §5 |
| Conformal Prediction for NLP (Survey) | Giovannotti, TACL 2024 | `#calibration` `#uncertainty` | Conformal prediction applied to NLP tasks; inductive (split) variant is practical; LLM softmax probabilities as input. | `proxy-prediction-and-active-learning.md` §5 |
| Generative Agent Simulations of 1,000 People | Park et al., arXiv 2024 | `#prediction` `#human-ai` `#teaparty-direct` | Two-hour interview → LLM agent → 85% response prediction accuracy; empirical ceiling for interview-to-model pipelines. | `proxy-prediction-and-active-learning.md` §6 |
| PersonalLLM: Tailoring LLMs to Individual Preferences | Kumar et al., ICLR 2025 | `#preference-learning` `#cold-start` `#teaparty-direct` | Personalization under continual data sparsity; PREF method converges with ~10 examples; population prior bootstraps cold start. | `proxy-prediction-and-active-learning.md` §6 |
| Few-Shot Personalization with Mis-aligned Responses (Fermi) | Salemi et al., 2024 | `#preference-learning` `#implicit-feedback` `#proxy-agent` | Misaligned (wrong) predictions are the most informative learning signal; validates delta-as-learning-signal design principle. | `proxy-prediction-and-active-learning.md` §6 |
| Training Proactive and Personalized LLM Agents (PPP) | Sun et al., 2025 | `#adjustable-autonomy` `#active-learning` `#human-ai` | Explicitly training ask-vs-predict decision is critical; threshold should be learned, not static. | `proxy-prediction-and-active-learning.md` §6 |

---

## Human Proxy Agent Design — Research Provenance

Traces the research lineage behind specific mechanisms in TeaParty's human proxy agent (EMA confidence, asymmetric regret, exploration rate, cold start, staleness guard, adjustable autonomy, act-or-ask dilemma, dialog-pattern learning). See `docs/research/human-proxy-agent-design.md` for full citations and mapping notes.

| Title | Authors, Year | Tags | One-line Summary | Source |
|-------|--------------|------|-----------------|--------|
| Trust, control strategies and allocation of function in human-machine systems | Lee & Moray, 1992 | `#trust` `#human-ai` `#proxy-agent` | ARMAV time-series model of trust: trust at t is a function of trust at t−1, task performance, and automation failures. Direct ancestor of EMA confidence tracking. | `human-proxy-agent-design.md` §1 |
| Trust, self-confidence, and operators' adaptation to automation | Lee & Moray, 1994 | `#trust` `#human-ai` `#proxy-agent` | Trust and self-confidence jointly predict delegation decisions; confirms dynamic trust model from 1992 paper. | `human-proxy-agent-design.md` §1 |
| The theory of statistical decision | Savage, 1951 | `#proxy-agent` | Minimax regret: choose the action minimizing worst-case opportunity cost. Conceptual ancestor of asymmetric regret weighting. | `human-proxy-agent-design.md` §2 |
| Learning to Optimize Autonomy in Competence-Aware Systems | Basich et al., AAMAS 2020 | `#adjustable-autonomy` `#trust` `#proxy-agent` `#teaparty-direct` | CAS learns autonomy levels online via introspective competence model; formally treats asymmetric costs of acting-wrong vs. escalating-unnecessarily. | `human-proxy-agent-design.md` §2, §6 |
| Finite-time analysis of the multiarmed bandit problem | Auer, Cesa-Bianchi & Fischer, 2002 | `#bandit` `#proxy-agent` | Proves ongoing exploration is necessary even after strong estimates; epsilon-greedy with fixed epsilon is a valid strategy for non-stationary settings. | `human-proxy-agent-design.md` §3 |
| Reinforcement Learning: An Introduction | Sutton & Barto, 2018 | `#bandit` `#proxy-agent` | Canonical formalization of epsilon-greedy exploration-exploitation tradeoff in bandit and RL settings. | `human-proxy-agent-design.md` §3 |
| Methods and metrics for cold-start recommendations | Schein et al., SIGIR 2002 | `#proxy-agent` | Cold-start regime: predictions from fewer than a minimum observation count are statistically unreliable; default to safe fallback. | `human-proxy-agent-design.md` §4 |
| Learning from time-changing data with adaptive windowing (ADWIN) | Bifet & Gavalda, SDM 2007 | `#concept-drift` `#proxy-agent` | ADWIN: variable-length window detects drift by comparing old vs. recent sub-window statistics; time-based forgetting is the simplest drift-adaptive strategy. | `human-proxy-agent-design.md` §5 |
| A survey on concept drift adaptation | Gama et al., ACM CSUR 2014 | `#concept-drift` `#proxy-agent` | Human preference drift is typically gradual/recurring; periodic forced re-calibration is necessary even without obvious failure. | `human-proxy-agent-design.md` §5 |
| FadeMem: Biologically-Inspired Forgetting for Efficient Agent Memory | Wei et al., 2026 | `#forgetting` `#proxy-agent` | Biologically-inspired exponential decay for agent memories; validates time-based staleness as a principled design choice. Preprint only. | `human-proxy-agent-design.md` §5 |
| Human and Computer Control of Undersea Teleoperators | Sheridan & Verplank, 1978 | `#adjustable-autonomy` `#human-ai` | Origin of the 10-level automation taxonomy; levels 5–6 correspond to the proxy's conditional auto-approve behavior. | `human-proxy-agent-design.md` §6 |
| A model for types and levels of human interaction with automation | Parasuraman, Sheridan & Wickens, 2000 | `#adjustable-autonomy` `#trust` `#human-ai` | 2D framework for automation (type × level); misuse and disuse are both failure modes; appropriate reliance is the goal. | `human-proxy-agent-design.md` §6 |
| Adjustable autonomy for human-centered autonomous systems on Mars | Dorais, Bonasso, Kortenkamp, Pell & Schreckenghost, 1999 | `#adjustable-autonomy` `#human-ai` | Coined "adjustable autonomy" as the principle that systems vary autonomy level based on task context and demonstrated performance. | `human-proxy-agent-design.md` §6 |
| Principles of mixed-initiative user interfaces | Horvitz, CHI 1999 | `#adjustable-autonomy` `#human-ai` `#proxy-agent` | Expected-utility framework for act-vs-ask decisions; both acting wrongly and interrupting unnecessarily have costs. Closest single source for the act-or-ask dilemma framing. | `human-proxy-agent-design.md` §7 |
| Principles of adjustable interactions | Crandall & Goodrich, AAAI 2002 | `#adjustable-autonomy` `#proxy-agent` | Explicitly names the act-or-ask dilemma in HRI: acting autonomously risks task failure; asking risks operator overload. Both are costs to minimize. | `human-proxy-agent-design.md` §7 |
| Optimizing search engines using clickthrough data | Joachims, KDD 2002 | `#implicit-feedback` `#proxy-agent` | Implicit signals (click patterns) encode preference without explicit ratings; relative signals are more reliable than absolute ones. Conceptual ancestor of dialog-pattern learning. | `human-proxy-agent-design.md` §8 |
| Leveraging implicit feedback from deployment data in dialogue | Pang, Roller, Cho, He & Weston, EACL 2024 | `#implicit-feedback` `#proxy-agent` | Follow-up question type and content are informative about what the prior system turn failed to address; closest peer-reviewed precedent for learning from dialog review patterns. | `human-proxy-agent-design.md` §8 |
| Logic and conversation | Grice, 1975 | `#implicit-feedback` `#proxy-agent` | Cooperative Principle and Quantity maxim: questions asked reveal what information is missing from the interlocutor's model; linguistic foundation for treating review questions as implicit feedback. | `human-proxy-agent-design.md` §8 |

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

## Conversation Protocols and Speech Act Theory

Foundational work on speech act theory and its application to coordination protocols. These papers underpin TeaParty's Conversation for Action (CfA) design. See `docs/background/conversation-patterns.md` for the narrative essay situating this work.

| Title | Authors, Year | Tags | One-line Summary | Source |
|-------|--------------|------|-----------------|--------|
| How to Do Things with Words | Austin, 1962 | `#speech-acts` `#coordination` | Foundational: utterances are not descriptions but performative acts; distinguishes locutionary, illocutionary, and perlocutionary acts. | `docs/background/conversation-patterns.md` |
| Speech Acts: An Essay in the Philosophy of Language | Searle, 1969 | `#speech-acts` `#coordination` | Systematized speech act theory with explicit rules for illocutionary force; five categories: assertives, directives, commissives, expressives, declarations. | `docs/background/conversation-patterns.md` |
| Expression and Meaning | Searle, 1979 | `#speech-acts` `#coordination` | Refined five-category taxonomy with illocutionary point, direction of fit, and psychological state as the three distinguishing dimensions. | `docs/background/conversation-patterns.md` |
| Understanding Computers and Cognition | Winograd & Flores, 1986 | `#cfa` `#speech-acts` `#coordination` `#teaparty-direct` | Introduced the Conversation for Action state machine; treats coordination as structured speech acts rather than information exchange. Direct ancestor of TeaParty's CfA protocol. | `docs/background/conversation-patterns.md` |
| The Contract Net Protocol | Smith, 1980 | `#multi-agent` `#coordination` | Market-inspired task allocation via announcement/bid/award; handles task assignment but assumes unambiguous task descriptions — does not address intent alignment. | `docs/background/conversation-patterns.md` |
| A Blackboard Architecture for Control | Hayes-Roth, 1985 | `#multi-agent` `#coordination` | Shared working memory with opportunistic knowledge-source scheduling; coordination by shared state, not commitment; poor fit for human-AI mixed teams. | `docs/background/conversation-patterns.md` |
| ReAct: Synergizing Reasoning and Acting in Language Models | Yao et al., ICLR 2023 | `#agent-reasoning` `#llm` | Interleaved reasoning traces and actions improve single-agent task performance; plan-execute loop with local recovery; no intent alignment or cross-phase backtrack. | `docs/background/conversation-patterns.md` |
| Plan-and-Solve Prompting | Wang et al., ACL 2023 | `#agent-reasoning` `#llm` | Separates plan generation from execution to reduce missing-step errors; treats human request as complete specification; no approval gate mechanism. | `docs/background/conversation-patterns.md` |
| AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation | Wu et al., 2023 | `#multi-agent` `#llm` `#coordination` | Flexible multi-agent conversation framework (LLMs, humans, tools); conversation structure is content-driven, not protocol-enforced; no commitment tracking. | `docs/background/conversation-patterns.md` |

---

## Conferences and Workshops to Monitor

| Event | Date | Topic |
|-------|------|-------|
| ICLR 2026 MemAgents Workshop | April 26-27, 2026, Rio | Memory architectures for LLM-based agentic systems |
| ICLR 2026 Lifelong Agents Workshop | April 2026 | Cross-episode learning, alignment, evolution |
| AAAI 2026 WMAC Workshop | 2026 | LLM-based multi-agent collaboration |
| NeurIPS 2026 (expected) | December 2026 | Full proceedings from current preprints |
