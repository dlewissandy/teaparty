# Human Proxy Agents

A human proxy agent learns to stand in for a specific human — engaging in dialog with agent teams, anticipating what the human would ask and how they would respond, and escalating to the actual human when the conversation exceeds its understanding. This is TeaParty's fourth pillar: the mechanism by which agents earn autonomy through demonstrated understanding, not configuration.

The proxy is not a gatekeeper. It is a dialog partner. At approval gates it decides whether to approve or escalate, but that is the least interesting thing it does. Its primary role is to participate in the ongoing conversation between human and agent teams — during intent gathering, during planning, during execution — building a model of the human's thinking that becomes more accurate with every interaction. The proxy that only says yes or no has failed at its job. The proxy that asks the questions the human would have asked, flags the concerns the human would have flagged, and provides the context the human would have provided — that proxy has earned the right to act autonomously.

## The Autonomy-Oversight Dilemma

Every autonomous agent faces a continuous choice: act or ask. Both carry risk. Acting when the human wanted to be consulted causes wrong work and eroded trust. Escalating when the agent could have handled it wastes the human's time. These failure modes are not symmetric — their relative costs vary by organization, individual, domain, and decision.

The human proxy exists to navigate the space between pure autonomy and constant oversight.

## Understand First, Act Second

The proxy's governing principle is: understand before acting. Before agent teams produce artifacts — before INTENT.md is written, before PLAN.md is drafted — the proxy runs an intake dialog that builds shared understanding of what the human wants and why.

On cold start, this is a full conversation. The agent team does its homework — explores the codebase, reads prior sessions, investigates the problem space — and the proxy then engages the human with what it found: "Here's what I'm seeing. Here's what I think the real problem is. Here are the things I want to confirm before we proceed." The proxy formulates questions, but it also formulates **predictions** — what it thinks the human's answer will be, based on whatever model it has so far. Questions where the proxy's prediction confidence is low go to the human. Questions where prediction confidence is high are answered by the proxy itself, surfaced as assumptions the human can correct.

Every answer the human gives is compared against the proxy's prediction. The delta — where the proxy was wrong — is the highest-value learning signal in the system. It reveals not just what the human wants, but where the proxy's model of the human diverges from reality. Over time, the proxy's predictions improve. The intake dialog gets shorter — not because the proxy skips questions, but because it answers more of them correctly. The progression from full dialog to near-silent proxy is not a configuration change. It is earned through demonstrated understanding.

This is not an interrogation or a requirements-gathering form. It is the same conversation a sharp colleague would have: one who did their research, has a point of view, and checks their understanding before going off to do the work.

## Least-Regret Escalation

Least-regret escalation means the proxy chooses whichever option — act or ask — produces less expected regret: less wrong work if it acts, less wasted time if it escalates, weighted by the costs specific to this human and decision.

The proxy makes this choice through two complementary models. The **confidence model** tracks accumulated approval history per (state, task) pair and determines whether the proxy has earned enough trust to act autonomously. The **risk tolerance model** estimates the reversibility and organizational impact of individual decisions, differentiating within a CfA state — approving a plan that touches the payment pipeline carries more risk than approving a plan that updates documentation, even though both are PLAN_ASSERT decisions. Together, these determine whether any given decision should be auto-approved or escalated.

## The Confidence Model

The confidence model tracks state-task pairs (e.g., `INTENT_ASSERT|POC`, `PLAN_ASSERT|POC`) and determines how much the proxy understands about the human's preferences for a given type of decision. The model learns from two sources: **gate outcomes** (did the human approve or correct the artifact?) and **prediction accuracy** (during intake dialog, did the proxy correctly anticipate the human's answers?). Gate outcomes are tracked in the confidence model; prediction accuracy tracking is a design target that will be added as the intake dialog matures. Prediction accuracy is the richer signal — a gate outcome tells the proxy "this was acceptable," but a prediction delta tells it *where and why* its model of the human is wrong.

Five mechanisms govern the model's behavior:

**Confidence tracking.** Each state-task pair accumulates an approval rate via exponential moving average (EMA, alpha=0.3). The proxy auto-approves when the EMA exceeds a threshold and escalates otherwise.

**Cold start.** With fewer than 5 observations per state-task pair, the proxy always escalates. Small samples are unreliable; the system defaults to the safe action until it has enough data to form a meaningful estimate.

**Asymmetric regret.** A single correction counts as 3 EMA decay steps. This makes autonomy harder to earn and easier to lose — a false approval (rubber-stamping bad work) is treated as 3x more costly than a false escalation (asking the human when they would have said yes).

**Exploration rate.** Even when confidence is high, the proxy escalates 15% of the time. This prevents convergence to "always auto-approve" and ensures the model continues to see human decisions for ongoing calibration.

**Staleness guard.** If the proxy hasn't seen human feedback for a state-task pair in 7+ days, it forces escalation regardless of confidence. Preferences drift; the model must not converge to an outdated snapshot.

## Beyond Gate Decisions

The confidence model captures what the human approves. But the human reveals far more than binary gate decisions during the course of work.

**Behavioral learning from dialog.** When the human questions a team's approach, redirects a line of investigation, asks for more detail on a specific aspect, or pushes back on an assumption, each interaction reveals what they pay attention to and how they think about the work. A question during planning — "where is the rollback plan?" — tells the system "this is what I scrutinize." These patterns are as valuable as gate decisions. The proxy records review conversations and question patterns, building a model of the human's scrutiny patterns that informs future reviews. See the [learning system](learning-system.md#proxy-learning) for how behavioral learning fits into the broader memory architecture.

**Concern vocabulary detection.** Agent output often contains hedging language, unresolved questions, or confidence qualifications that signal the agent itself is uncertain. The proxy scans for these signals and treats them as indicators that closer scrutiny — or escalation — is warranted, even when the confidence model would otherwise auto-approve.

**Artifact length tracking.** The proxy records the character count of each artifact it reviews, building a distribution of expected lengths per state-task pair. Unusually short or long artifacts relative to the historical distribution trigger closer scrutiny.

**Behavioral rituals.** Some human behaviors are not reactions to specific content but invariant practices tied to specific CfA states. A human who always asks for a TLDR before reviewing a plan, always leads delegation with quality principles ("make your work as conceptually clear and surgically specific as possible"), or always checks test coverage before approving code — these are rituals, and they reveal the human's operational DNA more directly than any individual decision. The proxy detects rituals by tracking behavior patterns per CfA state: actions that recur at the same state across multiple sessions, regardless of task content, are candidates. Once detected with sufficient confidence, the proxy performs these rituals preemptively — providing the TLDR before being asked, prepending the quality principles to delegation, surfacing test coverage in the review summary. A preemptively executed ritual that the human would have performed anyway saves time and demonstrates understanding. A preemptive execution that the human corrects ("I don't need a TLDR for this one") is a delta — the ritual was context-dependent, not invariant — and the proxy refines its model accordingly.

## Generative Proxy Responses

The proxy's most important capability is not deciding whether to approve — it is predicting what the human would say. This applies at every conversational moment, not just at gates:

**During intake dialog.** The proxy predicts answers to the questions the agent team needs resolved before producing artifacts. High-confidence predictions are used directly; low-confidence predictions become questions for the human. Every prediction-vs-actual comparison refines the model.

**During escalation.** When agent teams escalate (INTENT_ESCALATE, PLANNING_ESCALATE), the proxy stands in for the human in the clarification conversation itself — drawing on accumulated preferential and behavioral learning to generate responses that reflect the human's priorities, communication style, and decision patterns.

**During gate review.** Even at binary gates (INTENT_ASSERT, PLAN_ASSERT), the proxy that has built understanding through dialog can make more informed decisions than one that only sees the finished artifact. The intake dialog gives the proxy context about what the human cares about for *this specific task*, not just historical approval rates for this task type.

### Prediction Through Retrieval

The proxy's predictions are grounded in the learning system's scoped retrieval, not in raw transcript replay. When the proxy needs to predict what the human would say, it retrieves what it knows — preferential knowledge, task-based patterns, prior responses the human gave under similar circumstances — and reasons about what the human would likely say given that evidence. The learning system's scope weighting ensures that nearby context (team-level) is weighted more heavily than distant context (project, global) at equal similarity.

After the human answers, the proxy compares the prediction against reality and reflects: *What additional information about this human have I learned that would have improved my prediction?* That reflection — a text derivative of the comparison — is stored back into the learning system, scoped and indexed for future retrieval. Over time, these reflections accumulate into a richer model of the human.

The proxy can also generalize across situations: *How has this human responded under similar circumstances, and what can I infer about how they would respond here?* This is retrieval-backed reasoning — the proxy uses the LLM's own judgment to assess relevance, draw inferences from stored observations, and identify patterns across the human's past behavior. No separate statistical model is required; the learning system's storage, scoping, and retrieval provide the memory, and the LLM provides the reasoning.

### Knowing When to Ask

Prediction answers "what would they say?" but the proxy must also answer "what do I not know?" — identifying the gaps in its model that require human input rather than autonomous action. Three signals trigger questioning:

**No retrieval hits.** When the proxy queries its learning store for the current context and gets nothing relevant back, it has no basis for prediction. Novel task types, unfamiliar domains, or first encounters with a particular kind of decision all produce retrieval voids. These are the proxy's clearest signal that it needs to ask.

**Contradictory retrieval.** When retrieved learnings point in conflicting directions — one pattern says the human prefers aggressive parallelization, another says they insist on sequential verification for this domain — the proxy has learned something, but the something is ambiguous. Contradictions can signal preference drift (the newer pattern may have superseded the older), context sensitivity (both are right in different circumstances), or a genuine unresolved tension in the human's preferences. All warrant questioning to resolve.

**Novel concerns in agent output.** When the agent team's work surfaces issues, tradeoffs, or decision points that the proxy has never seen the human address — technologies not previously encountered, risk categories not previously weighed, organizational implications not previously considered — the proxy flags these as questions regardless of its confidence in adjacent domains. Confidence in one area does not transfer to another.

The interplay between prediction and questioning is what makes the intake dialog a calibration instrument rather than a questionnaire. The proxy predicts where it can, questions where it cannot, and calibrates from the delta between every prediction and the human's actual response.

The progression is: dialog builds understanding, understanding enables prediction, accurate prediction earns autonomy. A proxy that cannot predict what the human would say has no business approving on their behalf.

## Proxy Memory

Proxy learning is stored in the same file-based format as other learning types in the [learning system](learning-system.md): `proxy.md` for preferential knowledge (always loaded) and `proxy-tasks/` for task-based decision patterns and ritual patterns (fuzzy-retrieved against the current decision context).

## Cold Start to Warm Start

The progression from cold to warm follows a predictable arc, visible in both the intake dialog and at approval gates:

1. **Cold start** (< 5 observations) — full intake dialog. The proxy has no predictions, every question goes to the human. At gates, the proxy always escalates. Every answer and every gate decision is a new data point.
2. **Calibrating** (5-20 observations) — partial dialog. The proxy predicts some answers correctly and only asks about genuinely uncertain ones. At gates, confidence is volatile — a single correction can swing the rate substantially. The proxy begins to demonstrate understanding but cannot yet be trusted to act alone.
3. **Warm start** (20+ observations with stable predictions) — near-silent dialog. The proxy predicts most answers correctly, surfacing them as assumptions ("Based on our past work, I'm assuming X — correct me if wrong"). At gates, the proxy auto-approves reliably. The intake dialog has compressed from a full conversation to a brief confirmation.

The proxy never fully stops asking. The exploration rate ensures ongoing calibration signal even in warm-start domains — occasionally asking a question it could predict, to verify its model hasn't drifted.

## Relationship to the Learning System

Proxy learning is one of the four learning types in the [learning system](learning-system.md). The escalation model is one of the highest-value things the memory system stores — it encodes not just what a person values but how much latitude they grant, and how that varies by domain.

## References

**Chu, W. & Ghahramani, Z.** (2005). Preference learning with Gaussian processes. *ICML 2005*. https://dl.acm.org/doi/10.1145/1102351.1102369
Learns a latent utility function from pairwise preference comparisons, producing calibrated uncertainty estimates — high where data is sparse, low where dense. Demonstrates that preference models can produce well-calibrated confidence from sparse observations, informing the proxy's need to distinguish what it knows from what it is guessing at.

**Biyik, E., Huynh, N., Kochenderfer, M. J. & Sadigh, D.** (2024). Active preference-based Gaussian process regression for reward learning. *The International Journal of Robotics Research*. https://journals.sagepub.com/doi/10.1177/02783649231208729
Combines preference learning with active query selection — asking the most informative question next. Validated with real humans, reaching reliable predictions in 10-30 queries. Confirms that the cold-to-warm progression the proxy targets (5-50 observations) is realistic, and that prioritizing uncertain questions over random ones substantially improves learning efficiency.

**Settles, B.** (2009). Active learning literature survey. *University of Wisconsin–Madison Technical Report 1648*. https://burrsettles.com/pub/settles.activelearning.pdf
The canonical survey of active learning strategies. Four approaches — uncertainty sampling, query-by-committee, expected model change, information gain — all collapse to the same intuition: ask where the model is least confident, skip where it is most confident. Grounds the proxy's questioning strategy in an established principle rather than ad hoc heuristics.

**Houlsby, N., Huszár, F., Ghahramani, Z. & Lengyel, M.** (2011). Bayesian active learning by disagreement (BALD). *arXiv:1112.5745*. https://arxiv.org/pdf/1112.5745
Distinguishes epistemic uncertainty (resolvable by asking — the model has conflicting hypotheses) from aleatoric uncertainty (irreducible noise — more data won't help). Informs the proxy's decision about which questions are worth asking: only those where the human's answer would actually update the proxy's model, not questions whose answers are inherently unpredictable.

**Park, J. S. et al.** (2024). Generative agent simulations of 1,000 people. *arXiv:2411.10109*. https://arxiv.org/abs/2411.10109
Built AI agents representing 1,052 real individuals from two-hour qualitative interviews. Agents replicated survey responses with 85% accuracy using LLM in-context reasoning over interview transcripts — no explicit ML model required. Validates the premise that conversational data alone can build a predictive model of an individual, and that the LLM's own reasoning is a sufficient prediction engine.

**Salemi, A. & Zamani, H.** (2024). Few-shot personalization of LLMs with mis-aligned responses — Fermi. *arXiv:2406.18678*. https://arxiv.org/abs/2406.18678
Learns personalized prompts by iteratively refining them using prediction errors as the primary learning signal. Key finding: misaligned responses — where the LLM predicted incorrectly — are more valuable for learning than correct predictions. Validates the proxy's delta-based learning architecture: the gap between prediction and reality is the highest-value signal.

## Open Questions

**Risk tolerance calibration.** The risk tolerance model requires per-decision features — reversibility, organizational impact, blast radius — that go beyond the binary state-task pairs the confidence model uses. How to estimate these features reliably, and how to weight them against confidence, needs design work.

**Prediction accuracy threshold.** The intake dialog relies on the proxy knowing when its predictions are good enough to use and when to ask the human instead. Overconfident predictions that bypass the human erode alignment silently. Underconfident predictions that ask too many questions erode trust in the system's intelligence. The right threshold — and whether it should vary by question type, task domain, or decision reversibility — needs empirical calibration.

**Literature review.** The proxy's mechanisms were designed from pragmatic engineering intuition. A systematic literature review — particularly in adjustable autonomy, trust calibration, and implicit feedback learning — could identify principled improvements to the parameter choices that are currently set by judgment. A preliminary survey of the proxy design's relationship to existing work is cataloged in [research/human-proxy-agent-design.md](../research/human-proxy-agent-design.md). A targeted review of prediction-comparison learning, active questioning, and Bayesian preference modeling — covering approaches from Beta-Bernoulli updating through GP preference learning, uncertainty sampling (BALD), and practical systems (Park et al. 2024, Salemi/Fermi 2024) — is cataloged in [research/proxy-prediction-and-active-learning.md](../research/proxy-prediction-and-active-learning.md).
