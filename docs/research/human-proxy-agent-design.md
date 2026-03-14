# Research Provenance: Human Proxy Agent Design

This file traces the research lineage behind specific mechanisms in TeaParty's human proxy agent system — the component that tracks approval history per (state, task) pair, auto-approves when confidence is high, and escalates to the human when uncertain.

Each section identifies actual peer-reviewed sources and maps the paper's contribution to the specific implementation mechanism. Where the mapping is an adaptation rather than a direct implementation, that distinction is made explicit.

---

## 1. EMA-Based Confidence Tracking

**Mechanism:** Approval rate per (state, task) pair is maintained as an exponential moving average (alpha=0.3). When EMA exceeds a threshold the proxy auto-approves; otherwise it escalates.

### Direct lineage

**Lee, J.D. & Moray, N. (1992). Trust, control strategies and allocation of function in human-machine systems.**
- **Venue:** Ergonomics, 35(10), 1243–1270.
- **URL:** https://www.semanticscholar.org/paper/Trust,-control-strategies-and-allocation-of-in-Lee-Moray/08a8efa5395dbe0fa2504807094dfe65e9c1347f
- **Key findings:**
  - Introduced an Autoregressive Moving Average Vector (ARMAV) time-series model of trust: trust at time t is a function of trust at t−1, task performance, and automation failure events.
  - In a pasteurization plant simulation, the ARMAV model accounted for 60.9–86.5% of variance in controller-use decisions.
  - Trust is computed dynamically at each decision point, not assigned statically.
- **Mapping to mechanism:** The EMA update (new_ema = alpha * outcome + (1 - alpha) * old_ema) is a simplified single-variable version of the ARMAV model. Both treat trust as a running statistic that weights recent evidence more than old evidence. Alpha=0.3 corresponds to giving recent outcomes roughly 3.3x the weight of older ones, consistent with Lee & Moray's finding that recent failures dominate trust trajectories. This is a direct conceptual implementation.

**Lee, J.D. & Moray, N. (1994). Trust, self-confidence, and operators' adaptation to automation.**
- **Venue:** International Journal of Human-Computer Studies, 40(1), 153–184.
- **URL:** https://dl.acm.org/doi/10.1006/ijhc.1994.1007
- **Key findings:**
  - Confirmed ARMAV findings in a follow-on study. Showed that self-confidence (operator's belief in their own capability) interacts with trust in the automation to determine allocation decisions.
  - Trust and self-confidence jointly predict when operators switch between manual and automatic control.
- **Mapping to mechanism:** The proxy's EMA models accumulated "trust in the agent" for this context. The threshold-based auto-approve corresponds to the trust-exceeds-self-confidence crossover point at which operators in Lee & Moray's experiments chose to delegate.

---

## 2. Asymmetric Regret Weighting

**Mechanism:** A single human correction counts as 3x decay steps. False approvals are treated as 3x more costly than false escalations. The design is explicitly called "least-regret escalation."

### Conceptual lineage

**Savage, L.J. (1951). The theory of statistical decision.**
- **Venue:** Journal of the American Statistical Association, 46(253), 55–67.
- **URL:** https://www.jstor.org/stable/2280094 (original); referenced via https://link.springer.com/referenceworkentry/10.1057/978-1-349-95121-5_2965-1
- **Key findings:**
  - Introduced minimax regret as a decision criterion: choose the action that minimizes the maximum possible regret (difference between actual outcome and what would have been achieved by the optimal action under each state of the world).
  - Regret is computed asymmetrically by definition — it measures the opportunity cost of being wrong in a specific direction.
- **Mapping to mechanism:** The 3x correction penalty is an asymmetric regret weight, not minimax regret proper. Minimax regret asks "what is the worst-case regret over all states?" whereas the proxy uses a fixed asymmetric weight based on domain knowledge (corrections are more disruptive than unnecessary escalations). The naming "least-regret escalation" invokes the Savage framing but the implementation is a simpler expected-regret threshold, not a full minimax computation. This is an adaptation that borrows the vocabulary and intuition of regret theory without implementing its full machinery.

### Application-level lineage

**Basich, C., Svegliato, J., Wray, K.H., Witwicki, S., Biswas, J. & Zilberstein, S. (2020). Learning to Optimize Autonomy in Competence-Aware Systems.**
- **Venue:** Proceedings of the 19th International Conference on Autonomous Agents and Multiagent Systems (AAMAS 2020), Auckland, NZ, May 2020.
- **URL:** https://dl.acm.org/doi/10.5555/3398761.3398781 / arXiv:2003.07745
- **Key findings:**
  - Competence-Aware Systems (CAS) learn autonomy levels online via an introspective model of proficiency, factoring in the cost of human assistance.
  - The model explicitly represents the cost asymmetry between acting autonomously and incorrectly versus escalating unnecessarily — incorrect autonomous action typically incurs higher cost.
  - Provides formal analysis of convergence under this asymmetric cost structure.
- **Mapping to mechanism:** The 3x asymmetric weighting is a hard-coded instantiation of the cost asymmetry that CAS treats as a learnable parameter. The proxy assumes corrections are more costly than escalations based on domain knowledge rather than learning the ratio. The paper provides theoretical grounding that asymmetric cost weighting is a principled design choice for autonomy systems, not an arbitrary fudge factor.

---

## 3. Exploration Rate (Epsilon-Greedy)

**Mechanism:** Even at high confidence (EMA above threshold), the proxy escalates 15% of the time to prevent convergence and maintain calibration signal.

### Direct lineage

**Auer, P., Cesa-Bianchi, N. & Fischer, P. (2002). Finite-time analysis of the multiarmed bandit problem.**
- **Venue:** Machine Learning, 47(2-3), 235–256.
- **URL:** https://link.springer.com/article/10.1023/A:1013689704352
- **Key findings:**
  - Proves that the exploration-exploitation tradeoff in bandit problems requires ongoing exploration even after a strong estimate of arm quality is established.
  - UCB1 and UCB2 policies achieve optimal O(log n) regret bounds while maintaining exploration.
  - Epsilon-greedy with fixed epsilon is a simpler alternative: explore with probability ε regardless of confidence. At ε=0 the agent converges prematurely to suboptimal policies.
- **Mapping to mechanism:** The 15% escalation floor is fixed-epsilon-greedy applied to the autonomy decision. The "arm" is the escalate/approve binary decision; the "reward" is calibration quality over time. The paper formally justifies why a non-zero exploration rate is necessary even after apparent convergence — if the system stops escalating, it loses the signal needed to detect when its model has drifted.

**Sutton, R.S. & Barto, A.G. (2018). Reinforcement Learning: An Introduction (2nd ed.)**
- **Venue:** MIT Press. (1st ed. 1998 introduced epsilon-greedy for bandit problems.)
- **URL:** https://www.andrew.cmu.edu/course/10-703/textbook/BartoSutton.pdf
- **Key findings:**
  - Chapter 2 formalizes the k-armed bandit problem and proves that greedy policies (ε=0) converge to suboptimal arms whenever initial estimates are slightly wrong.
  - Fixed-ε policies trade some per-step reward for ongoing exploration; decaying-ε policies achieve optimal rates asymptotically but require knowing the time horizon.
- **Mapping to mechanism:** The 15% rate is a fixed epsilon. The proxy's designers chose not to decay ε because preference drift (see mechanism 5) means the exploration is never truly redundant — conditions change, so calibration signal is always valuable. This matches Sutton & Barto's guidance for non-stationary environments.

---

## 4. Cold Start Threshold

**Mechanism:** With fewer than 5 observations, always escalate regardless of EMA value.

### Direct lineage

**Cold start problem — recommender systems literature**
- **Canonical reference:** Schein, A.I., Popescul, A., Ungar, L.H. & Pennock, D.M. (2002). Methods and metrics for cold-start recommendations. Proceedings of the 25th ACM SIGIR Conference on Research and Development in Information Retrieval, pp. 253–260.
- **URL:** https://dl.acm.org/doi/10.1145/564376.564421
- **Key findings:**
  - New items with few interaction records cannot be reliably scored by collaborative filtering; predictions made from fewer than a minimum observation threshold are not meaningfully better than random.
  - The "cold start" regime is qualitatively different from the "warm" regime — different algorithms (content-based vs. collaborative) are appropriate in each.
- **Mapping to mechanism:** The n < 5 threshold treats the proxy decision as a cold-start context: when fewer than 5 outcomes have been observed for a (state, task) pair, any EMA value is statistically unreliable and the system should default to the safe action (escalate). The specific threshold of 5 is a design choice not derived from the recommender literature, which typically uses larger thresholds (10–20 interactions). The concept — that below some count, observed rates cannot be trusted — is drawn directly from cold-start research.

**Note on field of origin:** The cold start framing comes from recommender systems. There is no strong HRI-specific literature establishing a minimum-observations threshold for autonomy decisions; the recommender systems framing is the best available conceptual precedent.

---

## 5. Staleness Guard (7-Day Forced Escalation)

**Mechanism:** If no human feedback has been received for 7 or more days, force escalation regardless of confidence. Preferences drift.

### Primary lineage

**Concept drift / non-stationary environments literature**

The ADWIN algorithm (Adaptive Windowing) is the canonical algorithmic treatment:

**Bifet, A. & Gavalda, R. (2007). Learning from time-changing data with adaptive windowing.**
- **Venue:** Proceedings of the 7th SIAM International Conference on Data Mining (SDM), pp. 443–448.
- **URL:** https://epubs.siam.org/doi/10.1137/1.9781611972771.42
- **Key findings:**
  - ADWIN maintains a variable-length sliding window over a stream; signals drift when the mean of the recent sub-window diverges significantly from the older sub-window.
  - Without drift detection and adaptation, classifiers on non-stationary streams degrade to random performance.
  - Time-based forgetting (discarding observations older than a window) is the simplest drift-adaptive strategy.
- **Mapping to mechanism:** The 7-day forced escalation is a hard time-based forgetting gate: if no signal has arrived to update the window, the model is assumed stale and the system falls back to safe behavior. ADWIN's statistical machinery is not implemented — the proxy uses a simpler heuristic trigger — but the underlying motivation is identical: accumulated confidence becomes unreliable without recent signal.

**Gama, J., Žliobaitė, I., Bifet, A., Pechenizkiy, M. & Bouchachia, A. (2014). A survey on concept drift adaptation.**
- **Venue:** ACM Computing Surveys, 46(4), Article 44.
- **URL:** https://dl.acm.org/doi/10.1145/2523813
- **Key findings:**
  - Categorizes drift types: sudden, gradual, incremental, recurring.
  - Human preference drift is typically gradual or recurring — making it harder to detect than sudden shifts.
  - Time-based forgetting (sliding windows, exponential weighting) is well-validated for gradual drift.
- **Mapping to mechanism:** The 7-day staleness guard addresses gradual preference drift specifically. The survey provides theoretical grounding for why periodic forced re-calibration is necessary even when no obvious failure has been observed.

### Supporting lineage (memory decay angle)

**Wei, L., Peng, X., Dong, X., Xie, N. & Wang, B. (2026). FadeMem: Biologically-Inspired Forgetting for Efficient Agent Memory.**
- **Venue:** arXiv:2601.18642 (preprint, January 2026). No peer-reviewed venue yet.
- **URL:** https://arxiv.org/abs/2601.18642
- **Key findings:**
  - Implements exponential decay for agent memories; memories accessed more recently or more frequently decay more slowly.
  - After 30 days without access, even important memories degrade significantly under the biologically-inspired model.
  - This paper is a preprint; treat as supporting evidence, not confirmed result.
- **Mapping to mechanism:** FadeMem provides a memory-systems framing for the same intuition: agent confidence about human preferences should decay over time, not remain static. The 7-day trigger is a sharp version of what FadeMem models as a continuous decay process. The paper is recent enough that it could not have informed the original design, but it validates the concept.

---

## 6. Adjustable / Sliding Autonomy Paradigm

**Mechanism:** The overall paradigm — a system that earns autonomy through demonstrated competence rather than being granted it upfront.

### Foundational papers

**Sheridan, T.B. & Verplank, W.L. (1978). Human and Computer Control of Undersea Teleoperators.**
- **Venue:** MIT Man-Machine Systems Laboratory Technical Report. (Widely cited as the origin of the levels-of-automation taxonomy.)
- **URL:** https://www.semanticscholar.org/paper/Human-and-Computer-Control-of-Undersea-Sheridan-Verplank/d48b94e6af5093e7cc41e20fa6aca4f3a2d860bb
- **Key findings:**
  - Established a 10-level scale from "operator does it all" to "computer acts entirely autonomously."
  - Level 5: computer executes if operator approves. Level 6: computer executes, operator can veto. Levels 5–6 correspond exactly to the proxy's threshold-based auto-approve behavior.
  - Supervisory control is the default framing: human as monitor and exception-handler rather than direct operator.
- **Mapping to mechanism:** The proxy implements a dynamic version of Sheridan's levels 5–6 that slides between them based on demonstrated competence. When confidence is low the system operates at level 5 (awaits approval); when confidence is high it operates at level 6 (acts, human could veto in principle). Sheridan's original work is the conceptual ancestor.

**Parasuraman, R., Sheridan, T.B. & Wickens, C.D. (2000). A model for types and levels of human interaction with automation.**
- **Venue:** IEEE Transactions on Systems, Man, and Cybernetics — Part A: Systems and Humans, 30(3), 286–297.
- **URL:** https://pubmed.ncbi.nlm.nih.gov/11760769/
- **Key findings:**
  - Refines the Sheridan-Verplank taxonomy into a 2D framework: type of automated function (information acquisition, information analysis, decision/action selection, action implementation) × level of automation.
  - Argues that the appropriate level of automation depends on the cost of human error, the reliability of the automation, and the human's monitoring ability.
  - Misuse (over-trust) and disuse (under-trust) of automation are both failure modes; appropriate reliance is the design goal.
- **Mapping to mechanism:** The proxy's escalation policy explicitly targets appropriate reliance: auto-approve when the agent has been reliable (prevent disuse / over-escalation), escalate when uncertain (prevent misuse / rubber-stamping). The Parasuraman et al. framework provides the vocabulary and the justification that both failure modes matter.

**Dorais, G., Bonasso, R.P., Kortenkamp, D., Pell, B. & Schreckenghost, D. (1999). Adjustable autonomy for human-centered autonomous systems on Mars.**
- **Venue:** Proceedings of the AAAI Spring Symposium on Agents with Adjustable Autonomy (AAAI Technical Report SS-99-06), 1999. (The initial version was presented at the Mars Society Conference, 1998.)
- **URL:** https://www.researchgate.net/publication/2859426_Adjustable_Autonomy_for_Human-Centered_Autonomous_Systems_on_Mars
- **Key findings:**
  - Coined "adjustable autonomy" as the design principle that systems should vary their autonomy level based on task context and operator workload.
  - Proposed that the agent, not just the operator, should be able to request changes in autonomy level.
  - Sliding autonomy: autonomy adjusts continuously rather than in discrete operator-configured steps.
- **Mapping to mechanism:** The proxy is an implementation of adjustable autonomy applied to AI agent task approval: the system slides autonomy level dynamically based on accumulated performance evidence. Dorais et al. is the foundational paper for this design pattern.

**Basich et al. (2020) — same citation as mechanism 2.**
- **Key additional finding:** Provides the missing link between the classic adjustable autonomy literature (which focused on operator workload and task type) and the learning-from-experience framing (autonomy earned through demonstrated competence). The CAS model is the closest peer-reviewed precedent for the proxy's EMA-based autonomy earning approach.

---

## 7. The Autonomy-Oversight Dilemma

**Mechanism framing:** "Every autonomous agent faces a continuous choice: act or ask. Both carry risk."

### Assessment

This framing is a synthesis, not a direct citation from a single paper. The specific phrasing does not appear to originate from a single identifiable paper. However, it has clear intellectual ancestors:

**Horvitz, E. (1999). Principles of mixed-initiative user interfaces.**
- **Venue:** Proceedings of CHI '99 — ACM SIGCHI Conference on Human Factors in Computing Systems, Pittsburgh, PA, May 1999, pp. 159–166.
- **URL:** https://dl.acm.org/doi/10.1145/302979.303030 / PDF: https://erichorvitz.com/chi99horvitz.pdf
- **Key findings:**
  - Formalizes the expected-utility framework for deciding whether to act autonomously or ask the user: take the action with highest expected utility given the costs of autonomous action (if wrong) and the costs of interruption (if asking was unnecessary).
  - "The expected utility of taking autonomous action depends on how well the system can infer the user's goals."
  - Both acting wrongly and asking unnecessarily have costs; the design problem is minimizing total expected cost.
- **Mapping to mechanism:** Horvitz (1999) is the closest single paper to the "act or ask" framing. The proxy's escalation logic is an implementation of Horvitz's expected-utility decision: when EMA is high, act; when low, ask. The 3x asymmetric weighting on corrections encodes the domain-specific costs that go into Horvitz's utility calculation.

**Crandall, J.W. & Goodrich, M.A. (2002). Principles of adjustable interactions.**
- **Venue:** Proceedings of the AAAI Fall Symposium on Human-Robot Interaction, 2002.
- **URL:** https://cdn.aaai.org/Symposia/Fall/2002/FS-02-03/FS02-03-005.pdf
- **Key findings:**
  - Explicitly articulates the dilemma: acting autonomously risks task failure; asking risks operator overload and workflow disruption. Both are costs.
  - Proposes that the system should continuously evaluate which risk dominates.
- **Mapping to mechanism:** This paper directly names the act-or-ask dilemma in the HRI context. The proxy operationalizes this continuous evaluation via the EMA threshold with asymmetric weighting.

**Summary:** The "act or ask, both carry risk" framing is a synthesis of the above bodies of work. It is not fabricated — it accurately represents a core tension identified in multiple papers — but it is not a verbatim formulation from a single source. The closest single source is Horvitz (1999).

---

## 8. Learning from Dialog Patterns, Not Just Gate Decisions

**Mechanism:** A human's questions during review ("where is the rollback plan?") reveal what they scrutinize, as valuable as approve/reject decisions.

### Primary lineage

**Joachims, T. (2002). Optimizing search engines using clickthrough data.**
- **Venue:** Proceedings of the 8th ACM SIGKDD International Conference on Knowledge Discovery and Data Mining, Edmonton, Alberta, July 2002, pp. 133–142.
- **URL:** https://dl.acm.org/doi/10.1145/775047.775067
- **Key findings:**
  - Clickthrough data (which results users clicked) encodes implicit relevance judgments. Users do not rate results explicitly, but their navigation behavior reveals preference.
  - Implicit signals (click patterns, skip patterns) are noisier than explicit ratings but vastly cheaper to collect and can be collected at scale.
  - Relative preferences (A clicked but B skipped) are more reliable signals than absolute ones.
- **Mapping to mechanism:** A human's questions during review are implicit signals about what attributes they consider important. The proxy should treat "asked about rollback plan" as an implicit signal that rollback-plan presence is a scrutinized attribute for this human, analogous to a clickthrough signal in search. Joachims's work is the conceptual ancestor; this is an adaptation of the implicit feedback framing to a dialogue context.

**Pang, R.Y., Roller, S., Cho, K., He, H. & Weston, J. (2023/2024). Leveraging implicit feedback from deployment data in dialogue.**
- **Venue:** EACL 2024 (short paper). arXiv:2307.14117.
- **URL:** https://arxiv.org/abs/2307.14117 / https://aclanthology.org/2024.eacl-short.8/
- **Key findings:**
  - User response characteristics (length, sentiment, follow-up questions) in deployed dialogue systems encode implicit quality signals.
  - Learning from these implicit signals — without extra annotation — improves dialogue agent quality.
  - Follow-up question type and content are particularly informative about what the prior system turn failed to address.
- **Mapping to mechanism:** This is the closest peer-reviewed paper to the specific mechanism described: inferring what humans scrutinize from the nature of their follow-up questions during review, not just from their binary approve/reject signal. The paper is recent (2023) and addresses the dialogue setting directly. This supports the mechanism as a direct extension of established implicit-feedback research into the human-proxy-agent review loop.

**Grice, H.P. (1975). Logic and conversation.**
- **Venue:** In P. Cole & J. Morgan (Eds.), Syntax and Semantics, Vol. 3: Speech Acts, pp. 41–58. Academic Press.
- **URL:** https://lawandlogic.org/wp-content/uploads/2018/07/grice1975logic-and-conversation.pdf
- **Key findings:**
  - The Cooperative Principle and Quantity maxim: speakers say what is necessary; questions asked reveal what information is missing from the interlocutor's model.
  - Conversational implicature: what a speaker asks for implicates what they consider necessary but absent.
- **Mapping to mechanism:** When a human asks "where is the rollback plan?" during review, the Gricean maxim of Quantity implies they consider rollback plan presence necessary information not present in the agent's output. The proxy can treat question content as evidence about what the human's acceptance criteria include. Grice provides a linguistic theory grounding for why questions are informative about unstated requirements — the mechanism is a computational realization of this insight. This is an adaptation, not a direct implementation.

---

## Summary Table

| Mechanism | Research Field | Best Citation(s) | Implementation Type |
|-----------|----------------|------------------|---------------------|
| EMA confidence tracking | Human-machine trust dynamics | Lee & Moray (1992, 1994) | Direct conceptual implementation |
| Asymmetric regret (3x) | Decision theory + adjustable autonomy | Savage (1951); Basich et al. (2020) | Adaptation (fixed weights vs. minimax or learned parameters) |
| Exploration rate (15%) | Reinforcement learning / bandit theory | Auer et al. (2002); Sutton & Barto (2018) | Direct implementation of epsilon-greedy |
| Cold start (n<5) | Recommender systems | Schein et al. (2002) | Adaptation (concept borrowed, threshold is design choice) |
| Staleness guard (7 days) | Concept drift / non-stationary ML | Bifet & Gavalda (2007); Gama et al. (2014) | Simplified implementation (heuristic trigger vs. statistical test) |
| Adjustable autonomy paradigm | HRI / human factors | Sheridan & Verplank (1978); Parasuraman et al. (2000); Dorais et al. (1999); Basich et al. (2020) | Direct implementation of established paradigm |
| Act-or-ask dilemma | Mixed-initiative HCI | Horvitz (1999); Crandall & Goodrich (2002) | Synthesis of multiple sources; closest single source is Horvitz (1999) |
| Learning from dialog patterns | Implicit feedback / dialogue systems | Joachims (2002); Pang et al. (2023); Grice (1975) | Adaptation of implicit feedback research to dialogue review context |

---

## Confidence Assessment

**High confidence (well-established citation, verified):**
- Lee & Moray (1992, 1994) — ARMAV trust model
- Parasuraman, Sheridan & Wickens (2000) — automation levels
- Auer, Cesa-Bianchi & Fischer (2002) — bandit exploration
- Horvitz (1999) — mixed-initiative / act-or-ask
- Joachims (2002) — implicit feedback from clickthrough
- Basich et al. (2020) — competence-aware autonomy (AAMAS 2020, verified)

**Medium confidence (paper exists, mapping is plausible but indirect):**
- Sheridan & Verplank (1978) — levels of automation; original 1978 tech report; cited widely but not directly accessible
- Dorais et al. (1999) — adjustable autonomy for Mars; AAAI symposium proceedings, not a full conference paper
- Savage (1951) — minimax regret; naming connection is clear, mathematical mapping is loose
- Schein et al. (2002) — cold start; concept is right, specific n=5 threshold is not from this paper

**Lower confidence (recent preprint or indirect mapping):**
- FadeMem (Wei et al., 2026) — preprint only, supporting rather than foundational
- Pang et al. (2023/2024) — EACL short paper; closest match for dialog-pattern learning but does not address the proxy review loop specifically
- Grice (1975) — correct as linguistic foundation; adaptation to proxy learning is novel, not established in the literature

**Cannot confirm (not found):**
- No single paper found that coins the exact phrase "act or ask, both carry risk" as its central formulation. This is a synthesis.
- The specific choice of alpha=0.3 and n=5 and 7-day window and 15% exploration rate does not appear to be derived from any specific paper; these are design parameters informed by the general research directions above.
