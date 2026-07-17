# RECENT_RESEARCH.md — 2026 H1 Literature Scan for the GitHub-Bus Branch

**Purpose.** This file lives on the `claude/teaparty-message-bus-proxy-aa4ik3` branch so that
work on the GitHub-bus + proxy-as-subscriber proposal
(`docs/proposals/github-bus/proposal.md`) can cite recent evidence directly. It details — per
paper, with links, verified claims, corrections, and confidence — everything found in a
literature scan of the last six months.

**Scope:** papers whose first public appearance (arXiv v1 or venue publication) falls between
**2026-01-15 and 2026-07-17**, across four areas: multi-agent systems, human/AI collaboration,
learning human preferences and behaviors, and memory architectures. Every candidate was screened
for relevance to a *specific* TeaParty mechanism and classified as **SUPPORT** (evidence for our
approach), **REFUTE** (evidence against it), or **IMPROVE** (something we could adopt). Papers
already in `docs/research/INDEX.md` were excluded.

**Method and verification caveat.** Five parallel search passes (multi-agent coordination,
human-AI collaboration, preference learning, memory architectures, and protocol/planning
critiques) produced 46 candidates. A second, adversarial pass then attempted to *refute* every
candidate: existence, v1 date inside the window, accuracy of every quoted number, honesty of the
claimed relevance, and duplication against INDEX.md. Results: 36 confirmed, 8 corrected (kept,
with corrections applied below), 1 rejected on date, 1 retained at footnote strength.
One limitation: direct fetches to arxiv.org are egress-blocked in the environment where this scan
ran, so verification relied on multiple independent search-index snapshots of the arXiv abstract
pages plus secondary sources (GitHub repos, project sites, venue pages, author homepages) rather
than byte-exact abstract text. Confidence is noted per entry; spot-check quoted numbers against
the actual PDFs before citing them in publications.

---

## How this maps onto the proposal

Detailed mapping from findings to `docs/proposals/github-bus/proposal.md`, section by section.
Paper references (§n.m) point into the catalog in this file.

### Proposal §1 — "Why this exists" (delete the runtime, keep the bus and the proxy)

- **Directly supporting evidence:** §5.1 (Dennis et al.) is a controlled comparison in which an
  external LangGraph-style orchestrator injecting routing instructions loses to putting the whole
  procedure in the system prompt: quality 4.53–5.00 vs 4.17–4.84, orchestrator failure rates
  24%/9%/17% vs 11.5%/0.5%/5% across three domains, and 1.2× more LLM calls. The in-context arm
  is structurally identical to "CfA becomes a SKILL.md." Cite it with its limits: LangGraph-only
  head-to-head, LLM-as-judge scoring, in-context uses *more tokens* per conversation (68K vs 43K
  in one domain), and procedural customer-service domains rather than coding.
- §1.6 (Coordination as an Architectural Layer) states the same thesis generally: most production
  MAS failures are coordination defects, and the coordination substrate should be a configurable
  layer separated from agent logic — which is exactly what extracting the bus does. Directional
  support only (prediction-market experiments, two-author preprint).
- **Tension to note in the proposal:** §1.2 (Tran & Kiela) argues from the Data Processing
  Inequality that every inter-agent message boundary can only lose information, and shows
  single agents matching MAS under equal token budgets on multi-hop QA. The proposal's claim
  that the harness's hierarchical dispatch suffices should acknowledge this: the burden of proof
  is on showing coordination structure pays for its information loss on tasks where coordination
  is structurally necessary — see §1.1 (CooperBench) for the ready-made instrument.

### Proposal §4 — Message envelope

- §1.5 (Message Sequence Charts) is the natural formal upgrade: the envelope defines message
  *format* (`from`, `to`, `kind`, `reply_to`, `thread`) but nothing constrains *conversation
  structure*. An MSC-style spec of the legal exchanges (question→answer, task→status→escalation,
  plan→approve→execute, escalation round-trips) compiled per-participant would give
  deadlock-freedom — no thread where the proxy and a worker each wait on the other — instead of
  relying on skill-document convention. Formal-methods strength only; no empirical MAS evaluation.
- §1.8 (ProACT) adds the complementary runtime capability: detecting when a thread itself has
  broken down (lost common ground, conflicting commitments) and deciding silence vs. targeted
  intervention — a role neither the envelope nor the proxy currently owns.

### Proposal §5–6 — Identity, addressing, subscription

- §1.7 (Harness-MU) is the load-bearing citation for the multi-user design: authorization,
  restriction, and precedence between principals are "deterministic runtime variables that
  should be enforced by execution hooks rather than entrusted to the LLM," with prompt-based
  safeguards failing under multi-turn adversarial interaction. Concretely: who may author `from:
  proxy:<human>`, whose instructions take precedence in a thread, and what a worker agent may
  read across teams must be enforced by the bus adapter / GitHub permissions — never by asking
  the proxy to behave.
- The rejected-but-relevant A2H protocol (see §6 of this file) is convergent evolution — humans
  as addressable first-class nodes with a formal schema for when/why/how an agent contacts a
  human — and worth reading despite falling 15 days outside the window.

### Proposal §7 — The proxy as a subscriber

- **The loop is being validated elsewhere:** §3.1 (PAHF, Meta) operationalizes the same
  decomposition — pre-action clarification when ambiguous, actions grounded in per-user
  preference memory, post-action feedback integrated on drift.
- **Delegation beats advice when granted:** §2.4 (Choose Your Agent) — only the autonomous
  Delegate raised collective surplus (~1.5×, suggestive), yet participants preferred the
  high-control Advisor 44% to 19%. That preference-performance misalignment is the argument for
  autonomy *earned through demonstrated alignment* rather than configured.
- **Sober baselines for answering-as-the-human:** §3.5 (PrivacySIM: best persona-prompted
  frontier model hits only 40.4% on individuals' actual decisions), §3.6 (OmniBehavior: models
  average away individual differences and plateau with more context), §2.2 (PICon: persona
  agents contradict themselves under chained interrogation). None of these test
  observation-driven delta learning — they test persona prompting — so they define the baseline
  the proxy must beat and argue for conservative cold-start confidence thresholds.
- **Escalation quality is measurable:** §2.8 (HiL-Bench's Ask-F1: question precision × blocker
  recall) and §2.9 (Information-Gain-selected clarification: +3.7% success at +0.3 turns) give
  the proxy's decide-step a metric and a question-selection criterion. §2.3 (Alibaba field
  experiment) shows escalation-to-human recovers quality only when it arrives at the right time
  with enough context — which constrains what an `@mention` escalation must carry.
- **Learning-step upgrades:** §3.7 (population priors + correlation-aware questions for cold
  start), §3.9 (update-on-surprise instead of time-based staleness), §3.8 (TRACE: compile
  high-confidence preferences into hard checks — memory-recall alone left 57.5% of applicable
  preference checks violated), §3.10 (HorizonBench: ground-truth drift benchmark).

### Proposal §9 — Open questions / risks (this class of risk is understated)

The proposal's risk list covers rate limits, latency, access, secret hygiene, ordering, and
non-GitHub humans. The scan surfaced a *security* class the list does not name:

- **Clarification as attack surface:** §2.1 (ASPI) — across 728 scenarios and ten frontier
  models, entering a clarification-seeking state amplifies prompt-injection success by an order
  of magnitude (1.8%→34.0% for o3). On a bus where anyone with repo access can reply to the
  proxy's question, the intake dialog is the injection channel. Clarification replies must be
  treated as untrusted input; identity of the answerer matters as much as content.
- **The approved plan as a commit-before-exposure boundary:** §5.4 (Plan-Then-Execute) — a plan
  committed *before* the agent observes untrusted content confines injection to influencing
  values, not redefining the task. CfA's backtracks deliberately reopen plans mid-execution;
  the reconciliation is an authorization rule: only trusted principals (human, proxy) may
  trigger a backtrack — never content arriving on the thread.
- **Reviewer context rot:** §5.8 (Classifier Context Rot) — models monitoring long transcripts
  miss dangerous actions 2×–30× more often after ~800K benign tokens; §2.10 shows trace
  presentation can raise reviewer *confidence without accuracy*. Gate/review artifacts posted to
  threads should be compressed and structured, not raw transcripts.

### Proposal §10 — Phased plan

- **Phase 1 (bus core):** apply §1.7's deterministic-hooks principle in the adapter; consider
  §1.5's MSC specs for the envelope conversation grammar.
- **Phase 2 (proxy subscriber):** adopt Ask-F1 (§2.8) as the escalation metric from day one;
  treat clarification replies as untrusted (§2.1); design `@mention` escalations to carry
  failure-type and context per §2.3.
- **Phase 3 (teardown):** cite §5.1 and §1.6 as the evidence base; keep §1.2's compute-
  normalization critique in mind for any before/after comparison.
- **Phase 4 (CfA as a skill):** §5.1 is the direct precedent; §5.5 and §5.7 suggest the ten
  coarse backtracks may want a cheapest-sufficient-recovery routing rule and possibly finer
  granularity.
- **Validation of the whole bet:** run CooperBench-style paired-agent tasks (§1.1) over the bus;
  the published baseline is ~30% *worse* than solo — beating it is the demonstration that the
  bus + envelopes + proxy earn their complexity.

---

## Priority reads

If you read only ten, read these — each one bears directly on a live design decision:

1. **In-Context Prompting Obsoletes Agent Orchestration** (§5.1) — the closest published evidence
   for the fable-branch "delete the CfA state machine, keep CfA as a skill" move.
2. **ASPI** (§2.1) — negative result: clarification-seeking states amplify prompt-injection risk;
   acute for intake dialogs running over a world-writable GitHub-issues bus.
3. **CooperBench** (§1.1) — the "curse of coordination": naive agent pairs do ~30% *worse* than
   solo; the benchmark to beat to prove the bus + envelope protocol earns its keep.
4. **CAID** (§1.4) — the counterweight: structured async collaboration (isolated workspaces,
   dependency-aware delegation, verified integration) beats single agents.
5. **PAHF** (§3.1) — Meta independently operationalizes almost exactly the proxy loop
   (clarify → retrieve per-user preferences → integrate feedback).
6. **Single-Agent vs MAS under equal token budgets** (§1.2) — information-theoretic challenge to
   liaison compression; our hierarchical-vs-flat ablations must normalize compute.
7. **HiL-Bench** (§2.8) — Ask-F1, a directly adoptable metric for proxy escalation quality.
8. **PrivacySIM** (§3.5) — sober baseline: the best persona-prompted frontier model predicts
   individuals' decisions at only 40.4%; per-individual observation data is not optional.
9. **SkillLens** (§4.5) — unguided LLM judges are anti-predictive when validating distilled
   skills; promotion gates need outcome-based or rubric-guided validation.
10. **Harness-MU** (§1.7) — multi-user governance (authorization, precedence) must be enforced by
    deterministic hooks at the bus layer, never delegated to agent judgment.

---

## 1. Multi-agent coordination and communication substrates

### 1.1 CooperBench: Why Coding Agents Cannot be Your Teammates Yet
Khatua et al. (Stanford, SAP Labs). arXiv:2601.13295, v1 2026-01-19.
<https://arxiv.org/abs/2601.13295>
**REFUTE** (and an evaluation asset). 652 two-agent collaborative coding tasks across 12
libraries and 4 languages; SOTA agents average ~30% *lower* success collaborating than doing both
tasks solo — the "curse of coordination." This attacks the core bet that message-coordinated
agent teams outperform, and it targets exactly the regime the GitHub bus is for (concurrent work,
late conflict discovery). Read it as a motivating challenge rather than a fatal one: it tests
*unstructured* peer pairs, which is the failure mode our protocol claims to fix — making it the
obvious instrument for demonstrating that the bus + envelopes beat unstructured coordination.
*Verified: task count, languages, 30% figure, "curse of coordination" phrasing. High confidence.*

### 1.2 Single-Agent LLMs Outperform Multi-Agent Systems on Multi-Hop Reasoning Under Equal Thinking Token Budgets
Tran & Kiela (Stanford). arXiv:2604.02460, v1 April 2026 (exact day unresolved: Apr 2 vs Apr 11).
<https://arxiv.org/abs/2604.02460>
**REFUTE.** With thinking-token budgets held constant, single agents match or beat multi-agent
systems across Qwen3, DeepSeek-R1-Distill, and Gemini 2.5; a Data Processing Inequality argument
holds that every inter-agent message boundary can only lose information. This challenges the
liaison-compression pillar specifically — liaisons are deliberate information bottlenecks — and
implies our hierarchical-vs-flat ablations are only meaningful under normalized token budgets.
Scope caveat: multi-hop QA, not long-horizon multi-file work where context rot dominates; the
refutation reaches our setting only by extrapolation.
*Verified: models, budget-matched design, DPI argument. High confidence.*

### 1.3 The Illusion of Multi-Agent Advantage
Jwalapuram et al. arXiv:2606.13003, v1 2026-06-11.
<https://arxiv.org/abs/2606.13003>
**REFUTE — but of *automated* MAS design, not ours.** Audits automatically generated multi-agent
workflows (from 3 generator models across 5 datasets): 7 of 14 collapse to a structure
functionally identical to CoT self-consistency, four underperform the plain CoT-SC baseline, at
~10× cost. The adversarial pass corrected the original framing: the paper explicitly finds
*expert-architected* MAS outperforms auto-generated MAS, so it is a methodological warning rather
than a refutation of hand-designed architectures — multi-agent-advantage claims must come from
benchmarks that structurally stress coordination, or they're evaluation artifacts.
*Corrected in review: "audits 6 frameworks" was unverified; scope narrowed as above. High confidence on the numbers.*

### 1.4 Effective Strategies for Asynchronous Software Engineering Agents (CAID)
Geng & Neubig (CMU). arXiv:2603.21489, v1 2026-03-23.
<https://arxiv.org/abs/2603.21489>
**SUPPORT.** Unstructured concurrent editing fails (interfering edits, unsynchronized
dependencies); CAID — centralized dependency-aware delegation, asynchronous execution, isolated
workspaces, test-verified structured integration — beats single-agent baselines by **+26.7%** on
PaperBench and **+14.3%** on Commit0 (the adversarial pass corrected the initially quoted
+25.6%/+14.7%). The closest empirical validation of the uber-team/isolated-subteam architecture,
and its thesis — borrow humanity's mature software-collaboration infrastructure — is precisely
the fable-branch GitHub-bus argument. The strongest counterweight to §1.1–1.3: async multi-agent
*does* help when the coordination substrate is structured.
*Verified: architecture, corrected numbers, GitHub repo, OpenHands writeup. High confidence.*

### 1.5 Provable Coordination for LLM Agents via Message Sequence Charts
Bollig, Függer, Nowak (Paris-Saclay/CNRS/ENS). arXiv:2604.17612, v1 2026-04-19.
<https://arxiv.org/abs/2604.17612>
**IMPROVE.** A DSL specifying coordination as message sequence charts, with syntax-directed
projection compiling a global spec into deadlock-free local agent programs, independent of LLM
nondeterminism. Our envelopes define message *format* but not *conversation structure*; MSC-style
specs for CfA exchanges over the bus (request → plan → approve → execute; escalation round-trips)
would give deadlock-freedom guarantees — e.g., no thread where proxy and subteam each wait on the
other — instead of relying on skill-document convention. Formal-methods paper, small worked
example, no empirical MAS evaluation: design-inspiration strength.
*Corrected in review: v1 is Apr 19, not Apr 29 (that's v2). High confidence.*

### 1.6 Coordination as an Architectural Layer for LLM-Based Multi-Agent Systems
Nechepurenko & Shuvalov. arXiv:2605.03310, v1 2026-05-05.
<https://arxiv.org/abs/2605.03310>
**SUPPORT** (directional). Argues production MAS failures (citing 41–87% rates from prior work)
are mostly coordination defects, not model-capability defects, and that coordination should be a
configurable architectural layer separable from agent logic. This is the fable-branch thesis
stated as a general principle: pull the coordination substrate out of the agent runtime. Caveats:
the empirical study is on prediction-market tasks (information-controlled simulation, not
software teams), and it's a two-author preprint — directional support, not domain-matched
evidence.
*Verified: failure-rate attribution (cited, not measured), layer taxonomy. High confidence.*

### 1.7 Harness-MU: A Safe, Governed, and Effective Harness for Multi-User LLM Agents
Fan, Nie, Dai. arXiv:2606.21856, v1 2026-06-20.
<https://arxiv.org/abs/2606.21856>
**IMPROVE.** For multi-user, multi-principal agents, governance constraints — who is authorized,
what is restricted, whose instructions take precedence — are "deterministic runtime variables
that should be enforced by execution hooks rather than entrusted to the LLM," because
prompt-based safeguards fail under multi-turn adversarial interaction (verified: full privacy
preservation across access-control attacks on Muses-Bench; up to +48.9pp instruction-following).
The bus is explicitly multi-user: envelope routing, label-based access, and precedence between
humans' instructions should be enforced mechanically at the bus/hook layer, never by the proxy's
judgment. Directly applicable to Phase 1–2 of the GitHub-bus plan.
*Verified: core claim verbatim, benchmark results. High confidence.*

### 1.8 ProACT: Towards Breakdown-Aware Proactive Agent in Multi-User Collaboration
Yang, Xu, Pei, Wang (KAUST, Stanford). arXiv:2607.03730, v1 early July 2026.
<https://arxiv.org/abs/2607.03730>
**IMPROVE.** An agent embedded in multi-user conversation that detects collaboration breakdowns
(grounded in common-ground theory), chooses silence vs. targeted intervention, and improves
appropriateness/non-interruptiveness across five backbones. Orthogonal to the proxy's
act-or-escalate dial: this is noticing when a bus *thread itself* is breaking down (lost common
ground, conflicting commitments) and intervening. Its multi-user benchmark is a candidate for
evaluating proxy interventions without annoying participants.
*Caveat from review: the "3,244 turn-level examples" count could not be corroborated (and beware
conflation with the unrelated ProAct-75, arXiv:2602.03430). Medium-high confidence otherwise.*

---

## 2. Human/AI collaboration and oversight

### 2.1 ASPI: Seeking Ambiguity Clarification Amplifies Prompt Injection Vulnerability in LLM Agents
Sehwag et al. (Scale AI). arXiv:2605.17324, v1 2026-05-17.
<https://arxiv.org/abs/2605.17324> · code: <https://github.com/scaleapi/aspi>
**REFUTE** (security-scoped). Across 728 task-attack scenarios and ten frontier LLMs, entering a
clarification-seeking state consistently and substantially amplifies prompt-injection success
(e.g., 1.8% → 34.0% for o3; 2.2% → 35.7% for Gemini-3-Flash). Found independently by two search
passes; all numbers verified. The adversarial pass qualified the framing: this does not refute
the task-performance value of intake dialogs among trusted humans — it shows the *asking state*
opens an injection channel. For TeaParty it matters doubly: the GitHub bus makes clarification
threads world-writable, so the proxy's question-asking state is an attack surface unless
clarification replies are treated as untrusted input. Read together with §1.7.
*Verified: all figures, repo, HF dataset, AgentDojo extension. High confidence.*

### 2.2 PICon: A Multi-Turn Interrogation Framework for Evaluating Persona Agent Consistency
Kim et al. (KAIST). arXiv:2603.25620, v1 2026-03-26.
<https://arxiv.org/abs/2603.25620>
**REFUTE** (cautionary). Logically chained multi-turn interrogation of persona agents used as
"scalable proxies for human participants": all tested systems (7–8, version-dependent) fall below
the human baseline of 63 real participants on consistency. Cautions that an agent answering *as*
a person can contradict itself across a long thread — relevant to @proxy-marked answers spanning
weeks of bus history. The adversarial pass downgraded two attributed claims ("contradictions only
surface when 3+ statements jointly checked"; "structural, not situational") as unverified, and
noted the scope gap: PICon tests role-play personas, not prediction models learning from deltas.
Its chained-interrogation method is reusable as a proxy-fidelity stress test.
*Corrected in review as above. Medium-high confidence.*

### 2.3 Agentic AI and Human-in-the-Loop Interventions: Field Experimental Evidence from Alibaba's Customer Service Operations
Wang, Zhu, Feng, Lu, Jia. arXiv:2605.14830, v1 May 2026.
<https://arxiv.org/abs/2605.14830>
**REFUTE** (mixed). Randomized field experiment on Taobao (647 workers, ~680K chats): agentic AI
cut chat duration but substantially lowered customer ratings on AI-handled chats, and human
intervention helped only conditionally — depending on failure type, post-escalation effort, and
timing. Rare *field* evidence that escalation-to-human is not a free safety net: the proxy's
escalations must arrive at the right time with enough context for the human to actually recover
the situation. Directly informs what an @mention escalation should carry with it.
*Verified: experiment design, direction of effects, secondary press coverage. High confidence.*

### 2.4 Choose Your Agent: Tradeoffs in Adopting AI Advisors, Coaches, and Delegates in Multi-Party Negotiation
Zhu et al. (Harvard, Google DeepMind). arXiv:2602.12089, v1 2026-02-12.
<https://arxiv.org/abs/2602.12089>
**SUPPORT.** Behavioral experiment (N=243, three-party bargaining): only the autonomous
*Delegate* — the AI acting as the human — significantly increased collective surplus (suggestive
~1.5× individual welfare after adjusting for non-compliance), yet participants preferred the
high-control Advisor (44%) over the Delegate (19%). Supports the proxy bet (delegation beats
advice) and names the "preference-performance misalignment" that motivates earning autonomy
through demonstrated alignment rather than configuration. The mechanism — humans filtering AI
proposals destroys surplus — is the interesting part.
*Verified: all figures; the 1.5× is the paper's own "suggestive" estimate — keep the hedge. High confidence.*

### 2.5 Intelligent AI Delegation
Tomašev, Franklin, Osindero (Google DeepMind). arXiv:2602.11865, v1 2026-02-12.
<https://arxiv.org/abs/2602.11865>
**SUPPORT** (framework, no empirics). Delegation as a decision sequence: transfer of authority
and accountability, explicit role boundaries, clarity of intent, trust established through
demonstrated performance, contract-first decomposition, verifiable completion. A frontier-lab
endorsement of the TeaParty stack — intent artifacts as delegation contracts — useful for
vocabulary and for designing the uber-team → subteam liaison boundary. It is a position paper:
cite for framing, not evidence.
*Verified: authors, date, framework content. High confidence.*

### 2.6 Human Oversight of Agentic Systems in Practice
Dhanorkar, Passi, Vorvoreanu. arXiv:2606.05391, v1 2026-06-03. (FAccT '26.)
<https://arxiv.org/abs/2606.05391>
**SUPPORT.** Interview study (17 experienced developers) identifying four forms of emergent
oversight work: a-priori control, co-planning, real-time monitoring, post-hoc review. Empirical
grounding for oversight as ongoing structured work rather than a binary autonomy dial — and the
catalog of real oversight heuristics is raw material for what the proxy should learn to imitate.
*Verified: study design, four forms, FAccT '26 listing. High confidence.*

### 2.7 When Users Change Their Mind: Evaluating Interruptible Agents in Long-Horizon Web Navigation
Zou et al. arXiv:2604.00892, v1 2026-04-01.
<https://arxiv.org/abs/2604.00892> · code: <https://github.com/HenryPengZou/InterruptBench>
**SUPPORT.** First systematic study of mid-execution user interruptions in long-horizon tasks,
formalizing three intent-change types — addition, revision, retraction — and showing interruption
handling remains hard for large LLMs. Validates the two most distinctive CfA claims: requests are
not complete specifications, and execution must survive intent itself changing. The taxonomy maps
onto CfA's backtrack transitions and could ground an ablative experiment. Domain gap: web
navigation, not software teams.
*Verified: taxonomy verbatim, benchmark repo. High confidence.*

### 2.8 HiL-Bench: Do Agents Know When to Ask for Help?
Trinh et al. arXiv:2604.09408, v1 2026-04-10.
<https://arxiv.org/abs/2604.09408>
**IMPROVE.** Benchmarks the act-vs-ask judgment with human-validated blockers (missing info 42%,
ambiguous 36%, contradictory 22%; 150 SWE-Bench-Pro + 150 BIRD tasks; 75–89% pass@3 with full
info vs 4–24% with blockers). **Ask-F1** — harmonic mean of question precision and blocker
recall — is a directly adoptable metric for the proxy's escalation decisions, complementing
asymmetric-regret weighting with a measurable over-asking vs. silent-guessing tradeoff.
*Verified: blocker taxonomy, metric definition, task counts. High confidence.*

### 2.9 Uncertainty-Aware Clarification in LLM Agents with Information Gain
Deng et al. arXiv:2606.03135, v1 2026-06-02. (ICML 2026.)
<https://arxiv.org/abs/2606.03135>
**IMPROVE.** Trains a clarifier with an Information Gain Reward — the Bayesian belief update
toward the ground-truth goal induced by each clarification exchange — yielding +3.7% task success
at only +0.3 interaction steps on τ-Bench across five backbones. A principled criterion for
*which* question the intake dialog should ask, and empirical ammunition against "clarification
dialogs annoy users without helping."
*Verified: reward design, figures, ICML acceptance, code repo. High confidence.*

### 2.10 Overseeing Agents Without Constant Oversight: Challenges and Opportunities
Grunde-McLaughlin, Mozannar, Murad, Chen, Amershi, Fourney (UW, Microsoft Research).
arXiv:2602.16844, v1 2026-02-18. <https://arxiv.org/abs/2602.16844>
**IMPROVE.** Three user studies on a computer-use agent: verbose raw traces cause reviewers to
miss small-but-impactful errors; alternative trace presentations sped up error-finding and raised
confidence **without improving accuracy** — itself a design warning (better UX can manufacture
false assurance). Directly applicable to what approval gates and @proxy threads show the human:
gate artifacts should follow these findings rather than dumping transcripts. Pairs with §5.8
(reviewer performance also degrades with transcript length).
*Verified: study structure, confidence-without-accuracy nuance. High confidence.*

---

## 3. Learning human preferences and behaviors

### 3.1 Learning Personalized Agents from Human Feedback (PAHF)
Liang et al. (Meta). arXiv:2602.16173, v1 2026-02-18.
<https://arxiv.org/abs/2602.16173> · code: <https://github.com/facebookresearch/PAHF>
**SUPPORT.** Operationalizes almost exactly the proxy loop: pre-action clarification when
ambiguous; grounding actions in preferences retrieved from explicit per-user memory; integrating
post-action feedback when preferences drift. Independent validation from a major lab that
explicit-memory + ask-when-uncertain + update-on-feedback is the right decomposition — mapping
directly onto the prospective/corrective learning moments and the proxy preference store.
*Verified: three-step loop verbatim, repo, Meta research page. High confidence.*

### 3.2 Ask or Assume? Uncertainty-Aware Clarification-Seeking in Coding Agents
Edwards & Schuster. arXiv:2603.26233, v1 2026-03-27.
<https://arxiv.org/abs/2603.26233>
**SUPPORT.** On an underspecified SWE-bench Verified variant, a clarification-seeking scaffold
lifts resolve rate 61.2% → 69.4% (OpenHands + Claude Sonnet 4.5), nearly closing the gap to
fully-specified instructions. Correction from the adversarial pass: the well-calibrated asking
behavior (conserving questions on simple tasks) belongs to *their uncertainty-aware scaffold*,
not to base models generally — which if anything strengthens the case for building the behavior
into a protocol rather than trusting the model. Found independently by two search passes.
*Verified: figures, scaffold attribution corrected. High confidence.*

### 3.3 Large Language Models Should Learn Personalized Rather Than Aggregated Human Preferences
Garbacea. arXiv:2606.07629, v1 2026-05-30 (June announcement cycle).
<https://arxiv.org/abs/2606.07629>
**SUPPORT** (position paper). Social-choice-theoretic argument that aggregating preferences into
one reward optimizes for an "average user" who represents no real person. The theoretical case
for a proxy of ONE human rather than population-level alignment; strengthens INDEX.md's existing
framing of RLHF/DPO as negative examples. Argument, not mechanism.
*Verified: author, thesis. High confidence.*

### 3.4 PersonaJudge: Simulating Individual Human Preference Judgments with Evaluator-Specific Demonstration Data
He et al. arXiv:2607.05742, v1 early July 2026 (day unconfirmed).
<https://arxiv.org/abs/2607.05742>
**SUPPORT.** Simulates *individual* (not consensus) preference judgments via in-context learning
over evaluator-specific demonstrations (categorical judgment + interface telemetry +
retrospective reasoning). Close kin to the proxy's prediction task: approval-gate decisions are
evaluator demonstrations. Review note: the demonstration-set *size* ("small") is unverified.
*Medium confidence overall (recent posting; day unpinned).*

### 3.5 PrivacySIM: Evaluating LLM Simulation of User Privacy Behavior
Flemings & Annavaram. arXiv:2605.12147, v1 2026-05-12.
<https://arxiv.org/abs/2605.12147>
**REFUTE.** Nine frontier LLMs vs. ground-truth decisions of 1,000 real users (from five
published privacy studies): the best persona-conditioned model reaches only **40.4%** accuracy
matching individual decisions; stated attitudes diverge from actual behavior. A direct challenge
to proxy prediction of judgment calls — and in exactly the high-stakes category where asymmetric
regret says false approvals cost most. Read as: persona *prompting* is insufficient;
per-individual observation-driven learning (TeaParty's mechanism) is the necessary ingredient —
and cold-start confidence thresholds should be conservative.
*Verified: setup, 40.4%. High confidence.*

### 3.6 OmniBehavior: Benchmarking LLMs on Long-Horizon, Cross-Scenario, Heterogeneous Behavior Traces
Chen et al. arXiv:2604.08362, v1 2026-04-09.
<https://arxiv.org/abs/2604.08362> · code: <https://github.com/icip-cas/OmniBehavior>
**REFUTE** (domain-distant caution). User simulation from real longitudinal traces (200 users,
~3 months): LLMs converge toward a "positive average person," homogenize individual differences,
overestimate action probabilities, and — critically — **plateau even as context grows**. The
plateau challenges any assumption that accumulating more proxy history monotonically improves
prediction; the averaging bias is precisely what the per-individual delta signal must overcome.
Caveat: short-video platform behavior, not collaborator preference judgments.
*Verified: findings incl. plateau, corpus details, repo. High confidence.*

### 3.7 Pep: Cold-Start Personalization via Training-Free Priors from Structured World Models
Bose et al. arXiv:2602.15012, v1 2026-02-16.
<https://arxiv.org/abs/2602.15012>
**IMPROVE.** Frames cold start as routing: learn an offline population-level world model of
preference correlations, then do training-free Bayesian inference online to select maximally
informative questions and predict full preference profiles (80.8% vs 68.5% RL baseline, 3–5×
fewer interactions, ~10K params). A concrete upgrade path for the proxy's cold-start phase:
population priors + correlation-aware question selection instead of flat epsilon-exploration.
The adversarial pass pinned the flagged statistic: frontier models fail to ask appropriate
clarifying questions even when explicitly prompted, with **29% of elicitation attempts worsening
alignment vs. generic responses** — quote it in exactly that form.
*Verified: method, numbers, 29% statistic pinned. High confidence.*

### 3.8 TRACE: Compiling User Corrections into Runtime Enforcement for Coding Agents
("Getting Better at Working With You…") Zhou et al. (Notre Dame, IBM, Tencent).
arXiv:2606.13174, v1 2026-06-11. <https://arxiv.org/abs/2606.13174>
**IMPROVE** (and a partial challenge to memory-only designs). Mines corrections from chat,
rewrites them as atomic rules, and compiles them into runtime checks that must pass before task
completion. Key result: a Mem0-style memory still leaves **57.5%** of applicable preference
checks violated — passive retrieval (our proxy.md + ACT-R retrieval at gate time) demonstrably
under-enforces learned corrections. Suggests the corrective learning moment should *compile*
high-confidence preferences into hard gate checks, not only retrievable chunks. (TRACE =
Test-time Rule Acquisition and Compiled Enforcement; violations drop 100%→37.6% in-distribution,
100%→2.0% OOD.)
*Verified: 57.5%, enforcement results, companion repo. High confidence.*

### 3.9 SPRInG: Continual LLM Personalization via Selective Parametric Adaptation and Retrieval-Interpolated Generation
Kim & Kim. arXiv:2601.09974, v1 2026-01-15 (window boundary day; no earlier version found).
<https://arxiv.org/abs/2601.09974>
**IMPROVE.** Addresses the drift problem head-on: standard continual updating cannot distinguish
genuine preference shifts from transient context. Uses a likelihood-based novelty score to decide
*which* interactions warrant updating the user model — update on surprise (high prediction error)
rather than age. A principled alternative to the time-based staleness guard, and conceptually
adjacent to delta-as-signal: novelty scoring *is* prediction error. Note its solution is
parametric (adapters), not memory-file based — the criterion transfers, the mechanism doesn't
directly.
*Verified: method, boundary date. High confidence.*

### 3.10 HorizonBench: Long-Horizon Personalization with Evolving Preferences
Li et al. arXiv:2604.17283, v1 2026-04-19.
<https://arxiv.org/abs/2604.17283> · code: <https://github.com/stellalisy/HorizonBench>
**IMPROVE** (evaluation infrastructure). 4,245 items, 360 simulated users, 6-month histories
(~4,300 turns), where every preference *change* has ground-truth provenance. The missing
measurement instrument for staleness/drift guards: best of 25 frontier models scores 52.8%, and
failures preferentially select the *pre-evolution* preference — exactly the stale-preference
failure our decay parameters are meant to catch. Caveat: simulated users.
*Verified: statistics, provenance design, headline result. High confidence.*

---

## 4. Memory architectures and learning

### 4.1 Predictive Associative Memory: Retrieval Beyond Similarity Through Temporal Co-occurrence
Dury (single author). arXiv:2602.11322, v1 2026-02-11.
<https://arxiv.org/abs/2602.11322>
**SUPPORT** (footnote strength only). A JEPA-style predictor retrieving associatively reachable
states rather than nearest neighbors — the "retrieval should not be pure similarity" thesis. The
adversarial pass judged this the weakest tie in the scan: it's a trained neural predictor over
embedding streams, not agent memory; ACT-R's own spreading-activation literature (already in
act-r.md) covers the idea better. Keep as a one-line contemporary echo at most.
*Verified real (incl. a citing paper), but relevance is thin. Medium confidence.*

### 4.2 Oblivion: Self-Adaptive Agentic Memory Control through Decay-Driven Activation
Rana et al. (NEC Labs Europe). arXiv:2604.00131, v1 2026-03-31.
<https://arxiv.org/abs/2604.00131> · code: <https://github.com/nec-research/oblivion>
**SUPPORT + IMPROVE.** Forgetting as decay-driven reduction in *accessibility* rather than
deletion — the exact sub-threshold-but-not-deleted semantics of our ACT-R implementation. The
adoptable improvements: an uncertainty-gated read path (consult memory only when the agent's
uncertainty warrants it — our gate-time top-K is always-on) and reinforcement-on-use (bump a
chunk's presentation history when it actually contributes to a decision). Nuance: Oblivion's
decay is Ebbinghaus-exponential, not ACT-R power-law.
*Verified: mechanism, tiering, repo; date anomaly resolved (Mar 31 submission, April ID). High confidence.*

### 4.3 Learning to Share: Selective Memory for Efficient Parallel Agentic Systems
Fioresi et al. (UCF). arXiv:2602.05965, v1 2026-02-05. (ICML 2026.)
<https://arxiv.org/abs/2602.05965>
**SUPPORT.** A learned RL controller decides which intermediate steps get admitted to a global
memory shared across parallel agents; significantly reduces runtime while *matching or improving*
task performance vs. memory-free parallel baselines (the adversarial pass corrected "gains on
AssistantBench and GAIA" — the headline win is efficiency, not accuracy). Peer-reviewed evidence
for the promotion-chain premise: selective admission into shared memory beats both no sharing and
unfiltered sharing, and admission should be a learned/validated decision. Note SEDM (already in
INDEX.md) covers adjacent ground via verifiable write admission.
*Corrected in review as above. High confidence.*

### 4.4 Governed Collaborative Memory as Artificial Selection in LLM-Based Multi-Agent Systems
Cuadros et al. arXiv:2605.04264, v1 2026-05-05. (Viewpoint.)
<https://arxiv.org/abs/2605.04264>
**SUPPORT + IMPROVE** (no empirics). Frames the promotion-chain question — which candidate
memories become shared institutional state? — as a *selection regime*: ungoverned persistence,
constitutional/hybrid, automatic metric-based, human-ratified artificial selection. TeaParty's
human-validated promotion is squarely the last regime; the paper supplies the vocabulary and
design-space map for documenting why, and when a cheaper regime suffices. (Distinct from
"Governed Shared Memory," arXiv:2606.24535 — don't conflate.)
*Verified: taxonomy, viewpoint status. High confidence.*

### 4.5 From Raw Experience to Skill Consumption: A Systematic Study of Model-Generated Agent Skills (SkillLens)
Huang et al. (Microsoft; 16 authors). arXiv:2605.23899, v1 2026-05-22.
<https://arxiv.org/abs/2605.23899> · <https://microsoft.github.io/SkillLens>
**REFUTE (partial) — the most decision-relevant memory finding in this scan.** Lifecycle study of
model-generated skills in the SKILL.md format: (1) skills help in 75% of extractor–target pairs
but are *counterproductive in 25%* (worst domain: 47% negative transfer); (2) unguided LLM judges
are chance-level overall (46.4%) and **anti-predictive on clearly-separated pairs** (15.8% —
scope-corrected by the adversarial pass: that figure applies to pairs with utility gap ≥5%, where
the judge picks the *worse* skill). Material completion: a validated rubric raises judge accuracy
to **73.8%**. Implication for the promotion chain: LLM-plausibility review will promote wrong
learnings; validation must be outcome-based or rubric-guided. Cite both halves.
*Verified: both flagged numbers, scope correction, rubric recovery. High confidence.*

### 4.6 Managing Procedural Memory in LLM Agents: Control, Adaptation, and Evaluation (AFTER)
Belikova et al. arXiv:2606.23127, v1 June 2026.
<https://arxiv.org/abs/2606.23127>
**SUPPORT** (+ benchmark). AFTER: 382 enterprise tasks, six roles, 22 procedural skills, testing
local improvement and cross-task/role/model transfer. Procedural memory yields consistent gains
(+3.7–6.7 points per refinement round), but some skills are inherently role-specific and lose
effectiveness under transfer — empirical backing for keeping task-procedure learnings *scoped* to
the right hierarchy level rather than globally promoted. Candidate evaluation harness for the
task-procedures learning purpose.
*Verified: all figures. High confidence (exact v1 day unpinned).*

### 4.7 Organize then Retrieve: Hierarchical Memory Navigation for Efficient Agents (HORMA)
Hsu et al. (Duke, Snowflake). arXiv:2606.11680, v1 2026-06-10.
<https://arxiv.org/abs/2606.11680>
**SUPPORT.** Organizes agent memory into a file-system-like hierarchy — summaries at upper levels
linking down to raw trajectories — with retrieval as *navigation* rather than flat vector search
(≤22.17% of baseline token usage on ALFWorld/LoCoMo/LongMemEval). The strongest recent support
for two TeaParty choices at once: markdown-tree memory over vector DBs, and liaison-style
compressed summaries linked to recoverable detail. Caveat: HORMA's navigator is an RL-trained
lightweight agent; cite for the architecture argument, not the training method.
*Verified: mechanism, token figure. High confidence.*

### 4.8 Are We Ready For An Agent-Native Memory System?
Zhou et al. (SJTU, Tsinghua). arXiv:2606.24775, v1 2026-06-23.
<https://arxiv.org/abs/2606.24775>
**IMPROVE** (methodology). Decomposes memory into four modules — representation/storage,
extraction, retrieval/routing, maintenance — with system-level cost analysis across 12 memory
systems; finds no single architecture dominates and effectiveness depends on matching structure
to the workload bottleneck. Adopting this module-level decomposition would let the experimental
program isolate whether gains come from ACT-R scoring, bounding, or gate-time top-K — and it
mildly tempers any claim that file-based memory is universally superior.
*Verified: framework, 12-system evaluation, "no dominant architecture" finding. High confidence.*

### 4.9 Remember When It Matters: Proactive Memory Agent for Long-Horizon Agents
Wu et al. (Meta AI). arXiv:2607.08716, v1 2026-07-09.
<https://arxiv.org/abs/2607.08716>
**IMPROVE.** Names "behavioral state decay" — decision-relevant facts stop influencing decisions
even while still in context — and fields a separate memory agent that watches the trajectory and
decides when to *inject* a reminder vs. stay silent: +8.3pp pass@1 on Terminal-Bench 2.0, +6.8pp
on τ²-Bench. Suggests a push channel complementing our pull-at-gate retrieval: a liaison or the
proxy proactively injecting a high-activation preference or norm mid-execution when it becomes
decision-relevant. Terminology caution from review: "behavioral state decay" is an
attention-failure mode, not memory decay — do not cite it as support for ACT-R activation decay.
*Verified: figures, mechanism. High confidence.*

---

## 5. Protocol, planning, backtracking, and context rot

### 5.1 In-Context Prompting Obsoletes Agent Orchestration for Procedural Tasks
Dennis, Diamond, Patil, Shabahang, Guo (U. Melbourne). arXiv:2604.27891, v1 2026-04-30.
<https://arxiv.org/abs/2604.27891>
**SUPPORT (fable branch) / REFUTE (the hand-rolled runtime).** Controlled comparison: an external
LangGraph-style orchestrator injecting routing instructions is *dominated* by putting the whole
procedure in the system prompt and letting the model self-orchestrate — in-context 4.53–5.00 vs
orchestrator 4.17–4.84 (LLM-judged), orchestrator failure rates 24%/9%/17% vs 11.5%/0.5%/5%
across three domains, and more LLM calls (10.8 vs 8.7). All numbers survived adversarial
verification. This is the closest published evidence for "delete the CfA state machine, keep CfA
as a process skill." Cite with its caveats: head-to-head vs LangGraph only; LLM-as-judge scoring;
in-context uses *more tokens* per conversation (68K vs 43K in one domain — the win is quality and
call count, not token cost); domains are procedural customer-service dialogs, not coding.
*Verified: all figures incl. the call-count claim. High confidence.*

### 5.2 The Long-Horizon Task Mirage? Diagnosing Where and Why Agentic Systems Break (HORIZON)
Wang et al. (incl. Mutlu, Song, Nowak). arXiv:2604.11978, v1 2026-04-13.
<https://arxiv.org/abs/2604.11978>
**SUPPORT.** Cross-domain diagnostic benchmark (3,100+ trajectories, FMEA-guided failure
attribution, human–judge κ=0.84): agents strong on short horizons break on long interdependent
sequences; the diagnosis recommends — verbatim — "execution-time plan verification and repair,
and stronger long-range memory mechanisms," plus hierarchical subplanning. Independent support
for both the context-rot claim and the CfA position that execution must be able to reveal and
repair flawed plans.
*Verified: recommendation quoted verbatim, benchmark stats. High confidence.*

### 5.3 Diagnosing and Mitigating Context Rot in Long-Horizon Search
Xia, Wang, Huang, Liu. arXiv:2606.29718, v1 2026-06-29.
<https://arxiv.org/abs/2606.29718> · code: <https://github.com/GAIR-NLP/ContextRot>
**SUPPORT.** Names and measures context rot in long-horizon agents: across four open-source
models and three benchmarks, growing context causes models to give up or prematurely emit
uncertain answers, worsening as context grows; evaluates seven context-management mitigations.
Directly supports the hierarchical-teams rationale (context boundaries and compression) as a
mitigation-shaped architecture. Scope: deep-search agents, adjacent to our setting.
*Verified: findings, repo. High confidence.*

### 5.4 Web Agents Should Adopt the Plan-Then-Execute Paradigm
Piet et al. (UC Berkeley, incl. Popa, Wagner). arXiv:2605.14290, v1 2026-05-14.
<https://arxiv.org/abs/2605.14290>
**SUPPORT** (with a real tension). Position paper: agents should commit to a task-specific plan
*before* observing untrusted runtime content — content-driven control flow is the injection
pathway; a committed plan confines injected data to influencing values, not redefining the task.
Recasts the approved Plan artifact as a *security boundary*, highly relevant to a world-writable
GitHub bus. The tension the adversarial pass flagged: CfA's ten backtrack transitions
deliberately let execution observations reopen the plan — the exact loop this paper closes.
Worth a design note on *who* may trigger a backtrack (trusted humans/proxy, never thread
content).
*Verified: thesis; position paper, no benchmark. High confidence.*

### 5.5 Why Reasoning Fails to Plan: A Planning-Centric Analysis of Long-Horizon Decision Making (FLARE)
Wang et al. arXiv:2601.22311, v1 2026-01-29.
<https://arxiv.org/abs/2601.22311>
**IMPROVE.** Shows step-wise reasoning induces a greedy policy whose early myopic commitments are
"systematically amplified over time and difficult to recover from" (and proves greedy step-wise
reasoning arbitrarily suboptimal) — direct support for the no-backtracking failure claim. Its
remedy FLARE (Future-aware Lookahead with Reward Estimation: lookahead + value propagation +
limited commitment) suggests recovery may need finer granularity than ten coarse phase-level
backtracks. Correction from review: the paraphrase "commits only to the next action, replans
every transition" could not be corroborated — cite the mechanism as lookahead-with-limited-
commitment, not continuous replanning.
*Corrected in review as above. High confidence on core claims.*

### 5.6 Useless but Safe? Benchmarking Utility Recovery with User Intent Clarification (CarryOnBench)
Zheng, Morgan, Jiang, Rosé, Sap (CMU, AI2, UW). arXiv:2604.27093, v1 2026-04-29.
<https://arxiv.org/abs/2604.27093>
**SUPPORT — finding direction corrected.** The adversarial pass caught an inverted claim: the
original summary said models are "poor at revising intent interpretation after clarification."
The paper actually finds **13 of 14 models approach or exceed the benign-intent baseline once
users clarify** — revision generally *succeeds*. Real contributions: safety and utility are
structurally decoupled (single-turn performance predicts neither), and three failure modes
invisible to single-turn evals (utility lock-in, unsafe recovery, repetitive recovery). Supports
the intent-gap framing and the value of clarification; do not cite as evidence clarification
fails.
*Corrected in review; benchmark stats verified (398 seeds, 5,970 conversations, 14 models). High confidence.*

### 5.7 Beyond Global Replanning: Hierarchical Recovery for Cross-Device Agent Systems (H-RePlan)
Yao et al. arXiv:2606.20487, v1 2026-06-18.
<https://arxiv.org/abs/2606.20487>
**IMPROVE** (analogical). Separates device-local strategy recovery from orchestrator-level global
replanning; beats global-replan and single-strategy baselines on completion and token cost on a
fault-injected benchmark (174 task variants). The transferable idea for CfA's backtrack ladder:
route failures to the *cheapest sufficient* recovery level — don't reach for the expensive
cross-phase backtrack when a local repair suffices. Relevance is analogical (multi-device GUI
automation, and it *adds* an orchestrator where the fable branch deletes one).
*Verified: design, benchmark; relevance downgraded honestly. High confidence.*

### 5.8 Classifier Context Rot: Monitor Performance Degrades with Context Length
Martin & Roger (Anthropic Fellows). arXiv:2605.12366, v1 2026-05-12.
<https://arxiv.org/abs/2605.12366>
**SUPPORT.** Context rot afflicts *overseers*, not just workers: frontier models monitoring agent
transcripts miss subtly dangerous actions 2×–30× more often after ~800K tokens of benign
activity; periodic in-transcript reminders partially mitigate. Strengthens the case for
liaison-style compression *before* review — a reviewer (human, proxy, or final-review gate)
reading a long execution trace degrades with trace length. Scope caveat: measures
monitor/classifier degradation, not executor task performance. Pairs with §2.10.
*Verified: figures, LessWrong cross-post. High confidence.*

---

## 6. Rejected and near-miss candidates

**Rejected by the adversarial pass:**

- **A2H: Agent-to-Human Protocol** (arXiv:2602.15831) — real paper, accurate claims (Human Card,
  formal agent-contacts-human schema, unified messaging abstraction — convergent with the bus's
  humans-as-first-class-nodes design), but v1 was submitted **2025-12-31**, outside the 6-month
  window (the Feb-2026 arXiv ID reflects late announcement). Strong SUPPORT candidate if the
  window is ever relaxed.

**Sighted but not verified to the inclusion bar** (first places to look in a follow-up pass):
SYNAPSE (2601.02744 — spreading-activation memory, v1 Jan 6, just misses the window); Adaptive
Memory Admission Control (2603.04549); MemForest (2605.23986); HMARS (2606.28349);
Rate-Distortion agent memory (2605.10870); Governed Shared Memory for Multi-Agent LLM Systems
(2606.24535); User Preference Modeling for Conversational Agents via Weak Rewards (2603.20939);
PersistBench (2602.01146); Uncertainty Decomposition for Clarification Seeking (2606.19559);
Calibrate-Then-Act (2602.16699); Comparing Human Oversight Strategies for Computer-Use Agents
(2604.04918); Hedwig: Dynamic Autonomy for Coding Agents Under Local Oversight (2605.11495).

---

## 7. Cross-cutting observations

1. **The refutation literature converges on one demand:** demonstrate multi-agent advantage under
   *normalized compute* on tasks that *structurally stress coordination* (§1.1, §1.2, §1.3).
   CooperBench is the ready-made instrument.
2. **The bus makes old design choices security-critical.** ASPI (§2.1), Plan-Then-Execute (§5.4),
   and Harness-MU (§1.7) together imply: clarification threads are attack surfaces, the approved
   plan is a commit-before-exposure boundary, and authorization/precedence must live in
   deterministic bus machinery. The github-bus proposal's "secret hygiene" risk section
   understates this class of risk.
3. **Proxy realism check.** Persona-prompted prediction of individuals is poor (40.4%, §3.5;
   averaging bias and plateau, §3.6; persona inconsistency, §2.2) — but delegation demonstrably
   outperforms advice when it works (§2.4), and per-user-memory loops are being validated at
   scale (§3.1). The literature's message: TeaParty's observation-driven, delta-learning design
   is the *right* bet precisely because prompting-only proxies fail; set cold-start thresholds
   conservatively.
4. **Promotion chains need outcome-based validation.** SkillLens (§4.5) + AFTER's role-transfer
   losses (§4.6) + Learning-to-Share (§4.3): promote selectively, validate with rubrics or
   outcomes (never unguided LLM judgment), and keep procedural learnings scoped to the hierarchy
   level where they were earned.
5. **Retrieval should gain a push channel.** Oblivion's uncertainty-gated reads (§4.2) and
   Meta's proactive memory agent (§4.9) both suggest complementing pull-at-gate retrieval with
   proactive injection when a stored preference becomes decision-relevant mid-execution.
