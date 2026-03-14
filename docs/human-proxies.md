# Human Proxy Agents

A human proxy agent learns to stand in for a specific human — approving work, answering team questions, and escalating when the decision exceeds its confidence. This is TeaParty's fourth pillar: the mechanism by which agents earn autonomy rather than assume it.

## The Autonomy-Oversight Dilemma

Every autonomous agent faces a continuous choice: act or ask. Both carry risk. Acting when the human wanted to be consulted causes wrong work and eroded trust. Escalating when the agent could have handled it wastes the human's time. These failure modes are not symmetric — their relative costs vary by organization, individual, domain, and decision.

The human proxy exists to navigate the space between pure autonomy and constant oversight.

## Least-Regret Escalation

Least-regret escalation means the proxy chooses whichever option — act or ask — produces less expected regret: less wrong work if it acts, less wasted time if it escalates, weighted by the costs specific to this human and decision.

The proxy makes this choice through two complementary models. The **confidence model** tracks accumulated approval history per (state, task) pair and determines whether the proxy has earned enough trust to act autonomously. The **risk tolerance model** estimates the reversibility and organizational impact of individual decisions, differentiating within a CfA state — approving a plan that touches the payment pipeline carries more risk than approving a plan that updates documentation, even though both are PLAN_ASSERT decisions. Together, these determine whether any given decision should be auto-approved or escalated.

## The Confidence Model

The confidence model tracks state-task pairs (e.g., `INTENT_ASSERT|POC`, `PLAN_ASSERT|POC`) and makes binary approve/escalate decisions based on accumulated observation. Five mechanisms govern its behavior:

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

## Generative Proxy Responses

The mechanisms above address binary states — INTENT_ASSERT, PLAN_ASSERT — where the proxy decides to approve or escalate. But generative states (INTENT_ESCALATE, PLANNING_ESCALATE) require the proxy to do more than decide: it must predict what the human would say in a clarification dialog. The proxy stands in for the human during the escalation conversation itself, drawing on accumulated preferential and behavioral learning to generate responses that reflect the human's priorities, communication style, and decision patterns.

## Proxy Memory

Proxy learning is stored in the same file-based format as other learning types in the [learning system](learning-system.md): `proxy.md` for preferential knowledge (always loaded) and `proxy-tasks/` for task-based decision patterns (fuzzy-retrieved against the current decision context).

## Cold Start to Warm Start

The progression from cold to warm follows a predictable arc:

1. **Cold start** (< 5 observations) — always escalate, collect data. Every session begins here for new state-task pairs.
2. **Calibrating** (5-20 observations) — EMA emerges but confidence is volatile. A single correction can swing the rate substantially.
3. **Warm start** (20+ observations with stable EMA) — proxy auto-approves reliably for this state-task pair.

The proxy never fully stops escalating. The exploration rate ensures ongoing calibration signal even in warm-start domains.

## Relationship to the Learning System

Proxy learning is one of the four learning types in the [learning system](learning-system.md). The escalation model is one of the highest-value things the memory system stores — it encodes not just what a person values but how much latitude they grant, and how that varies by domain.

## Open Questions

**Risk tolerance calibration.** The risk tolerance model requires per-decision features — reversibility, organizational impact, blast radius — that go beyond the binary state-task pairs the confidence model uses. How to estimate these features reliably, and how to weight them against confidence, needs design work.

**Generative response quality.** Standing in for the human during clarification dialogs is a harder problem than binary gate decisions. The proxy must generate responses that the human would recognize as reflecting their own priorities, not generic reasonable responses. How much behavioral and preferential data is needed before generative responses are trustworthy enough to deploy is an open question.

**Literature review.** The proxy's mechanisms were designed from pragmatic engineering intuition. A systematic literature review — particularly in adjustable autonomy, trust calibration, and implicit feedback learning — could identify principled improvements to the parameter choices that are currently set by judgment. A preliminary survey of potentially relevant work is cataloged in [research/human-proxy-agent-design.md](research/human-proxy-agent-design.md).
