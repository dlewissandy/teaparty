# Intent Engineering: Detailed Design

## 1. Foundation

The theoretical basis for intent engineering — the intent gap, the Klarna pattern, the three missing architectural layers, and the relationship between prompt engineering, context engineering, and intent engineering — is documented in `intent-engineering-spec.md`. This document begins where the spec ends: it specifies how to build the system the spec describes. Readers who need the rationale should read the spec first. Readers who need the implementation specification should start here.

---

## 2. What the System Produces: INTENT.md

### 2.1 Structure and Content

INTENT.md is a prose document written in natural language. Its structure follows the shape of the problem, not a fixed template. Some projects will need extensive escalation guidance and minimal constraints; others will be constraint-heavy with obvious objectives. The document must capture what matters, not check boxes.

Five types of content must be present in every INTENT.md, though their relative weight and ordering should follow the problem:

**Objective.** What outcome the human wants and why it matters. Not the task — the purpose the task serves. The test: if you remove the "why," does a reader know what success looks like for the organization, or only what the agent should produce? A document that specifies the deliverable without the purpose fails this test. The objective should be one to three sentences. Longer means the purpose has not been distilled.

**Success criteria.** Both quantifiable thresholds and qualitative values. Qualitative criteria are first-class. They are a different kind of signal, not a lesser version of quantitative criteria. "The output should feel like a sharp colleague wrote it, not a tool" is a legitimate success criterion — it tells the agent what to optimize for in the unmeasured space. Quantitative criteria provide clear pass/fail signals. Qualitative criteria govern the space between the quantitative signals. Both are required.

**Decision boundaries and escalation posture.** Where the agent should use its own judgment, where it must stop and consult the human, and what it must never do. This is not a static checklist. It is a narrative that captures the human's risk tolerance for this specific project. It should be elicited through scenario discussion ("what would make you want to stop and check?") rather than direct questioning about preferences ("what are your escalation preferences?"). The distinction matters: scenarios reveal actual tolerance, while direct questions produce stated preferences that often diverge from revealed ones. This section should name specific domains or decision types and specify posture for each. It should include stop rules — things the agent must never do regardless of circumstance — separately from escalation thresholds, which are context-dependent.

**Constraints.** Technical, organizational, temporal, and resource boundaries the solution must satisfy. Constraints are different from success criteria: constraints define the solution space, success criteria define what winning looks like within it. A constraint violated produces an invalid solution regardless of how well it meets the success criteria. Constraints must be stated precisely enough that their satisfaction is unambiguous.

**Open questions.** Ambiguities and design decisions that cannot be resolved during intent gathering. These are not a parking lot — they are an active handoff to the planning phase. Each open question must contain: the question itself, why it cannot be resolved now (what information is missing), and what the planning phase must do with it (research options and present alternatives, or hold for human decision before execution begins). A parking lot of unresolved questions signals that intent gathering did not go far enough. The correct bar is: everything that can be resolved through conversation and available research has been resolved.

### 2.2 Anti-Patterns

INTENT.md is not:

A requirements specification or feature list. Requirements specify what to build. Intent specifies why and for whom, with what values governing the tradeoffs that emerge during building. An INTENT.md that reads like a product requirements document has failed.

A bullet-point summary of the conversation. The document should read as if the human wrote it themselves — a coherent, self-contained statement of purpose that could be handed to someone who was not in the conversation and give them everything they need to make good decisions downstream.

A form with fields. The five content types above are not section headers. They are the minimum coverage required, in whatever structure serves the problem.

A low-confidence first draft that "will be refined later." INTENT.md is a governing document. It must be complete enough to govern planning and execution without requiring follow-up clarification. It is updated during intent gathering as the conversation develops, but by the time it is approved it must be authoritative.

### 2.3 Quality Gates

Every sentence in INTENT.md must satisfy three criteria:

**Earn its place.** If removing a sentence would not change the reader's ability to understand the intent, remove it. This applies to every clause, not just every section. Padding — restatements of the obvious, courtesy hedges, phrases that soften rather than specify — reduces document quality by diluting signal.

**Pass the reasonable person test.** Read the document as someone who was not in the room. If they cannot proceed with what they've been given — if they would face a decision that requires knowledge not captured in the document — the document is incomplete. The test is strict: not "could a reasonable person figure it out" but "does this document give them what they need."

**Bring solutions, not questions.** When the document reaches a decision boundary, it should specify the boundary, not gesture at it. "The agent should use judgment about timing" is not a specification. "The agent should not send customer-facing communications outside business hours without explicit authorization; within business hours it may send on judgment up to two follow-ups per thread" is a specification.

---

## 3. Conversation Protocol

### 3.1 Turn Structure and Constraints

The intent gathering conversation operates under a 15-minute constraint for moderate-complexity projects. This constraint is not aspirational — it is a design requirement that shapes the conversation protocol.

Each call to the claude process is bounded to three turns maximum per invocation. This is not an arbitrary limit: three turns forces the agent to make meaningful progress in each exchange rather than using unlimited turns to meander toward clarity. The conversation is bounded to ten rounds maximum (one round = one human response + one claude invocation). Ten rounds at three turns each provides 30 turns of total conversation budget, sufficient for complex projects while enforcing discipline.

Time accounting: at round 8 of 10, the intent-lead should signal that it is preparing to finalize INTENT.md and ask for anything the human has not yet stated. At round 10, it must write INTENT.md regardless of remaining open questions, noting what remains unresolved. The 15-minute wall should be enforced by intent.sh: warn at 12 minutes, write INTENT.md at 15 minutes.

### 3.2 What the Agent Does on Turn 1

The first turn is not the time to ask the human what they want. The human has already stated a task. The first turn is the time for the agent to demonstrate that it has engaged with the problem space before asking the human to do any work.

Turn 1 structure:
1. State what the agent understands about the task from the initial input — specifically, concretely, without hedging.
2. State what the agent has researched or already knows about the relevant domain — technologies named, constraints implied, organizational context visible in the task description. This is where research-liaison dispatches should already be in flight.
3. Identify the two or three most important unknowns — the decisions that the human must make that the agent cannot resolve through research.
4. Ask a single question, the most important unknown, framed with the agent's current best answer and its rationale.

The agent must not ask open-ended questions ("what are your goals?", "what constraints do you have?"). Every question must be preceded by the agent's current best understanding and at least two concrete options with tradeoffs. The human's job is to decide between well-researched alternatives, not to do the agent's research for it.

### 3.3 Research During Dialog

The research-liaison exists to prevent the intent-lead from asking questions that a web search could answer. Whenever the human names a technology, platform, organization, domain constraint, or regulatory context, the research-liaison should dispatch a research request without waiting to be asked.

A good research request is specific: "What are the rate limits and authentication requirements for the Stripe webhook API?" is correct. "Research Stripe" is not. The research-liaison should return findings to the intent-lead via SendMessage within two to three minutes. The intent-lead integrates findings into its next response.

Research should not opine on the human's values or make judgments about what the human should want. It surfaces facts, constraints, and options. The human decides what matters.

### 3.4 "Bring Solutions, Not Questions" — Operationalized

This principle governs every question the intent-lead asks and every escalation the execution agents make.

Anti-pattern (bare question): "What deployment environment do you want to target?"

Correct pattern: "I'm assuming deployment to AWS given your team's infrastructure. The main tradeoff is between ECS Fargate (simpler operations, higher per-unit cost) and EKS (more operational overhead, better for high-traffic workloads). For the scale you described, Fargate is likely right — does that hold, or are there constraints I should know about?"

The correct pattern requires the agent to have already researched the relevant options, formed a view based on available context, and structured the exchange so the human is making a decision, not generating options from scratch.

Every question must contain: what the agent already knows and assumes, at least two concrete alternatives with their tradeoffs, and a recommended default with reasoning. If the human has strong preferences that override the recommendation, that is useful signal. If the human agrees with the recommendation, the conversation moves forward efficiently.

### 3.5 Cold Start Protocol

When the system has no prior context with this human or project domain, the conversation follows this pattern:

The agent opens by stating what it knows from the task description, flags what it has dispatched for research, and asks the single most important question. INTENT.md is started immediately — the objective and any constraints visible from the initial task go into the document in the first turn, even if they are preliminary.

Each subsequent turn: update INTENT.md first (the human sees the updated document between turns and can approve at any time), then surface the next most important open question using the solution-first pattern. Do not ask multiple questions per turn. Ask the one that, if answered, most reduces uncertainty about what the agent should optimize for.

Escalation posture is surfaced through scenario exploration, not through direct inquiry. Rather than "what are your escalation preferences?", the agent should present a specific scenario: "If during execution I find that the API we planned to use has changed its authentication scheme and I need to modify the integration approach — do you want me to handle that autonomously, or stop and check with you?" Two or three such scenarios per project type reveal the human's actual tolerance with more precision than any abstract discussion.

The objective section of INTENT.md must be complete before the conversation ends. The success criteria section must be at least partially complete. The decision boundaries section is typically the last to mature, because it requires the human to have thought through the failure modes — something that usually only happens after the objective and constraints are clear.

### 3.6 Warm Start Protocol

When the system has accumulated observations from prior interactions with this human or this project domain, the warm start protocol applies.

At the start of the conversation, the agent states explicitly what it has pre-populated from prior context and marks each element clearly: "(from prior sessions: [source])". It does not silently assume these elements apply. Pre-population reduces conversation length only when the human confirms that prior observations still hold. Every pre-populated element is a question, not an assertion.

Confirmation pattern: "Based on prior sessions, I've pre-filled your preference for TypeScript with strict null checking, and an escalation posture of 'check with me before any external API integrations.' Do both still apply to this project, or has anything changed?"

When a human corrects a pre-populated element, that correction is high-value signal: the model has diverged from reality. The correction must be written explicitly to the session learning record with a note that it overrides a prior observation. This is more valuable than confirming that a prior observation still holds, because corrections reveal where the model is wrong.

Warm start should reduce conversation length proportionally to the system's confidence in prior observations. A session with many high-confidence observations may need only two or three rounds to confirm and extend. A session where prior observations have low confidence or the project domain is novel should run close to the cold-start protocol.

---

## 4. Least-Regret Escalation Design

### 4.1 The Formal Model

At every decision point, an autonomous agent faces a binary choice: act or ask. Both options carry risk.

Expected regret of acting = P(human wanted to be consulted) × cost(acting when should have asked)

Expected regret of escalating = P(agent could have handled it) × cost(escalating when should have acted)

Choose the action with lower expected regret.

These costs are not symmetric. Acting when the human wanted to be consulted may cause wrong work, violated values, eroded trust, or irreversible damage. Escalating when the agent could have handled it wastes the human's time and fails to deliver on the promise of autonomy. These failure modes have different costs in different organizations, for different humans, in different domains, and for different types of decisions. The model must learn these costs; it cannot be configured with universal constants.

### 4.2 Risk Tolerance Model

The risk tolerance model is a per-domain record of observed escalation preferences. Its schema:

```json
{
  "domain": "string (project category or domain slug)",
  "threshold": "float (0.0–1.0; higher = more autonomy granted)",
  "confidence": "float (0.0–1.0; based on signal count)",
  "signal_count": "integer",
  "last_calibrated": "ISO8601 timestamp",
  "signals": [
    {
      "type": "positive | negative | neutral",
      "description": "what happened",
      "timestamp": "ISO8601"
    }
  ]
}
```

Positive signal: the human accepted an autonomous action without correction. The threshold shifts upward by a small delta (suggested: 0.05).

Negative signal: the human corrected an autonomous action or expressed that they wanted to be consulted. The threshold shifts downward by a larger delta (suggested: 0.10). Negative signals are weighted more heavily because the cost of acting when the human wanted to be consulted is typically higher than the cost of unnecessary escalation.

Neutral signal: the human accepted an action but modified the output before proceeding. Small downward shift (suggested: 0.02).

Cold start default threshold: 0.3 for all domains. This biases toward escalation, which is the correct posture when the model has no data. The threshold rises toward autonomy as data accumulates, and falls back toward escalation when the human expresses surprise or makes corrections.

### 4.3 Action Cost Matrix

Before choosing to act or ask, the agent estimates two properties of the decision:

**Reversibility:** How hard is it to undo this action if it turns out to be wrong? On a four-point scale: fully reversible (delete the file), mostly reversible (revert the code change, but time was spent), partially reversible (sent an email; can send a follow-up, but the first impression is set), irreversible (deleted the database, published the article, charged the customer).

**Organizational impact:** How widely does this action affect people or systems beyond the immediate task? On a four-point scale: local (affects only the current file or artifact), team (affects other people's work), organizational (affects policies, external communications, or resources shared across teams), external (affects customers, partners, or public reputation).

The decision matrix:

| Reversibility | Local impact | Team impact | Org impact | External impact |
|---|---|---|---|---|
| Fully reversible | Autonomous | Autonomous | Autonomous unless threshold < 0.4 | Escalate unless threshold > 0.7 |
| Mostly reversible | Autonomous | Autonomous unless threshold < 0.3 | Escalate unless threshold > 0.6 | Escalate |
| Partially reversible | Autonomous unless threshold < 0.3 | Escalate unless threshold > 0.6 | Escalate | Always escalate |
| Irreversible | Escalate unless threshold > 0.8 | Escalate | Always escalate | Always escalate |

"Always escalate" means escalate regardless of the domain threshold — these are decisions that require human authorization regardless of how much autonomy has been earned.

### 4.4 Escalation Posture in INTENT.md

The decision boundaries section of INTENT.md must encode the human's escalation posture in a form that execution agents can consume directly.

For each decision domain identified during intent gathering, INTENT.md should specify:
- Whether the agent should act autonomously, act and notify, or stop and check
- What specifically triggers a "stop and check" (the scenario, not just the category)
- What the agent must never do (stop rules)

Stop rules are distinct from escalation thresholds. A threshold is a probabilistic preference: "I'd rather not be bothered with routine API key rotation." A stop rule is an absolute constraint: "Never commit to main directly; always use a pull request with at least one review." Stop rules apply regardless of how much domain autonomy has been earned.

When an execution agent escalates, the escalation must contain three things: the situation (what was encountered), the recommended action (what the agent proposes to do, with reasoning), and the cost of waiting (what the impact is if the human does not respond within a time window). A bare question — "I encountered this situation, what should I do?" — is not a valid escalation. The agent must have done the work before escalating.

---

## 5. Institutional Memory Integration

### 5.0 Current Implementation vs. Target Architecture

The JSON schemas in Sections 5.1–5.4 describe the target record format for institutional memory. The POC implementation uses a simpler markdown-backed architecture that is already built and functional. Understanding the gap prevents implementers from building the target architecture before the POC validates the approach.

**Current implementation (what exists today):**
- `OBSERVATIONS.md` — human preference signals appended by `summarize_session.py` (scope: `observations`)
- `ESCALATION.md` — autonomy calibration signals appended by `summarize_session.py` (scope: `escalation`)
- `.memory.db` — SQLite FTS5 index of the above files, built and queried by `memory_indexer.py`
- Retrieval uses BM25 full-text search with optional hybrid embedding reranking

**How the JSON schemas apply today:** The schemas in 5.1–5.4 define the *semantic structure* of what `summarize_session.py` extracts and writes to the markdown files. They are not stored as discrete JSON records; they are the conceptual model that shapes the extraction prompts. A user observation record, for example, becomes a structured paragraph in OBSERVATIONS.md rather than a JSON file entry.

**When to migrate:** When the observation corpus grows large enough that flat-file retrieval degrades (rough threshold: OBSERVATIONS.md exceeds 50KB or retrieval precision drops visibly), migrate to structured JSON storage. Until then, the markdown-backed architecture provides sufficient warm-start quality with minimal infrastructure.

**Embedding provider:** `memory_indexer.py` supports OpenAI and Gemini embeddings but requires API keys. Run BM25-only for the POC (omit the embedding provider flag) unless embeddings are already configured in the environment. BM25 is adequate for corpora with fewer than 100 observations.

### 5.1 What Memory Must Contain

The intent engineering system is both a consumer and a producer of institutional memory. It consumes observations accumulated from prior sessions to reduce the burden of intent gathering. It produces observations — corrections, confirmations, new preferences, escalation calibration signals — that improve future sessions.

The memory architecture must support four record types for intent to function:

**User observation record.** Captures a specific learned preference or observed behavior pattern.

```json
{
  "id": "uuid",
  "user_id": "string",
  "scope": "individual | team | organization",
  "domain": "string (project category or freeform domain)",
  "key": "string (what was observed)",
  "value": "string (the observation)",
  "confidence": "float (0.0–1.0)",
  "source": "stated | revealed | inferred",
  "signal_count": "integer",
  "first_observed": "ISO8601",
  "last_updated": "ISO8601",
  "sessions": ["session_id array"]
}
```

Source types matter: stated preferences (the human said "I prefer X") carry less weight than revealed preferences (the human consistently corrected toward X despite saying otherwise) and inferred preferences (the agent observed X from behavior without explicit statement). When stated and revealed preferences conflict, the conflict should be surfaced at the next intent gathering session, not silently resolved.

**Escalation calibration record.** The risk tolerance model described in Section 4.2.

**Project-domain index.** Maps project category slugs (as produced by classify_task.py) to domain slugs in the escalation model. This is the mechanism by which project-level categorization provides the initial domain index for escalation thresholds.

```json
{
  "project_category": "string",
  "domain_slugs": ["string array"],
  "confidence": "float",
  "last_updated": "ISO8601"
}
```

**Session learning record.** Captures what was learned in a completed intent gathering session.

```json
{
  "session_id": "string",
  "project_category": "string",
  "intent_file": "string (path)",
  "new_observations": ["observation_id array"],
  "updated_observations": ["observation_id array"],
  "corrections_to_priors": ["correction record array"],
  "escalation_signals": ["signal record array"],
  "outcome_observations": ["observation_id array"],
  "extracted_at": "ISO8601"
}
```

### 5.2 Retrieval for Warm Start

When a new intent gathering session begins, the system queries institutional memory for observations relevant to the current task. The retrieval query combines two signals: semantic similarity to the task description, and recency (more recent observations are weighted more heavily because preferences drift).

Retrieval returns a ranked list of observations. The intent-lead pre-populates INTENT.md with observations whose confidence exceeds 0.7. Observations with confidence between 0.4 and 0.7 are surfaced as explicit questions in the conversation ("I've seen this preference before but I'm not confident it still applies — does this hold?"). Observations below 0.4 are not surfaced.

When individual, team, and organizational priors conflict, the conflict must be surfaced explicitly. The system does not silently resolve conflicts by priority — a team convention that conflicts with an individual preference is a real organizational ambiguity that a human must adjudicate. Silently applying one over the other causes the kind of subtle misalignment that accumulates over time.

### 5.3 Post-Session Learning Extraction

After a successful intent gathering session (INTENT.md approved by human), the system extracts learnings from the session stream via summarize_session.py. Extraction should happen asynchronously, after the human approves INTENT.md, as the session moves into the planning phase.

What to extract:
- New observations: statements the human made about preferences, values, or constraints not previously recorded
- Updated observations: confirmations or modifications to prior observations
- Corrections to priors: explicit rejections of pre-populated elements; these must be flagged as high-value signal
- Escalation calibration signals (if any escalation occurred during the session)

The session stream contains the full conversation history. Corrections are identifiable as explicit disagreements with pre-populated content. New observations are identifiable as statements about preferences that do not correspond to any existing record. Confirmations are identifiable as acceptance of pre-populated elements without modification.

Scope assignment: observations made by an individual apply at individual scope by default. Statements explicitly about team or organizational policy (recognizable by "we always", "the team requires", "company policy is") apply at the appropriate broader scope.

Learning extraction feeds into the promote_learnings.sh pipeline, which propagates learnings upward through the scope hierarchy: dispatch → team → session → project → global.

---

## 6. Agent Configuration Specification

### 6.1 Intent-Lead Agent — Full Prompt

The following is the complete prompt for the intent-lead agent. It replaces the minimal prompt in the current agents/intent-team.json.

```
You are the intent lead — the first stage of a production pipeline. Your only deliverable is INTENT.md. After you, a separate planning team takes INTENT.md and produces a plan. Execution agents execute the plan. You do not design solutions, write code, or produce any artifact other than INTENT.md.

Your job is to understand what the human actually wants — not what they said, but what they meant, including the implicit knowledge they've internalized to the point of invisibility: which tradeoffs are acceptable, where quality matters more than speed, what "good enough" looks like, where they want to be consulted and where they trust autonomous judgment.

Three principles govern everything you produce, including INTENT.md itself:

Every sentence must earn its place. If removing a sentence would not change the reader's ability to understand the intent, remove it. Apply this to every clause, not just every section.

Would a reasonable person find this sufficient? Read INTENT.md as someone who was not in the conversation. If they would face a decision not covered by the document, the document is incomplete.

Bring solutions, not questions. Before asking anything, research the problem space and present concrete alternatives with tradeoffs. The human decides between well-reasoned options — they do not generate options from scratch. Never ask a bare question without your current best answer and reasoning.

INTENT.md must contain five types of content: (1) Objective — what outcome and why it matters, not just the deliverable; (2) Success criteria — both quantifiable thresholds and qualitative values, with qualitative treated as first-class; (3) Decision boundaries and escalation posture — where the agent uses judgment, where it stops and checks, what it must never do, elicited through scenarios not abstract preference questions; (4) Constraints — technical, organizational, temporal, resource; (5) Open questions — unresolvable ambiguities, each with the question, why it cannot be resolved now, and what the planning phase must do with it.

INTENT.md must not be: a requirements list, a bullet-point conversation summary, a form with fields, or a low-confidence draft. It must read as if the human wrote it themselves.

Write or update INTENT.md every turn. Do not announce that you are going to write it — just write it alongside your response. Always write the complete document, not a partial update. The human sees INTENT.md between turns and may approve it at any time. Start INTENT.md in the first turn with what you already know from the task description. Update it progressively as the conversation develops.

Conversation strategy: ask one question per turn, the most important remaining unknown. Frame every question with your current assumption and at least two concrete alternatives. Do not ask multiple questions at once. Do not ask questions that research could answer — dispatch those to the research-liaison.

When the human names a technology, platform, domain, or constraint you need to understand concretely: send a task to the research-liaison immediately. Do not wait until you have a question formulated — dispatch as soon as the domain is named.

Escalation posture is surfaced through scenarios: "If I encounter X during execution, would you want me to handle it autonomously or check with you?" Two or three concrete scenarios per project reveal actual risk tolerance more accurately than asking about preferences in the abstract.

Team: intent. Available liaisons: research-liaison — dispatch research tasks via SendMessage when domains require concrete understanding.
```

### 6.2 Research-Liaison Agent — Specification

The research-liaison's role is to prevent the intent-lead from asking questions that research could answer. It must be proactive: when the intent-lead's conversation mentions a domain that requires concrete knowledge (a technology, a platform, an API, an organization, a regulatory context), the research-liaison should dispatch a research request to the research subteam without waiting to be explicitly asked.

Research requests must be specific. "Research Stripe" is not a valid request. "What are the rate limits, authentication requirements, and webhook event types for the Stripe Payments API, and are there any notable recent changes in 2025-2026?" is a valid request.

Findings returned to the intent-lead via SendMessage should be concise: three to five key facts relevant to the conversation, with any constraints that the intent-lead needs to know about. Raw research dumps are not useful. The research-liaison must distill.

Time budget: research must complete within two to three minutes to fit the 15-minute conversation constraint. If a research task will take longer, the research-liaison should send an interim message with what it has and flag that more is coming.

### 6.3 Tool Configuration

**Intent-lead disallowed tools:** TeamCreate, TeamDelete, Task, TaskOutput, TaskStop, Read, Glob, Grep.

Read, Glob, and Grep are disabled because the intent-lead is a conversational agent. It has no filesystem access — the working repository is for the planning and execution teams. Context that requires filesystem access should be provided by the caller (intent.sh) as injected context in the initial prompt, not discovered by the intent-lead at runtime.

TeamCreate and TeamDelete are disabled because the team is statically defined by the intent-team.json specification. Dynamic team creation would circumvent tool restriction enforcement.

Task, TaskOutput, and TaskStop are disabled because cross-team coordination goes through the liaison pattern (SendMessage to research-liaison, who calls dispatch.sh), not through Task tool invocations.

**Research-liaison allowed tools:** All tools including WebFetch, WebSearch, Bash(dispatch.sh), Bash(yt-transcript.sh). The research-liaison has no disallowed tools because its role requires broad access to external information.

**Permission mode:** acceptEdits. The intent-lead must be able to write INTENT.md to the working directory. No other file writes are expected or appropriate during intent gathering.

**Model:** sonnet for both agents. The 15-minute constraint requires a model fast enough to complete multiple turns within the window. Opus provides marginal quality improvement at the cost of latency that makes the constraint difficult to meet.

**Max turns per invocation:**
- Intent-lead: 3. Forces focused exchanges; each invocation = one meaningful advance in the conversation.
- Research-liaison: 10. Research tasks may require multiple search iterations and source synthesis.

---

## 7. Integration with the POC Pipeline

### 7.1 How INTENT.md Flows into Planning

INTENT.md is a governing document, not a suggestion. The planning team receives it as the authoritative statement of purpose and must honor it at every decision point.

plan-execute.sh injects INTENT.md as a context file in the initial planning prompt. The planning agent reads INTENT.md before any other action. The plan it produces must be traceable to INTENT.md: each major decision in the plan should be justifiable by reference to the objective, success criteria, or constraints in INTENT.md.

Open questions in INTENT.md are a mandatory handoff. The planning team must resolve every open question before execution begins. Resolution means: researching the options identified in the open question section, developing well-reasoned alternatives, and presenting them to the human for decision before the execution phase starts. An open question that is not resolved in planning becomes an unguided decision during execution — the worst possible time to face it.

Success criteria in INTENT.md are the evaluation framework for the plan. The planning team should not propose a plan that it cannot explain in terms of how it will satisfy the INTENT.md success criteria. If a planned approach cannot satisfy a stated success criterion, the planner must surface that conflict during planning rather than proceeding and failing during execution.

### 7.2 How Execution Respects Intent

Execution agents receive INTENT.md as injected context at session start. This is not optional — INTENT.md defines the space within which execution is authorized to operate.

The execution agent uses INTENT.md to determine when to escalate. The decision rule: if an encountered situation would require an action whose reversibility and organizational impact exceed the domain threshold (from the escalation matrix in Section 4.3), and the situation is not covered by the decision boundaries in INTENT.md, the execution agent must escalate.

An escalation from an execution agent must contain: the situation encountered (specific, not vague), the action the agent recommends (with reasoning), and the cost of waiting (what fails or is delayed if the human does not respond within a specified time window). A bare question is a failure mode — the agent must do the preparatory work before escalating.

Escalation outcomes are calibration signals. When the human responds "just handle it," the domain threshold shifts upward. When the human responds with a correction or with "you should have checked first," the threshold shifts downward. The outcome is written to the escalation calibration record in institutional memory after the session completes.

**Injecting escalation context into execution agents.** The domain thresholds stored in `ESCALATION.md` must reach the execution agent at session start. `plan-execute.sh` accomplishes this by adding `--context-file "$PROJECT_DIR/ESCALATION.md"` to both the plan and execute invocations. The agent reads the injected context and uses the domain thresholds when evaluating the action cost matrix from Section 4.3.

When a calibration signal occurs — the human responds to an escalation with "just handle it" or with a correction — `plan-execute.sh` appends the signal to `ESCALATION.md` at session end by calling:

```bash
python3 "$SCRIPT_DIR/scripts/summarize_session.py" \
  --stream "$EXEC_STREAM" \
  --scope escalation \
  --session-dir "$STREAM_DIR" &
```

This runs asynchronously after session completion. The signal is available to the next session's warm-start retrieval.

### 7.3 Post-Session Feedback Loop

**Future: Delivery-point instrumentation.** The highest-value feedback signal would be delivery-point instrumentation — tracking how much the human edits output before accepting it, with a high edit-to-acceptance ratio signaling misalignment. This requires file-system instrumentation that is out of scope for the POC. It is documented here as a post-MVP capability. Do not implement it in the current phase. When instrumentation is built, corrections must be distinguished from extensions: a correction changes something the agent produced (misalignment signal); an extension adds something the agent could not have produced from available context (not a misalignment signal).

Lightweight check-ins at natural breakpoints — "this phase is complete; does the direction still feel right?" — supplement the delivery-point signal. These are single-question, low-friction interactions. They are not surveys. The human's response (yes, with modification, or no) is itself a signal: modification indicates partial misalignment; no indicates significant misalignment that requires intent re-evaluation.

Feedback propagates through promote_learnings.sh after session completion: observations extracted from the session stream are written to institutional memory, promoting through the scope hierarchy as appropriate.

---

## 8. Implementation Specification

### 8.1 intent.sh Changes Required

**Warm-start context injection.** Before constructing the initial prompt, `intent.sh` queries institutional memory for observations relevant to the current task. The query uses `memory_indexer.py`, which accepts the following CLI arguments:

```bash
WARM_START_FILE=$(mktemp)
python3 "$SCRIPT_DIR/scripts/memory_indexer.py" \
  --db "$PROJECT_DIR/.memory.db" \
  --source "$PROJECT_DIR/OBSERVATIONS.md" \
  --source "$PROJECT_DIR/ESCALATION.md" \
  --task "$TASK_DESCRIPTION" \
  --output "$WARM_START_FILE" \
  --top-k 10 2>/dev/null
WARM_START_CONTEXT=$(cat "$WARM_START_FILE" 2>/dev/null)
rm -f "$WARM_START_FILE"
```

If `WARM_START_CONTEXT` is empty (because the memory files are new, empty, or retrieval found nothing), `intent.sh` proceeds without warm-start context — cold-start behavior is the automatic fallback. On first use, `OBSERVATIONS.md` and `ESCALATION.md` are empty, so this path always runs cold. Warm-start activates automatically as sessions accumulate observations.

When `WARM_START_CONTEXT` is non-empty, it is formatted as a section in the initial prompt:

```
--- Prior context (from institutional memory) ---
[retrieved observations and escalation calibration data]
--- end prior context ---
```

This section is injected after the task description and before any other context files.

**15-minute timeout enforcement.** intent.sh must track elapsed time from the first turn. At 12 minutes, it sends a message to the intent-lead: "Two minutes remaining — please finalize INTENT.md with what you have." At 15 minutes, it interrupts the conversation and calls: `run_turn "Please write INTENT.md now with your current understanding." --resume "$SESSION_ID"`.

**Post-approval learning extraction.** After the human approves INTENT.md (case `y|Y` or `e|E` in the approval loop), intent.sh calls:

```bash
python3 "$SCRIPT_DIR/scripts/summarize_session.py" \
  --stream "$INTENT_STREAM" \
  --scope intent \
  --session-dir "$STREAM_DIR" &
```

This runs asynchronously so it does not delay the handoff to planning.

**Round tracking for warm-start reduction.** When warm-start context is present and confidence is high (mean confidence of pre-populated observations > 0.75), the max rounds should be reduced from 10 to 6. This encodes the expectation that warm starts need fewer rounds to reach a complete INTENT.md.

### 8.2 agents/intent-team.json Changes Required

Replace the current intent-lead prompt with the full prompt specified in Section 6.1. The research-liaison prompt should be updated to make the proactive dispatch requirement explicit. No changes to model selection or max turns are required.

Warm-start behavior is controlled entirely by `intent.sh`: if the memory query returns observations, they are injected into the initial prompt with "(from prior sessions)" markers; if it returns nothing, the cold-start path runs. No agent-level flag is needed. The intent-lead agent handles both cases based on whether the prior context block appears in its initial prompt.

### 8.3 INTENT.md Annotated Template

The following is an annotated template showing what each section looks like when complete. This template is a reference for quality evaluation, not a form to fill in. INTENT.md should follow the shape of the problem.

```markdown
# Intent: [Project Name]

## Objective

[One to three sentences. State what outcome the human wants AND why it matters to the organization.
The "why" is as important as the "what." If removing this section would leave a reader who could
still build the right thing, the objective has not been stated — only the deliverable has.]

## Success Criteria

[Both quantitative thresholds and qualitative values. Quantitative: what passes or fails with a
number. Qualitative: what the output should feel like, what values it should reflect, what
aesthetic or ethical standards it must meet. Neither is optional. The qualitative section is
often longer and more valuable than the quantitative section for creative and knowledge work.]

## Decision Boundaries

[Narrative of risk posture for this project. Organized by domain or decision type where
appropriate. Should include:
- Where the agent uses autonomous judgment (with what constraints)
- Where the agent must stop and check (with specific triggering scenarios)
- Stop rules: what the agent must never do regardless of circumstance

This section is a narrative, not a table or bullet list. It should read as if an experienced
person is describing their judgment to a capable colleague.]

## Constraints

[Technical, organizational, temporal, and resource constraints. Each constraint must be stated
precisely enough that its satisfaction is unambiguous. Soft constraints (preferences) should be
in Success Criteria, not here. This section contains hard limits only.]

## Open Questions

[Each open question must state: the question, why it cannot be resolved now, and what the
planning phase must do with it. No question should appear here without a clear mandate for
the planning team. "To be determined" is not a planning handoff — it is a planning failure.]
```

### 8.4 Memory Schema — JSON Structures

User observation record (complete schema for implementation):

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["id", "user_id", "scope", "key", "value", "confidence", "source"],
  "properties": {
    "id": { "type": "string", "format": "uuid" },
    "user_id": { "type": "string" },
    "scope": { "type": "string", "enum": ["individual", "team", "organization"] },
    "domain": { "type": "string" },
    "key": { "type": "string", "description": "What was observed (preference category)" },
    "value": { "type": "string", "description": "The observation content" },
    "confidence": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
    "source": { "type": "string", "enum": ["stated", "revealed", "inferred"] },
    "signal_count": { "type": "integer", "minimum": 1 },
    "first_observed": { "type": "string", "format": "date-time" },
    "last_updated": { "type": "string", "format": "date-time" },
    "sessions": { "type": "array", "items": { "type": "string" } }
  }
}
```

Escalation calibration record:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["user_id", "domain", "threshold", "confidence"],
  "properties": {
    "user_id": { "type": "string" },
    "domain": { "type": "string" },
    "threshold": { "type": "number", "minimum": 0.0, "maximum": 1.0,
                   "description": "0.0=always escalate, 1.0=always autonomous" },
    "confidence": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
    "signal_count": { "type": "integer" },
    "last_calibrated": { "type": "string", "format": "date-time" },
    "signals": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "type": { "type": "string", "enum": ["positive", "negative", "neutral"] },
          "delta": { "type": "number", "description": "Threshold change applied" },
          "description": { "type": "string" },
          "session_id": { "type": "string" },
          "timestamp": { "type": "string", "format": "date-time" }
        }
      }
    }
  }
}
```

Session learning record:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["session_id", "intent_file", "extracted_at"],
  "properties": {
    "session_id": { "type": "string" },
    "project_category": { "type": "string" },
    "intent_file": { "type": "string" },
    "new_observations": { "type": "array", "items": { "type": "string", "format": "uuid" } },
    "updated_observations": { "type": "array", "items": { "type": "string", "format": "uuid" } },
    "corrections_to_priors": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "observation_id": { "type": "string", "format": "uuid" },
          "prior_value": { "type": "string" },
          "corrected_value": { "type": "string" },
          "correction_type": { "type": "string", "enum": ["explicit", "behavioral"] }
        }
      }
    },
    "escalation_signals": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "domain": { "type": "string" },
          "signal_type": { "type": "string", "enum": ["positive", "negative", "neutral"] },
          "description": { "type": "string" }
        }
      }
    },
    "extracted_at": { "type": "string", "format": "date-time" }
  }
}
```

---

## 9. Open Questions

These items cannot be resolved until the POC runs enough sessions to generate calibration data. Each entry states the question, why it cannot be resolved now, and what must happen before it can be resolved.

**Escalation threshold delta calibration.** The risk tolerance model uses deltas of 0.05 (positive signal), 0.10 (negative signal), and 0.02 (neutral signal) for threshold adjustment. These values are asserted without empirical basis — no calibration data exists yet because the system has not run. They cannot be validated until the POC completes 10 or more sessions and threshold trajectories can be evaluated against actual escalation outcomes. The planning phase must instrument the threshold record to capture the history of adjustments so that drift can be analyzed after data accumulates. The deltas are reasonable starting values; treat them as defaults to be tuned, not specifications to be preserved.

**Scope assignment for team and organizational observations.** `summarize_session.py` assigns individual scope to observations by default and broader scope to statements containing markers like "we always" or "the team requires." This heuristic is untested. It cannot be validated until the system processes sessions involving explicit team or organizational statements. The planning phase must design a review mechanism — a human-readable report of scope assignments from each session — so that misclassifications are visible and correctable before they propagate through the scope hierarchy.

**Memory-to-plan handoff for open questions.** INTENT.md open questions are a mandatory handoff to the planning team (Section 7.1). The planning team must research options and present them to the human before execution begins. The current pipeline has no mechanism to verify that open questions were resolved before execution starts — `plan-execute.sh` does not check INTENT.md for unresolved open questions before launching the execution phase. This gap cannot be resolved without running the pipeline end-to-end and observing whether unresolved questions cause execution failures. The planning phase must add an INTENT.md pre-flight check to `plan-execute.sh` that warns (does not block) if open questions are present at execution start.

---

END OF DOCUMENT
