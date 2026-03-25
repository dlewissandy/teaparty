# Conversation Patterns for Agent Coordination

## Background

Every coordination protocol makes a bet about what coordination fundamentally is. Shared memory architectures bet that coordination is about shared state. Message-passing systems bet it is about information routing. Auction-based systems bet it is about incentive alignment. TeaParty's Conversation for Action (CfA) protocol makes a different bet: that coordination is a speech act — that work gets done by making and fulfilling commitments, and that the structure of those commitments can be made explicit in a protocol that both humans and AI agents can execute.

This essay traces the intellectual lineage behind that bet.

---

## The Language-Action Perspective

In 1986, Terry Winograd and Fernando Flores published *Understanding Computers and Cognition: A New Foundation for Design*, a book that was simultaneously a philosophy of mind, a critique of AI, and a proposal for how software should be built. Their central argument was that computers, as then conceived, were built on a mistaken model of what human cognition and communication actually are. The prevailing model treated cognition as information processing and communication as information exchange — the transfer of packets of meaning from one mind to another. Winograd and Flores argued this was wrong on both counts.

Drawing on Heidegger's phenomenology and the speech act theory of Austin and Searle, they proposed what they called the Language-Action Perspective: the idea that language is not primarily a vehicle for describing the world, but the medium through which humans take action in it. When a manager says "I need this done by Friday," she is not reporting a fact about her psychological state. She is performing a *directive* — creating an obligation that changes the practical situation for everyone involved. When the engineer replies "I'll have it to you Thursday," he is not predicting the future. He is performing a *commissive* — a promise that creates accountability and opens the door to legitimate complaint if it is broken.

The structure Winograd and Flores identified as the fundamental unit of coordination is the Conversation for Action (CfA). In its canonical form, it proceeds through a small number of states: a request is made, the request is accepted (a promise) or declined, the work is performed, completion is reported, and completion is acknowledged. Each transition is a speech act. The conversation is complete only when both parties reach mutual acknowledgment — when the requester accepts that the conditions of satisfaction have been met. The diagram is deceptively simple: fewer than a dozen states, fewer than twenty transitions. But it captures the essential shape of how cooperative work actually unfolds, including the legitimate exits: a request can be counter-offered, declined, or withdrawn; a promise can be revoked; completion can be rejected as unsatisfactory.

What made this radical was the claim that the CfA is not just a description of how humans coordinate, but a *normative* structure that can be designed into systems. Winograd and Flores built this claim into their Action Technologies product — software for managing workflows as networks of conversations rather than as dataflow. The CfA became a protocol.

But Winograd and Flores were designing for human-to-human coordination. Their model assumes that the participants share a vast and largely unspoken background of practices, norms, and interpretations. When a manager makes a request, the engineer already knows what acceptable work looks like, what the relevant constraints are, what "done" means in this context. The CfA protocol does not need to encode any of this — it sits on top of it. When one of the participants is an AI agent, this background cannot be assumed. The protocol must carry what humans could leave implicit.

---

## Speech Acts as State Transitions

The philosophical foundations of the CfA go back further than Winograd and Flores. J.L. Austin's *How to Do Things with Words* (1962), drawn from his William James lectures at Harvard, made the foundational observation that many utterances are not descriptions at all. They are *performative*: saying "I apologize" does not describe an apology taking place; it performs one. "I declare the session open" does not report a state of affairs; it creates one. Austin distinguished the *locutionary act* (what is said), the *illocutionary act* (what is done in saying it — promising, ordering, warning), and the *perlocutionary act* (what effect the utterance achieves in the hearer).

John Searle systematized this framework in *Speech Acts* (1969) and refined the taxonomy further in *Expression and Meaning* (1979), settling on five fundamental categories of illocutionary acts: assertives (committing the speaker to the truth of a proposition), directives (attempting to get the hearer to do something), commissives (committing the speaker to a future action), expressives (expressing psychological states), and declarations (bringing about the state of affairs they name). The last category is the purest case of language as action: a judge saying "I sentence you to five years" does not describe a sentencing — it *is* the sentencing.

What matters for coordination protocols is that Searle's taxonomy maps cleanly onto the moves in a CfA-style conversation. A request is a directive. An acceptance is a commissive. A completion report is an assertive. An acknowledgment is often a declaration — "I accept this work as complete" — that closes the conversation and discharges the obligation. The formal machinery of speech act theory gives us a principled account of why these are the relevant categories and not others: they correspond to the fundamental ways in which utterances can change the normative situation between participants. Making this explicit is what distinguishes a coordination protocol from an ad hoc message format.

The implication for AI systems is that agents participating in a coordination protocol need to understand not just the semantic content of messages, but their illocutionary force. An agent that treats "can you have this done by Thursday?" as a yes/no question rather than a request has misunderstood the act, regardless of whether it understood the words.

---

## The Plan-Execute Loop and Its Limits

Most agent systems built in the last few years do not think about coordination in these terms at all. They think about it in terms of planning and execution.

The dominant paradigm is some variant of: decompose the goal into steps, execute the steps, observe the results, revise if necessary. ReAct (Yao et al., 2023), published at ICLR 2023, interleaves reasoning traces with action execution — at each step, the agent generates a thought, takes an action, and observes the result. The insight is that interleaving reasoning and acting outperforms either alone, and that making the reasoning visible improves diagnosability. Plan-and-Solve (Wang et al., 2023), published at ACL 2023, addresses a related failure mode: zero-shot chain-of-thought prompting tends to skip steps and produce calculation errors. Plan-and-Solve explicitly separates plan generation from plan execution, nudging the model to first lay out the full sequence before executing any of it.

Both of these are valuable contributions to the mechanics of single-agent reasoning. But neither addresses the coordination problem. The user's request is treated as a complete specification. Ambiguity in the goal is handled, if at all, by the agent's internal reasoning, not by a protocol that creates space for clarification before work begins. There is no concept of intent alignment — no structured process for establishing shared understanding of what success looks like before committing resources to execution. There is no approval gate — no point at which a human or supervising agent reviews the plan and decides whether to proceed. And when something goes wrong, the recovery model is local: retry the step, try a different tool, generate a revised chain of thought. The idea that correct recovery might require going all the way back to rethink the goal — that the plan might be wrong because the intent was misspecified, not because execution failed — has no place in this model.

This is not a criticism of ReAct or Plan-and-Solve on their own terms. They solve a different problem: improving the reasoning quality of individual agents on well-specified tasks. The limitation becomes acute when the task is not well-specified, when the agent is operating as part of a team, or when the human's intent is something that needs to be *established* rather than *given*.

---

## Multi-Agent Coordination: Task Assignment Without Intent

The multi-agent coordination literature approaches the problem from the other direction. Rather than starting with a single agent and asking how it should reason, it starts with multiple agents and asks how they should divide and allocate work.

The Contract Net Protocol (Smith, 1980) is the foundational result. Published in IEEE Transactions on Computers, it introduced a market-inspired mechanism for task allocation in distributed problem-solving systems: a manager broadcasts a task announcement to potential contractors, contractors submit bids, and the manager awards the contract to the best bidder. This is elegant and has proven remarkably durable — Contract Net has influenced multi-agent systems design for four decades. It handles the allocation problem well. What it does not handle is the problem of task definition. The task announcement is assumed to be already complete and unambiguous. The contractors bid on a specification, not on a goal. When the specification is underspecified — when what the requester actually wants cannot be fully articulated in advance — Contract Net has nothing to say.

Blackboard architectures (Hayes-Roth, 1985) take a different approach: multiple specialized knowledge sources read from and write to a shared working memory. A scheduler determines which knowledge source should act next based on the current state of the blackboard. This is coordination by shared state rather than by message passing. It handles incremental, opportunistic problem-solving well — each knowledge source contributes when it has something to contribute — but it scales poorly to systems where the agents are humans or LLMs, and it offers no mechanism for commitment tracking or accountability.

Contemporary multi-agent LLM frameworks preserve these structural choices while updating the implementation. AutoGen (Wu et al., 2024) provides a programming model for multi-agent conversations where agents can be humans, LLMs, or tools, and where conversations are structured as back-and-forth message exchanges. It is genuinely flexible and has proven useful across a wide range of applications. But the conversation structure it provides is essentially unstructured: agents send messages to each other, and the content of those messages determines what happens next. There is no protocol enforcing that a planning phase must be approved before execution begins, no mechanism for a cross-phase backtrack when execution reveals that the original intent was misunderstood, and no concept of mutual acknowledgment as the formal closure of a coordination unit. LangGraph offers a graph-based state machine for agent workflows, which adds more structure, but the structure is control flow rather than speech acts — it specifies the sequence of operations rather than the conversational commitments those operations constitute.

---

## The Gap: Shared Context in Mixed Teams

The gap these frameworks leave open becomes most visible in mixed human-agent teams.

Human teams develop shared mental models — overlapping representations of the task, the team's capabilities, and the coordination requirements — through conversation, observation, and accumulated experience working together. This shared model is what makes implicit coordination possible: experienced teammates can anticipate each other's moves, interpret ambiguous signals correctly, and recover from misalignment without explicit negotiation. Studies of human-AI teaming have found that AI teammates can impede this process: communication with AI tends to be more constrained, shared mental models develop more slowly, and the rich back-channel of human communication — tone, hesitation, shared references — is unavailable (Demir et al., 2020).

The fundamental issue is that what human teams leave implicit, human-AI teams cannot. An AI agent has no accumulated context about the team's history, no sensitivity to the pragmatic implications of phrasing, no ability to read the room. This is not a deficiency that can be patched with better prompts — it is a structural feature of the situation. The shared background that Winograd and Flores could assume is simply absent.

The consequence is that coordination protocols for mixed teams need to do more explicit work. They need to create structured processes for establishing shared understanding before execution begins (intent alignment), for validating the plan against that understanding before resources are committed (plan approval), and for recognizing when execution has revealed that the plan — or the intent itself — needs to be revised. Backtracks are not failure modes. They are the protocol's mechanism for handling the inevitable gap between initial specification and discovered reality.

---

## TeaParty's CfA Protocol

TeaParty's CfA protocol is a direct response to this gap. It implements the Winograd-Flores Conversation for Action as a three-phase state machine — Intent, Planning, Execution — with approval gates between phases. Each phase follows the structure of a speech act conversation: the intent team proposes a formulation of the goal, the human reviews and either accepts, refines, or rejects it, and only on acceptance does the protocol advance to planning. The same pattern holds between planning and execution. These gates are not bureaucratic checkpoints; they are the moments at which the commissive is made — the team commits to a course of action, and the human authorizes the commitment.

Cross-phase backtracks are first-class citizens of the protocol. A discovery during execution can trigger a return to planning (because the plan is wrong) or a return to intent alignment (because the goal itself needs to be rethought). The protocol does not treat this as an error condition; it provides explicit states and transitions for it. This reflects the Winograd-Flores insight that the legitimate moves in a coordination conversation include withdrawal and renegotiation — a promise can be revoked if circumstances change, and the protocol should support that gracefully rather than forcing a completion-or-failure binary.

What distinguishes this from the plan-execute loop paradigm is that it treats ambiguity and discovery as expected rather than exceptional. What distinguishes it from the Contract Net and its successors is that it addresses the problem of intent, not just allocation. And what distinguishes it from AutoGen-style conversational frameworks is that the protocol enforces a structure of commitment rather than leaving the conversation's shape entirely to the content of messages.

The bet is that explicit commitment structure — carried in the protocol rather than assumed from shared background — is what makes coordination reliable when the participants cannot rely on that background. In mixed human-agent teams, the protocol has to do work that culture and history do in human teams. That is the design premise of TeaParty's CfA.

---

## References

- Austin, J.L. (1962). [*How to Do Things with Words*](https://pure.mpg.de/rest/items/item_2271128/component/file_2271430/content). Harvard University Press.

- Demir, M., McNeese, N. J., & Cooke, N. J. (2020). [Understanding human-robot teams in light of all-human teams: Aspects of team interaction and shared cognition](https://doi.org/10.1016/j.ijhcs.2020.102436). *International Journal of Human-Computer Studies*, 140, 102436.

- Hayes-Roth, B. (1985). [A blackboard architecture for control](https://dl.acm.org/doi/10.1016/0004-3702(85)90063-3). *Artificial Intelligence*, 26(3), 251–321.

- Searle, J.R. (1969). *Speech Acts: An Essay in the Philosophy of Language*. Cambridge University Press.

- Searle, J.R. (1979). [*Expression and Meaning: Studies in the Theory of Speech Acts*](https://altexploit.files.wordpress.com/2019/10/john-r.-searle-expression-and-meaning-_-studies-in-the-theory-of-speech-acts-1979.pdf). Cambridge University Press.

- Smith, R.G. (1980). [The Contract Net Protocol: High-level communication and control in a distributed problem solver](https://dl.acm.org/doi/10.1109/TC.1980.1675516). *IEEE Transactions on Computers*, 29(12), 1104–1113.

- Wang, L., Xu, W., Lan, Y., Hu, Z., Lan, Y., Lee, R.K.-W., & Lim, E.-P. (2023). [Plan-and-Solve Prompting: Improving zero-shot chain-of-thought reasoning by large language models](https://aclanthology.org/2023.acl-long.147/). In *Proceedings of ACL 2023*.

- Winograd, T., & Flores, F. (1986). [*Understanding Computers and Cognition: A New Foundation for Design*](https://dl.acm.org/doi/book/10.5555/5245). Ablex.

- Wu, Q., Bansal, G., Zhang, J., Wu, Y., Li, B., Zhu, E., Jiang, L., Zhang, X., Zhang, S., Liu, J., Awadallah, A.H., White, R.W., Burger, D., & Wang, C. (2024). [AutoGen: Enabling next-gen LLM applications via multi-agent conversation](https://arxiv.org/abs/2308.08155). *Proceedings of COLM 2024*.

- Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., & Cao, Y. (2023). [ReAct: Synergizing reasoning and acting in language models](https://arxiv.org/abs/2210.03629). In *Proceedings of ICLR 2023*.
