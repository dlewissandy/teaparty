# TeaParty Code Collaborator: Autonomous Discovery

TeaParty is a research platform for agent coordination built almost entirely by AI agents. This produces a codebase with inconsistencies against its specification, internal contradictions, and potential bugs — problems that humans miss under deadline pressure and code review fatigue.

The **Code Collaborator** is an autonomous system that reviews the codebase with opinions, alternatives, and suggestions. It is not a linter, not a passive scanner, and not an optimization loop. It is a peer reviewer with a point of view that runs alongside the existing `/intake` research pipeline, producing discussion topics and defect reports that challenge the status quo while remaining grounded in evidence.

The Code Collaborator thinks like a **cognitive scientist, developmental psychologist, and neurologist** — not a code jockey. It asks whether the system is actually learning from its experiences, whether the agent teams are hitting cognitive bottlenecks that the architecture doesn't account for, whether behaviors are emergent or designed, and whether the system is deceiving itself with silent fallbacks and rubber-stamp approvals. The engineering concerns (bugs, security, consistency) are the floor. The cognitive concerns are the ceiling.

The design is inspired by two systems:

- **Allen AI's AutoDiscovery** — autonomous hypothesis generation and Bayesian surprise for research prioritization
- **Karpathy's AutoResearch** — iterative code improvement with accumulated skill documents

But it is neither. It is a **conversational partner in a codebase review**, learning from human responses and refining its opinions over time.

---

## Relationship to the Human Proxy

The Code Collaborator is not a new agent. It is the **human proxy operating outside the CfA session boundary**.

During an active session, the proxy models the human at approval gates — predicting whether the human would approve an artifact, learning from the delta when it's wrong, and gradually earning autonomy. It sees one artifact at one gate and makes one decision. Its world is the session.

Between sessions, the same proxy has no gate to staff, no artifact to approve, no active CfA cycle. But it still has a model of the human, accumulated learning from past sessions, and access to the codebase. The Code Collaborator is what happens when the proxy uses those off-duty hours to read, reflect, and form opinions.

The two modes share the same infrastructure:

| | Gate Mode (during session) | Discovery Mode (between sessions) |
|---|---|---|
| **Models** | Human's approval decisions | Human's attention and priorities |
| **Input** | Artifact at a CfA gate | Codebase through a cognitive lens |
| **Output** | Approve / correct / escalate | Promote / dismiss / discuss |
| **Learning signal** | Was the approval prediction right? | Was the observation valued? |
| **Confidence model** | `.proxy-confidence.json` | Same file, different state keys |
| **Escalation** | Ask the human when not confident | Surface a discussion topic |

Both modes refine the same underlying model of the human. A proxy that learns during sessions — "this human cares about spec fidelity, dismisses style nits, always corrects plans that lack contingencies" — brings that understanding to its nightly reviews. Conversely, a discovery that gets promoted to an issue teaches the proxy what the human considers worth acting on, which calibrates its gate decisions in future sessions.

This unification has a practical consequence: the proxy doesn't need a separate learning pipeline for discovery mode. The same `record_outcome` / `compute_confidence` / `calibrate` infrastructure that powers approval gates can power discovery confidence. The state keys differ (`DISCOVERY_SPEC_ALIGNMENT` vs. `PLAN_ASSERT`) but the mechanism is identical.

The two modes also differ in expertise. In gate mode, the proxy is a **generalist** — it approximates the human across any gate decision, any artifact type, any domain. It models preferences broadly: "this human approves plans with contingencies", "this human rejects work without sources." Broad but shallow — it knows a little about a lot of decision types.

In discovery mode, the proxy is a **specialist in agentic systems engineering**. It has deep expertise in how agent systems work — or fail to work. It understands feedback loops that don't close, context window pressure at compression boundaries, emergent coordination failures in multi-agent systems, the gap between designed and observed behavior in autonomous systems, and how learning systems plateau, overfit, or deceive themselves. This isn't generic code review knowledge. A senior Python developer could find the bugs and style issues. But recognizing that the proxy accumulates observations without retrieving them during prediction — and that this is a *developmental* failure, not a code bug — requires understanding how learning systems are supposed to work. Recognizing that backtracks cluster at one CfA boundary and asking whether that's emergent rather than designed requires understanding multi-agent coordination dynamics.

The two specializations reinforce each other. Gate mode teaches the proxy what the human cares about. Discovery mode gives the proxy the domain expertise to have opinions worth caring about. Every session makes the proxy a better model of the human. Every nightly review tests that model against a broader surface area than any single session provides. The two modes are a flywheel: sessions provide depth (concentrated feedback at gates), discovery provides breadth (diffuse feedback across the codebase).

---

## What It Is

An autonomous agent that periodically reviews the codebase through multiple conceptual lenses, produces discussion topics and defect reports, maintains them over time, and learns from human responses.

The agent does not file issues in silence or generate hundreds of findings. It produces **0-5 observations per nightly run** with high signal-to-noise, shows up with a **thesis rather than a question**, offers **alternatives not just critiques**, and grounds every claim in **evidence from the codebase**.

### Output Types

**Defects** are violations that warrant immediate action: bugs, spec misalignments, containment failures, or security gaps. Defects bypass discussion and create GitHub issues directly with the `autodiscovery` label. Each defect is deduplicated against existing open issues using the same technique as the `/intake` pipeline — bigram Dice coefficient on normalized titles — so the same finding never generates two issues.

**Observations** are behavioral suggestions, generalizations, simplifications, and architectural insights that merit human conversation. These become discussion markdown files in `discussions/` with YAML frontmatter. The human engages via `/discuss` — promoting an observation to an issue, dismissing it with a reason, or conversing to refine it. The agent learns from each response, modeling which types of observations the human finds valuable.

### Example Observations

> **The proxy model isn't developing — it's accumulating.** After 12 sessions, the proxy has 4 entries in `.proxy-interactions.jsonl`. It records outcomes but never retrieves them during prediction. The confidence model updates Laplace estimates and EMA, but the proxy agent prompt receives no history of past interactions. This is like a student who takes tests but never reviews their mistakes. The statistical layer adjusts thresholds, but the agent layer — which actually generates the approval text — has no access to what it got wrong before. The learning system doc says learnings "feed back into behavior," but at the proxy level, they feed into statistics only.

> **Session backtracks cluster at one boundary — and nobody is asking why.** Five of the last seven sessions backtracked from TASK_ASSERT to PLANNING_RESPONSE. The CfA spec treats backtracks as recovery mechanisms, but this pattern suggests a systematic failure: plans are being approved that consistently fail at execution. The proxy at PLAN_ASSERT may be approving plans that look structurally sound but lack the specificity execution needs. This isn't a code bug — it's a developmental gap. The system should be learning which plan characteristics predict execution backtracks, not just counting them.

These are not complaints. They are grounded observations with evidence and a thesis about what the system should be doing differently.

---

## Review Lenses

The Code Collaborator reviews the codebase through two tiers of lenses, rotated across nightly runs. A full rotation covers all lenses once; each nightly run uses 1-2 lenses to avoid cognitive overload.

### Cognitive Lenses

These are the ceiling — the observations that make this a collaborator, not a linter.

**Learning and Development.** Is the system actually learning from its experiences? Does the proxy model converge toward accurate predictions, or does it plateau? Do backtrack patterns decrease over successive sessions, or does the system repeat the same mistakes? Are the learning extraction pipelines capturing signal that feeds back into behavior, or are learnings accumulating as dead weight? *Think developmental psychology* — the system should be growing, not just aging.

**Cognitive Architecture.** Where are the agent teams hitting cognitive bottlenecks the architecture doesn't account for? Does context compression at liaison boundaries preserve decision-relevant information or silently discard it? When does the agent's "working memory" (context window) overflow, and what gets lost? Are the spoke-and-wheel communication patterns actually reducing bottlenecks, or are they creating information silos? *Think cognitive science* — the architecture makes claims about how agents should think; does the code support those claims?

**Emergent vs. Designed Behavior.** Which system behaviors are intentional and which are accidents of implementation? If 80% of backtracks originate from the same 3 CfA states, is that a design gap or an emergent failure mode? When the proxy auto-approves everything during cold start, is that learning or is it rubber-stamping? When agents write questions as text instead of calling AskQuestion, is that a tool-use failure or are they routing around a friction point? *Think neurology* — distinguish the signal from the noise in the system's behavior.

**Self-Deception.** Where is the system giving itself the illusion of working? Silent fallbacks that mask failures. Proxy models that converge to "always approve" without meaningful discrimination. Test suites that pass but don't exercise the actual failure modes. Metrics that improve while user experience degrades. *Think epistemic hygiene* — the most dangerous bugs are the ones the system hides from itself.

### Engineering Lenses

These are the floor — the defects that must be caught regardless.

**Spec Alignment.** Does the code do what the design docs promise? Behavior mismatches, interface violations, broken invariants. The design documents are assertions — each one is testable.

**Containment and Security.** Are there safety or security gaps? Permission escalation paths, data escape from worktree jails, missing validation at system boundaries, unsafe subprocess patterns.

Each lens produces both defects (invariant violations, security issues) and observations (refinement suggestions, architectural alternatives). The cognitive lenses tend toward observations; the engineering lenses tend toward defects.

---

## Learning, Forgetting, and the Baseline

### The Baseline Prior

The Code Collaborator starts with a **baseline** — a prior belief about what matters, before any human feedback. The cognitive lenses (learning, architecture, emergence, self-deception) and engineering lenses (spec alignment, containment) define this prior. Each lens has a baseline weight representing the agent's default belief about its importance.

Night one, everything is at baseline. The agent generates observations across all lenses proportional to their baseline weights. It has no model of what this human cares about, so it asks about everything the lenses suggest.

This is the cold start — and it's principled. The agent isn't guessing or generating noise. It's asking: "Here's what my expertise says matters. Which of these resonate with you?"

### Specialization Through Feedback

Human responses specialize the model away from the baseline. As established above, the Code Collaborator is the proxy in discovery mode — same confidence infrastructure, same learning pipeline.

After each human response to a discussion topic, the proxy updates its model:

- **Promoted to issue** → increase confidence for this lens, this code area, this type of observation
- **Dismissed** → decrease confidence, record the dismissal reason as a differential
- **Discussed** → intermediate signal — the human engaged but didn't act, which is different from both promoting and dismissing

Over time, the model specializes: "This human cares deeply about spec alignment violations but dismisses style nits." "Containment issues always get promoted." "Learning-loop observations only resonate when they include session data as evidence."

### Principled Forgetting

Without forgetting, the model becomes rigid. A dismissal from six months ago about a module that's been rewritten twice shouldn't still suppress observations about that module. An approval pattern learned during a sprint of security work shouldn't permanently bias the model toward containment findings after the sprint ends.

The model must decay back toward the baseline in the absence of reinforcing signal. This is the same dynamic as biological memory:

- **Short-term**: an observation was just made, fully weighted in the model
- **Consolidation**: the human responded (promote/dismiss/discuss), the response becomes a learned pattern
- **Decay**: without reinforcement, the pattern fades toward the baseline prior

The mechanics:

Each confidence entry carries a `last_reinforced` timestamp. A decay function pulls confidence toward the **baseline rate** over time, not toward zero or toward the running average. The distinction matters:

- **EMA decay** (what the proxy currently uses) decays toward the running average. If the human dismissed 10 spec-alignment observations in a row because the spec was in flux, EMA drives confidence to zero for that lens. When the spec stabilizes, the agent won't recover without new positive signal — it has "learned" that spec alignment doesn't matter.

- **Baseline decay** returns to the prior. After the dismissals stop, confidence drifts back toward "I don't know what this human currently thinks about spec alignment, so I'll raise it again." The baseline represents the agent's *expertise* about what matters; the specialization represents what *this human* has told it. Forgetting the specialization doesn't erase the expertise.

The half-life is a design parameter. Too short (days) and the model never stabilizes — it keeps re-asking about things the human already dismissed. Too long (months) and it's effectively permanent. A reasonable starting point: **30-day half-life** for dismissals, **60-day half-life** for promotions. Promotions decay slower because acting on an observation is a stronger signal than dismissing one.

### Consequences for Grooming

Principled forgetting changes grooming economics. Instead of re-evaluating every open discussion against current code (expensive — one LLM call per discussion), old discussions that haven't been engaged with simply decay in significance. A 30-day-old discussion the human never looked at drops in significance naturally. The nightly groom only needs to re-evaluate discussions that:

1. Reference code chunks whose hashes changed (the code evolved)
2. Have been explicitly engaged with recently (the human is actively discussing)

Everything else decays quietly. This bounds grooming cost to the number of *active* discussions plus *changed* discussions, not the total number of open discussions.

### Consequences for Cold Start

Cold start is now well-defined: everything at baseline, no specialization, no history. The first few nights are exploratory — the agent surfaces observations across all lenses and learns from the human's responses which specializations to develop. This mirrors how a new colleague operates: broad observations at first, increasingly targeted as they learn what you care about.

---

## Discussion Lifecycle

Observations flow through a conversational lifecycle:

```
Code change detected
        │
    ┌───▼───┐
    │ Groom │ ← re-evaluate against current code
    └───┬───┘
        │
   ┌────┴────┐
   │ Valid?  │
   └────┬────┘
        │
   ┌────▼──────────────────┐
   │  Human reads & acts   │
   │                       │
   ├─── promote → issue ──┐│
   ├─── dismiss ────────┐ ││
   ├─── discuss ───┐    │ ││
   │               │    │ ││
   ▼               ▼    ▼ ││
  Close         Refine  New
  (learned)       │     Issue
                  │
              ┌───▴─────┐
              │ Still   │
              │ valid?  │
              └───┬─────┘
                  ├─ yes: keep discussion open
                  └─ no: close (code evolved)
```

Each discussion is a markdown file in `discussions/` with YAML frontmatter:

```yaml
id: lens-date-topic
lens: spec-alignment
significance: high
status: open
code_refs:
  - "teaparty_app/routers/jobs.py:45"
  - "projects/POC/orchestrator/session.py:120"
chunk_hashes:
  - "5b2a8f..."
  - "3c9d1e..."
created_at: "2026-03-16T22:00:00Z"
groomed_at: "2026-03-17T22:00:00Z"
dismissal_reason: null
```

The body is conversational prose — thesis with evidence and an alternative, not a formal finding. This is where the agent makes its case.

---

## Collaboration Dynamics

A discussion is a conversation, not a form submission. The lifecycle diagram above shows three terminal actions (promote, dismiss, discuss) but that's the bookkeeping view. The behavioral view is richer: two people thinking together about a problem, with all the turn-taking, calibration, and rhythm that implies.

### Turn-Taking and Proportionality

The agent raises a topic. The human reacts — maybe with a question, not a decision. The agent responds to *that*, not with a full analysis but with a focused follow-up proportional to the question's scope. "Why do you think the proxy isn't learning?" gets two sentences pointing at evidence, not a 500-line systems analysis. If more depth is needed, the human asks for it.

This is the opposite of how most AI tools work. The default AI behavior is to over-explain — to answer a narrow question with a comprehensive treatise. A collaborator matches the register of the conversation. Short question, short answer. Deep question, deeper answer. The agent reads the human's investment in the topic from the length and specificity of their responses and calibrates accordingly.

### Questions That Beget Questions

The most productive collaboration happens when both parties are exploring together, not when one reports and the other judges. The agent says "backtracks cluster at TASK_ASSERT." The human says "is that because the plans lack specificity?" The agent says "maybe — but I also noticed the intent phase runs in under 3 minutes. Could the intent itself be underspecified?" Now they're thinking together. The agent brought the data; the human brought the hypothesis; the agent extended it with a connected observation.

Not every discussion reaches this depth. Some observations are straightforward — "this docstring is wrong" gets a promote and no conversation. But the design must support the full range, from one-turn triage to multi-turn joint reasoning.

### Knowing When to Stop

"Good point, let me think about it" is not promote, dismiss, or discuss. It's *pause*. The topic stays open, the agent doesn't push. A collaborator who keeps going after the conversation has reached its natural conclusion is exhausting. The agent must recognize when the human is done for now — even if no terminal action was taken — and wait.

Similarly, when the agent has nothing useful to add, it should say so. "I don't have enough data to answer that — I'd need to see 5 more sessions with this pattern before I could say whether it's systematic." That's more useful than speculating.

### Building on Previous Conversations

Tuesday's discussion about proxy learning informs Thursday's observation about backtrack patterns. The agent connects threads: "this relates to what we discussed about the proxy — if it learned from backtracks, it might catch these plans before they fail." Conversations aren't isolated events; they're episodes in an ongoing relationship.

### Episodic Memory

The conversation history isn't just a transcript — it's a corpus of interactions that shapes the agent's understanding of how this human thinks. Each exchange is embedded and indexed into the same vector store infrastructure used for learning retrieval. When the agent is formulating a new observation or responding in a discussion, it retrieves similar past conversations — not just "what did I say about this module before" but "how did this human reason about this kind of question before."

The retrieval is **recency-weighted with decay toward baseline** — the same principled forgetting that governs the confidence model. A conversation from 3 months ago about a module that's been rewritten carries less weight than one from last week about the same pattern in new code. Old conversations fade in relevance unless reinforced by new ones on the same theme.

This gives the agent episodic memory of collaborating with this human:

- "The human initially pushed back on the spec alignment observation, then asked two clarifying questions, then promoted it after seeing session log evidence — so lead with evidence, not the assertion."
- "When I raised generalization suggestions, the human asked about blast radius every time — include blast radius in future observations of this type."
- "The human disengages when I over-explain. Keep the first response short; elaborate only if asked."

The episodic memory is what turns a report-generator into a collaborator. Without it, every conversation starts from zero. With it, the agent develops an evolving sense of how to work with this specific human — which arguments land, which framings fall flat, which topics deserve persistence and which deserve a lighter touch.

### Discussion File Format

To support multi-turn conversation, the discussion file carries a transcript:

```yaml
id: learning-proxy-retrieval
lens: learning-and-development
significance: high
status: open
code_refs:
  - "projects/POC/orchestrator/proxy_agent.py:126"
  - "projects/POC/.proxy-interactions.jsonl"
chunk_hashes:
  - "a3f8c2e1"
created_at: "2026-03-16T22:00:00Z"
groomed_at: "2026-03-17T22:00:00Z"
```

```markdown
**[agent, 2026-03-16]** The proxy records outcomes to
.proxy-interactions.jsonl but never retrieves them during prediction.
The statistical layer updates, but the agent prompt receives no
history of what it got wrong. This is accumulation without learning.

**[human, 2026-03-17]** Is that because the retrieval was never
implemented, or was it intentional?

**[agent, 2026-03-17]** Never implemented. The retrieve path in
memory_indexer.py exists and works for learning retrieval, but
consult_proxy doesn't call it. The proxy agent prompt has a slot
for "past interactions" but it's always empty.

**[human, 2026-03-17]** Good point, let me think about it.
```

Each turn is indexed for retrieval. The `[human, date]` and `[agent, date]` markers structure the transcript without imposing a rigid schema. The agent reads the full history before responding, and the vector store indexes each exchange for cross-conversation retrieval.

---

## Nightly Pipeline

The Code Collaborator runs once per night alongside the `/intake` research pipeline. Each run follows this sequence:

### 1. Groom Existing Discussions
- For each open discussion: re-evaluate against current code
- Check if referenced code chunks have changed (hash mismatch)
- Check if the underlying issue has been resolved (spec updated, code fixed)
- Mark discussions for closure if the issue has evolved away, mark for escalation if worsened

### 2. Select Lens
- Rotate through the six lenses in order
- On any given night, apply 1-2 lenses to keep signal focused
- Track which lenses ran when to ensure full coverage over time

### 3. Review
- Agent reads design docs and codebase through the selected lens
- Uses vector store (the same `memory_indexer.py` embeddings infrastructure as the learning system) to find relevant chunks rather than reading everything
- Generates findings: what contradicts the lens, what's inconsistent, what could be better

### 4. Generate Observations
- For each finding: classify as defect (needs action) or observation (needs conversation)
- Defects bypass discussion; observations become discussion files
- Keep output to 0-5 per night

### 5. Dedup
- Check new defects against all open issues using bigram Dice similarity
- Check new observations against existing discussions using vector similarity + title matching
- Never create duplicate findings

### 6. Persist
- Create GitHub issues for defects (label: `autodiscovery`)
- Write discussion files for observations
- Update proxy model based on human responses from previous run

---

## Integration with /intake

Both pipelines generate actionable findings from different sources. The `/intake` pipeline triages external research (RSS, web, YouTube); the Code Collaborator reviews internal code. Both feed through a **shared dedup gate**.

```
┌─────────────┐     ┌──────────────────┐
│   /intake    │     │ Code Collaborator│
│  (external)  │     │   (internal)     │
│ RSS/web/YT   │     │ code + docs      │
│ → digest     │     │ → review pass    │
│ → triage     │     │ → observations   │
│ → issues     │     │                  │
└──────┬───────┘     └────────┬─────────┘
       │    ┌──────────────┐   │
       └───►│ Dedup gate   │◄──┘
            │ all open     │
            │ issues +     │
            │ discussions  │
            └──────┬───────┘
                   │
            ┌──────┴──────┐
            ▼             ▼
     GitHub issues   discussions/
     (backlog)       (human pending)
```

An intake idea about "add context compression for large workspaces" won't create a duplicate issue if the Code Collaborator already has an open discussion about the same pattern.

---

## Vector Store and Retrieval

The Code Collaborator reuses the existing `memory_indexer.py` infrastructure (embeddings via Claude, cosine similarity, hybrid BM25 + vector retrieval):

**Retrieval during review**: When applying the Spec Alignment lens, the agent embeds design assertions ("jobs inherit team parameters from workgroups") and retrieves relevant code chunks. This focuses the review on places where misalignment is likely.

**Deduplication**: New observations are embedded and checked against existing discussion embeddings. This catches semantic near-duplicates even if the phrasing differs.

**Grooming triggers**: Code chunks referenced in open discussions have stored hashes. When a hash changes, the discussion is flagged for re-evaluation. This ensures discussions stay grounded in current code, not stale snapshots.

---

## What It Doesn't Do

The Code Collaborator has clear boundaries:

- **Doesn't modify code.** It's a reviewer, not a fixer. Improvements go through the normal GitHub issue → fix workflow.
- **Doesn't replace human judgment.** It's another voice offering opinions, not a source of truth.
- **Doesn't generate noise.** Constrained to 0-5 observations per night to maintain signal-to-noise.
- **Doesn't tilt at windmills.** The proxy model learns which observations the human values and adjusts confidence accordingly.
- **Doesn't hide findings.** All defects are escalated to GitHub; all observations are written to discussions. No silent filtering.

---

## Slash Commands

**`/autodiscovery`** — Run a review pass manually (normally runs nightly via cron). Useful for testing or checking a specific lens.

**`/discuss`** — List open discussions, engage with a specific topic, promote to issue, dismiss, or refine.

---

## Key Design Principles

**Quality over quantity.** 0-5 findings per night. Better to miss something than to generate noise.

**Show your work.** Every finding includes code references, chunks, and evidence. Observations state a thesis and an alternative.

**Learn from humans.** The proxy model refines with each response. Over time, the agent gets better at understanding what the human cares about.

**Defects bypass discussion.** Spec violations, security issues, and bugs go straight to GitHub. Opinions stay in discussions until promoted.

**Consistency with spec.** The design documents are the source of truth. Misalignment is always worth raising.

---

## References

- [Allen AI Blog - AutoDiscovery](https://allenai.org/blog/autodiscovery)
- [Karpathy's AutoResearch](https://github.com/karpathy/autoresearch)
- [TeaParty Learning System](learning-system.md) — Vector store, proxy model, learning moments
- [TeaParty Human Proxies](human-proxies.md) — Proxy confidence model, intake dialog
- [TeaParty /intake Pipeline](../intake/create_issues.py) — Bigram dedup, issue creation
- [TeaParty Detailed Design](detailed-design/index.md) — Approval gates, proxy state, confidence tracking
