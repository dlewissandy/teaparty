# Human-AI Collaboration, Adjustable Autonomy, and the Proxy Agent

## Background

As AI agent systems grow more capable, they are increasingly deployed not as single assistants but as teams: a coordinator dispatches subagents, subagents call tools and spawn further specialists, and tasks that once required a human at every step now proceed through many layers of automated reasoning before anyone looks at the result. This is genuinely useful. It is also where things go wrong in ways that are hard to detect.

The central tension is not new. Every increase in automation raises the same question: how much of the decision loop should the human remain in? Too much involvement and the automation provides no leverage — the human is simply rubber-stamping decisions they did not make. Too little and the system drifts, silently executing on assumptions that may have diverged from what the human actually wanted. This is the autonomy dilemma, and it has been studied in earnest for decades in aviation, nuclear process control, and military command-and-control — domains where the cost of getting it wrong is measured in lives.

### The Supervisory Control Problem

Thomas Sheridan's 1992 monograph *Telerobotics, Automation, and Human Supervisory Control* gave the problem its canonical framing (Sheridan, 1992). Supervisory control is the mode that arises when a human no longer acts directly on a system but instead plans, monitors, and occasionally intervenes while automation handles execution. Sheridan identified ten levels ranging from full manual control to full autonomy, with the operator progressively ceding authority: first over implementation, then over selection among options, then over decision-making itself, and finally over the choice of whether to inform the human at all.

Parasuraman, Sheridan, and Wickens refined this into a more functional taxonomy in a widely cited 2000 paper (Parasuraman et al., 2000). Rather than a single dial from manual to automatic, they identified four classes of function — information acquisition, information analysis, decision and action selection, and action implementation — each of which can be automated at different levels independently. The insight is important: automation level is not a global property of a system, it is a property of each function. A system that automatically gathers and displays information but requires human sign-off on action selection sits at different levels across those four dimensions simultaneously.

This functional view reshaped how researchers think about human-automation allocation. It also exposed a failure mode that Sarter and Woods documented in a series of studies of commercial cockpit automation: mode error (Sarter & Woods, 1995). When automation levels vary by function and modes shift during operation, pilots frequently lost track of what the system was currently doing — and why. Their paper's memorable title, "How in the World Did We Ever Get into That Mode?", captures something that recurs in any sufficiently complex automated system. The human is nominally in control but practically surprised by the machine's behavior, because their mental model of the automation's current state has fallen behind.

### Adjustable Autonomy

The supervisory control literature treats automation level as something a designer sets. A different strand of work asks whether autonomy can be adjusted dynamically, earned or revoked based on observed performance. Bradshaw and colleagues developed this concept in the context of multi-agent systems, arguing that autonomy should be treated not as a static assignment but as an ongoing negotiation between the human and the agent (Bradshaw et al., 2003). An agent that consistently makes decisions consistent with human intent earns the right to proceed without consultation. An agent that makes a bad call should lose that right, at least temporarily, until trust is rebuilt.

This is a substantially more demanding design target than a static level-of-automation setting. It requires the system to have a model of its own reliability, a mechanism for accumulating that model over time, and a way of expressing the current level of earned autonomy in its behavior — asking when uncertain, acting when confident. It also requires the human to have enough visibility into agent behavior to calibrate trust in the first place.

### Trust Calibration

Lee and See's 2004 review of trust in automation is the standard reference for why this calibration problem is hard (Lee & See, 2004). Trust, they argue, is not simply a rational assessment of system reliability. It is influenced by performance (does the system do what it says?), process (does the human understand how it works?), and purpose (does the human believe the system is designed to serve their interests?). Humans respond to automation more like they respond to people than like they respond to tools — extending good faith, interpreting behavior charitably, assigning intent.

The consequences are predictable. Overtrust, also called automation complacency, leads humans to accept automated outputs they should have checked. Undertrust leads them to ignore or override systems that are actually performing well. Neither failure mode corresponds to a rational reading of the system's actual track record; both are systematic biases in how humans process reliability information.

Two asymmetries are particularly important. First, trust recovers slowly after violations. A single high-profile failure resets trust in ways that many preceding successes did not establish it. This is not irrational — failures are genuinely more informative about tail behavior — but it means that the trust relationship is fragile in a way that matters for agent design. Second, humans are slow to update on subtle evidence of degraded performance. They notice dramatic failures; they miss gradual drift. This combination — vulnerability to sudden failures and blindness to slow ones — defines the risk profile that a well-designed proxy agent needs to address.

### Software Agents that Learn from Observation

The idea of an agent that learns to stand in for a human was already present in the earliest work on interface agents. Pattie Maes's 1994 paper introduced the concept of software agents that learn user preferences through observation, reducing work by anticipating what the user would do and doing it for them (Maes, 1994). A year later, Henry Lieberman demonstrated Letizia, an agent that shadowed a user's web browsing session, built a model of their interests, and proactively suggested links the user was likely to want (Lieberman, 1995). Neither system asked the user questions. They watched and inferred.

The modern version of this idea, reinforcement learning from human feedback (RLHF), scales the same basic insight to large language models. Christiano and colleagues showed that complex behaviors could be learned from pairwise comparisons of short trajectory segments, with the human providing relative judgments rather than explicit reward signals (Christiano et al., 2017). Ouyang and colleagues applied this to instruction-following in large language models, producing the InstructGPT family that underlies contemporary conversational AI systems (Ouyang et al., 2022). RLHF is now a central technique in AI alignment: it captures human preferences and encodes them into model weights.

But encoding preferences into weights is a one-time training operation. It captures a statistical summary of what a population of labelers preferred across a distribution of prompts. It does not capture what a specific individual prefers in the specific context they are operating in right now. The preferences learned by RLHF are general; the preferences that matter in a running agent system are personal and contextual.

TeaParty's proxy agent occupies a different level of the stack. It does not fine-tune model weights. It accumulates a record of a specific human's decisions in a specific operational context — what they approved, what they rejected, what they asked to be done differently, and crucially, what reasoning they gave when they were explicit about it. This is preference learning at the application layer, not the model layer, and the distinction matters: it means the proxy's model of the human updates in real time, can be inspected and corrected, and does not require a training run.

### Active Learning and the Question of When to Ask

A proxy agent that accumulates decisions still faces a choice: when should it act on its accumulated knowledge, and when should it escalate to the human? Acting too readily is the overtrust failure mode from the human side, except now instantiated in the proxy itself. Escalating too readily defeats the purpose of the proxy.

The active learning literature frames this as a query selection problem. If human attention is scarce, which observations should you request labels for? Uncertainty sampling, one of the simplest strategies, queries the instances where the model is least confident. Houlsby and colleagues formalized a Bayesian version of this idea — Bayesian Active Learning by Disagreement, or BALD — that queries the instances where disagreement among the model's hypotheses is highest, maximizing the information gained per query (Houlsby et al., 2011). The principle is straightforward: do not ask questions you already know the answer to.

Applied to a proxy agent, this becomes: do not escalate decisions you can predict with high confidence. Escalate the ones where your prediction is genuinely uncertain, where the observed features are unlike anything in your training set, or where the stakes are high enough that even moderate uncertainty warrants a check.

Recent work has extended active preference learning to the LLM context specifically. A 2024 paper on active preference learning for large language models proposes query strategies based on the predictive entropy of the language model and the certainty of the implicit preference model, finding that the same level of preference alignment can be achieved with substantially fewer queries when they are selected actively rather than randomly (arXiv:2402.08114, 2024). The message for proxy agent design is that asking the right question at the right time is more valuable than asking many questions.

### Asymmetric Costs and the Shape of Regret

Not all errors are symmetric. When a proxy agent makes a decision it should have escalated — a false approval, in classification terms — the human's intent may be violated and they may not find out until damage is done. When the proxy escalates a decision the human would have approved — a false escalation — the cost is attention: the human spends a moment on something the proxy could have handled. These costs are not equal.

This asymmetry should be explicit in the proxy's decision function. Treating escalation as a symmetric binary classification problem — minimize total error rate — will systematically underweight the badness of false approvals when they are less frequent than false escalations, which is often the case. Cost-sensitive learning and asymmetric loss functions exist precisely to encode this kind of domain knowledge. The precautionary principle, which appears in domains from environmental policy to pharmaceutical approval, reflects the same intuition: when the costs of false negatives and false positives differ substantially, optimize for the more costly error type even at the expense of more frequent nuisance errors.

For a proxy agent, the asymmetry should be baked into the design: the threshold for acting autonomously should be higher than a pure accuracy optimization would suggest, because the cost of a false approval is higher than the cost of a false escalation. This is not a tuning parameter to be adjusted by hand — it is a structural property of the decision function.

### Where TeaParty Stands

Most current agent frameworks treat human oversight as a configuration parameter. You set an escalation threshold and the system escalates more or less depending on its confidence. This is better than nothing, but it is static, impersonal, and unlearned. The threshold does not update as the system builds a history with a particular human. It does not distinguish between a decision type the agent has handled successfully dozens of times and one it has never seen. It does not reflect the human's actual tolerance for different kinds of errors.

TeaParty's proxy agent is a different design. It maintains a persistent memory of prior decisions, modeled using activation-based retrieval inspired by ACT-R's declarative memory system (Anderson & Lebiere, 1998): recently accessed memories and frequently accessed memories are more readily retrieved, mirroring the recency and frequency effects observed in human memory. The proxy makes predictions using a two-pass model — a prior based on categorical similarity to past decisions, updated to a posterior by contextual features of the current decision. The gap between prediction and outcome, when the human's actual decision diverges from the proxy's prediction, is the signal that drives learning: it is extracted as a surprise, stored with its context, and used to recalibrate the proxy's model going forward.

The result is a proxy that earns autonomy through demonstrated alignment rather than being configured to a fixed level. Each decision the proxy makes correctly, and each decision the human confirms without correction, is evidence of alignment. Each surprise narrows the proxy's confidence interval and triggers more frequent escalation until the model has recovered. The asymmetric regret weighting is structural: the cost of false approval always exceeds the cost of false escalation, so the proxy errs toward asking.

This positions TeaParty against the intellectual landscape in a specific way. The supervisory control literature identifies the problem. The adjustable autonomy work identifies the aspiration: autonomy that is earned, not assigned. The trust calibration literature identifies the failure modes that the design must avoid. The proxy agent and preference learning traditions identify the mechanisms. TeaParty's contribution is to assemble these pieces into an operational system at the application layer, where preferences are personal and contextual, where the learning loop runs in real time, and where the cost asymmetry is encoded rather than assumed away.

---

## References

Anderson, J. R., & Lebiere, C. (1998). *The Atomic Components of Thought*. Lawrence Erlbaum Associates.

Bradshaw, J. M., Feltovich, P., Jung, H., Kulkarni, S., Taysom, W., & Uszok, A. (2003). [Dimensions of adjustable autonomy and mixed-initiative interaction](https://dl.acm.org/doi/10.1007/978-3-540-25928-2_3). *Proceedings of the 2003 International Conference on Agents and Computational Autonomy (AUTONOMY 2003)*. Springer.

Christiano, P., Leike, J., Brown, T. B., Martic, M., Legg, S., & Amodei, D. (2017). [Deep reinforcement learning from human preferences](https://arxiv.org/abs/1706.03741). *Advances in Neural Information Processing Systems (NeurIPS 2017)*.

Houlsby, N., Huszar, F., Ghahramani, Z., & Lengyel, M. (2011). [Bayesian active learning for classification and preference learning](https://arxiv.org/abs/1112.5745). *arXiv preprint arXiv:1112.5745*.

Lee, J. D., & See, K. A. (2004). [Trust in automation: Designing for appropriate reliance](https://journals.sagepub.com/doi/10.1518/hfes.46.1.50_30392). *Human Factors: The Journal of the Human Factors and Ergonomics Society, 46*(1), 50--80.

Lieberman, H. (1995). [Letizia: An agent that assists web browsing](https://dl.acm.org/citation.cfm?id=1625975). *Proceedings of the 14th International Joint Conference on Artificial Intelligence (IJCAI 1995)*, 924--929.

Maes, P. (1994). [Agents that reduce work and information overload](https://dl.acm.org/doi/10.1145/176789.176792). *Communications of the ACM, 37*(7), 30--40.

Ouyang, L., Wu, J., et al. (2022). [Training language models to follow instructions with human feedback](https://arxiv.org/abs/2203.02155). *Advances in Neural Information Processing Systems (NeurIPS 2022)*.

Parasuraman, R., Sheridan, T. B., & Wickens, C. D. (2000). [A model for types and levels of human interaction with automation](https://dl.acm.org/doi/10.1109/3468.844354). *IEEE Transactions on Systems, Man, and Cybernetics -- Part A: Systems and Humans, 30*(3), 286--297.

Sarter, N. B., & Woods, D. D. (1995). [How in the world did we ever get into that mode? Mode error and awareness in supervisory control](https://journals.sagepub.com/doi/10.1518/001872095779049516). *Human Factors, 37*(1), 5--19.

Sheridan, T. B. (1992). *Telerobotics, Automation, and Human Supervisory Control*. MIT Press.

Tian, T., et al. (2024). [Active preference learning for large language models](https://arxiv.org/abs/2402.08114). *arXiv preprint arXiv:2402.08114*.
