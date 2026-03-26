# Memory and Learning

TeaParty has two memory systems that serve different purposes and connect through persona distillation.

The **learning system** is organizational memory. It extracts structured learnings from completed sessions — what worked, what failed, what the human corrected — and stores them as markdown files with YAML frontmatter. Agents in future sessions retrieve relevant learnings to avoid repeating mistakes and build on prior work. The learning system operates across all agents and all sessions.

The **proxy memory system** models one specific human. It stores episodic memories of gate interactions — what the proxy predicted, what the artifact contained, what the human actually said — and uses ACT-R activation dynamics to surface the most relevant memories when the proxy needs to predict the human's response. The proxy memory operates within the approval gate, not across agents.

The two systems connect through **persona distillation**: stable preferences discovered through the proxy's episodic interactions are extracted post-session and written as Claude Code memory files, where they become always-loaded context for all future sessions. The human can see and correct these files, creating a transparent feedback loop.

---

## How proxy memory retrieval works

The proxy needs to answer: "given this gate context, what would the human say?" The answer depends on what the proxy remembers about similar past interactions with this human.

We use ACT-R's base-level activation to model memory accessibility — memories that were accessed recently and frequently are more available, matching the empirical power-law decay of human memory (Anderson & Schooler, 1991). We combine this with vector embedding similarity for context sensitivity, replacing ACT-R's symbolic spreading activation with a mechanism that works over unstructured text. The result is a two-stage retrieval that first filters by accessibility, then ranks by contextual relevance.

```
retrieve memories for gate(state, task_type, question):
    candidates ← all chunks matching state and task_type
    for each candidate:
        B ← base-level activation from trace history
        discard if B below retrieval threshold
    normalize B values across survivors to [0, 1]
    for each survivor:
        cosine_avg ← average cosine similarity across embedding dimensions
        score ← 0.5 × normalized_B  +  0.5 × cosine_avg  +  logistic noise
    return top-k by score, serialized to markdown for the proxy's prompt
```

Each memory chunk carries independent embedding dimensions for situation, artifact, stimulus, and response, so retrieval can match on "what happened at this gate type" separately from "what artifact features were involved." A fifth dimension — salience — captures prediction deltas (what surprised the proxy) and is retrieved through a separate attention query rather than blended into the composite score, so that routine interactions are not penalized for lacking surprise.

When the retrieved set contains conflicting memories (one says the human prefers parallelization, another says sequential verification), a retrieval-time conflict detection pass classifies the cause — preference drift, context sensitivity, genuine tension, or noise — and injects the classification into the proxy's prompt so the conflict is reasoned about explicitly rather than silently resolved.

For the ACT-R theory and equations, see [research/act-r.md](../research/act-r.md). For TeaParty's parameter choices and adaptations, see [act-r.md](act-r.md). For the chunk schema, trace rules, scoring details, contradiction detection, and salience separation, see [proxy-chunks-and-retrieval.md](proxy-chunks-and-retrieval.md).

---

## How proxy prediction works

Retrieval tells the proxy what to remember. Prediction tells it what to do with those memories. The proxy runs a two-pass prediction at every gate: first without the artifact (what does my model of this human expect?), then with the artifact (does the actual work change my prediction?). The delta between passes is the salience signal — it identifies what in the artifact the human would attend to.

```
predict at gate(state, task_type, artifact, question):
    memories ← retrieve memories(state, task_type, question)

    prior ← invoke proxy agent with memories, no artifact
    posterior ← invoke proxy agent with memories + artifact + prior reasoning

    if action changed or confidence shifted significantly:
        extract surprise description and salient percepts

    calibrate confidence against statistical history
    record interaction as new memory chunk with per-dimension embeddings
```

The two-pass design ensures the proxy always inspects the artifact, even when it would predict approval from context alone. Over time, the accumulated surprise deltas build a learned attention model: what this human notices, what they ignore, what triggers corrections. A proxy whose prior consistently matches its posterior has internalized the human's patterns deeply enough that artifact inspection is confirmatory, not discovery.

Per-context prediction accuracy tracking maintains running counts of prior-correct and posterior-correct predictions by (state, task_type) pair. This is the mechanism by which the proxy earns autonomy: not from a scalar threshold, but from demonstrated accuracy in a specific context. Contexts where both prior and posterior are consistently accurate are candidates for autonomous action; contexts where accuracy is poor require escalation.

For the motivation behind replacing the scalar EMA model, see [proxy-memory-motivation.md](proxy-memory-motivation.md). For the two-pass prediction design, surprise detection, learned attention, and accuracy-based autonomy, see [proxy-prediction-and-attention.md](proxy-prediction-and-attention.md).

---

## How learning retrieval works

The learning system retrieves organizational knowledge for agents at session start. Unlike proxy memory (which models one human's patterns), learning retrieval surfaces the team's accumulated experience: institutional norms, task-specific lessons, and procedural skills.

We use BM25 full-text search as the primary signal, optionally blended with vector embeddings, because learnings are stored as prose with YAML frontmatter — keyword matching is effective and the system degrades gracefully when embedding providers are unavailable. Prominence scoring weights results by importance, recency, and reinforcement count, ensuring that frequently validated learnings surface above one-off observations.

```
retrieve learnings for session(task_description, scope):
    load institutional learnings unconditionally at matching scope
    query ← extract key search terms from task_description
    results ← FTS5 BM25 search over indexed chunks
    if embeddings available:
        blend 0.7 × vector score  +  0.3 × BM25 score
    weight by prominence: importance × recency decay × (1 + reinforcement count)
    apply scope multipliers: team 1.5×, project 1.2×, global 1.0×
    rerank for diversity via maximal marginal relevance
    return within token budget
```

For the full learning system design — extraction pipeline, storage hierarchy, type-aware routing, and known gaps — see [learning-system.md](learning-system.md).

---

## How skills accumulate (System I / System II)

The planning phase operates as a dual-process system. System I (fast path) checks whether a stored skill matches the current task — if it does, the skill template becomes the plan and the planning agent never runs. System II (slow path) invokes the planning agent to reason from scratch. This is how collective procedural knowledge accumulates: agents solve problems through deliberate planning, successful solutions crystallize into reusable skills, and future similar tasks benefit from prior work without repeating the effort.

```
plan for task(task_description, project_dir):
    skill ← look up matching skill from skills/ directory
    if skill found:
        seed PLAN.md from skill template                         -- System I
    else:
        invoke planning agent to produce PLAN.md from scratch    -- System II

    human or proxy reviews plan at PLAN_ASSERT
    capture corrections, comments, or rejection reason

    during execution:
        record friction: timeouts, permission denials, tool failures, retries
        on backtrack execution → planning: skill signal (corner case in plan)
        on backtrack to intent: not skill signal (intent problem)

    post-session:
        archive approved plan as skill candidate
        if 3+ candidates for same work category:
            crystallize: generalize candidates into parameterized skill
        if skill was used and any signals recorded:
            refine: invoke Claude Code skill refinement with skill + signals
```

Skills learn from three feedback signals. Gate feedback includes corrections ("add a rollback step") but also approval comments that reveal where the skill fell short of expectations. Execution-to-planning backtracks are the strongest signal — they reveal corner cases the skill's structure failed to anticipate, and the corrected plan shows exactly what the fix looks like (planning-to-intent backtracks are not skill signal — they indicate intent problems). Execution friction captures operational problems in successful runs — timeouts, permission issues, missing references — that the skill's instructions should have anticipated. Refinement invokes Claude Code's built-in skill creation capability, which can improve instructions, add file references and examples, and insert metrics hooks to monitor future execution quality.

For the full procedural learning design — crystallization, gate reward signals, and skill self-correction — see [learning-system.md](learning-system.md) §Procedural Learning.

---

## Document inventory

| Document | Lines | Purpose |
|----------|-------|---------|
| [research/act-r.md](../research/act-r.md) | 156 | Vanilla ACT-R theory: equations, parameters, empirical basis |
| [act-r.md](act-r.md) | 79 | TeaParty's adaptations: interaction-based time, embeddings, parameter choices |
| [proxy-memory-motivation.md](proxy-memory-motivation.md) | 84 | Why ACT-R replaces EMA, two systems / two roles, what changes |
| [proxy-chunks-and-retrieval.md](proxy-chunks-and-retrieval.md) | 253 | Chunk schema, traces, retrieval, contradiction detection, salience separation |
| [proxy-prediction-and-attention.md](proxy-prediction-and-attention.md) | 235 | Two-pass prediction, surprise, learned attention, accuracy-based autonomy |
| [learning-system.md](learning-system.md) | 150 | Extraction, storage, retrieval, promotion, System I/II skill lifecycle |
