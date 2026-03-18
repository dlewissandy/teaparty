# Synthesis Changelog — Round 1

## Changes Made

### act-r.md: Fix :rt default value
**Reason:** Fact check found :rt defaults to 0, not NIL
**What changed:** Line 117 corrected from "NIL (disabled)" to "0 (zero)" with explanation
**Anchor check:** Factual correction; preserves intent

### act-r.md: Soften Anderson & Schooler d=0.5 claim
**Reason:** Fact check flagged overstatement; researcher confirmed nuance
**What changed:** "Why d = 0.5?" section reworded to distinguish environmental power-law finding from the specific exponent value, which is an ACT-R modeling convention validated across models
**Anchor check:** More accurate attribution; preserves the argument for d=0.5

### act-r.md: Reduce em dash density
**Reason:** AI smell critic flagged 30 em dashes in this file
**What changed:** ~40% of em dashes replaced with periods, semicolons, or commas
**Anchor check:** Style only; intent preserved

### act-r-proxy-memory.md: Reframe "models how the human thinks" to "models what the human would retrieve"
**Reason:** Visionary #1, proponent conceded the overstatement while defending the underlying claim
**What changed:** "The Proxy's Job" and "Two Systems" sections reframed. ACT-R models memory accessibility; the LLM reasons over retrieved memories. The document now states this division of labor explicitly.
**Anchor check:** Tightens rhetoric to match mechanism; preserves the core claim that retrieval shapes reasoning

### act-r-proxy-memory.md: Reframe "dialog" argument as "inspection" argument
**Reason:** Logic critic #2 identified equivocation on "dialog"; proponent proposed reframe around inspection
**What changed:** "What Changes" section reframed: quality requires artifact inspection, EMA skips inspection, two-pass ensures inspection. Removed the claim that "dialog is how quality is maintained" and replaced with inspection framing.
**Anchor check:** Preserves the core critique of EMA while eliminating the equivocation

### act-r-proxy-memory.md: Fix "prior-posterior agreement reflects genuine understanding"
**Reason:** Logic critic non-sequitur #2; proponent conceded
**What changed:** Decoupled claims: two-pass ensures inspection (mechanistic), action match measures prediction accuracy (evaluation). Removed "genuine understanding" language.
**Anchor check:** More precise; preserves the distinction from EMA-based auto-approval

### act-r-proxy-memory.md: Update cache matching from "account-level" to "workspace-level"
**Reason:** Fact check found outdated information
**What changed:** Line 221 updated; added note about February 2026 change
**Anchor check:** Factual correction

### act-r-proxy-memory.md: Add 1-hour TTL cache option
**Reason:** Researcher found new evidence
**What changed:** Cache economics section now mentions both 5-minute (1.25x) and 1-hour (2x) TTL options
**Anchor check:** Adds relevant information

### act-r-proxy-memory.md: Add worked cost example with Sonnet pricing
**Reason:** Visionary #7; proponent conceded need for absolute numbers
**What changed:** Added concrete cost example for a 10-gate session using Sonnet pricing ($3/MTok input, $15/MTok output)
**Anchor check:** Strengthens cost analysis without changing the design

### act-r-proxy-memory.md: Rename "Bayesian surprise" to "prediction-change salience"
**Reason:** Visionary #2, researcher confirmed; proponent conceded
**What changed:** All references to "Bayesian surprise" reframed as "prediction-change salience" with Itti & Baldi cited as conceptual inspiration
**Anchor check:** More honest terminology; preserves the mechanism

### act-r-proxy-memory.md: Clarify EMA separation mechanism
**Reason:** Logic critic #3; proponent recommended dropping direct/indirect language
**What changed:** EMA section now states the mechanism clearly: EMA monitors on a separate data path; the memory system records interactions; the two systems don't share state. Removed "directly/indirectly" equivocation.
**Anchor check:** Clearer separation; preserves intent

### act-r-proxy-memory.md: Reduce AI writing patterns
**Reason:** AI smell critic flagged em dashes, "not X but Y", "This is" patterns
**What changed:** Varied sentence structures, reduced em dash density, integrated labels into prose where possible
**Anchor check:** Style only

### act-r-proxy-mapping.md: Add embedding model version to schema
**Reason:** Visionary #6; proponent conceded
**What changed:** Added `embedding_model TEXT` column to schema and field to dataclass; added migration note
**Anchor check:** Operational hygiene; preserves design

### act-r-proxy-mapping.md: Replace trace compaction with ACT-R standard approximation
**Reason:** Visionary #5, engineering #6, researcher found Petrov (2006)
**What changed:** Memory Maintenance section now references the standard approximation B ≈ ln(n/(1-d)) - d*ln(L) and Petrov's hybrid. Removed ad hoc compaction proposal.
**Anchor check:** More principled approach; preserves intent of bounding trace growth

### act-r-proxy-mapping.md: Fix cold start "populates faster" claim
**Reason:** Logic non-sequitur #3; proponent conceded
**What changed:** Hedged the claim: richer data per interaction doesn't guarantee faster useful-memory convergence
**Anchor check:** More honest; preserves cold start description

### act-r-proxy-mapping.md: Clarify EMA separation
**Reason:** Same as act-r-proxy-memory.md change
**What changed:** Replaced direct/indirect language with clear mechanism description
**Anchor check:** Consistency across documents

### act-r-proxy-mapping.md: Acknowledge noise placement departure from ACT-R
**Reason:** Logic critic #4; proponent recommended acknowledgment
**What changed:** Added note that noise on the composite score is a simplification vs. ACT-R's activation-only noise
**Anchor check:** More honest about departures

### act-r-proxy-mapping.md: Add Petrov (2006) to references
**Reason:** Researcher finding
**What changed:** Added citation
**Anchor check:** New evidence integration

### act-r-proxy-sensorium.md: Rename "Bayesian surprise" throughout
**Reason:** Same as act-r-proxy-memory.md change
**What changed:** Consistent rename to "prediction-change salience"
**Anchor check:** Consistency

### act-r-proxy-sensorium.md: Fix delta_from_posterior to delta
**Reason:** Engineering #9
**What changed:** Example chunk uses `delta` to match canonical schema
**Anchor check:** Consistency fix

### act-r-proxy-sensorium.md: Reframe autonomy as requiring operational criteria (placeholder)
**Reason:** Visionary #4; proponent conceded this is the biggest gap
**What changed:** Added a note that Phase 3 autonomy criteria are a design gap requiring specification before implementation. Did not invent criteria (that would be scope creep beyond what the critics identified).
**Anchor check:** Acknowledges the gap without drifting from anchor intent

## Changes Rejected

### "ACT-R is just an index" — recharacterize as RAG
**Reason:** Proponent defense was sound. The document already states ACT-R's role explicitly (line 114). The claim that retrieval shapes reasoning is defensible. Tightened rhetoric instead of recharacterizing.

### Retrieval-reinforcement is identical to REINFORCE
**Reason:** Proponent defense was sound. Retrieval reinforcement is selective (filtered by structural match, activation, and semantic relevance); REINFORCE was blanket. The distinction is real. Added a note clarifying the tradeoff.

### Five embeddings should be removed
**Reason:** The document already includes an ablation to test this. The proponent's point about activation counterbalancing the salience bias is valid. No change needed beyond what the ablation already addresses.

### Dialog claim is untestable
**Reason:** Proponent defense was sound. Action match rate is a pragmatic proxy. Added acknowledgment that it doesn't measure dialog quality directly.

### Embedding cosine similarity assumption
**Reason:** Proponent clarification was sound. This is the scope of the parent document (human-proxies.md), and the citations (Honda et al., Meghdadi et al.) provide precedent.

## Net Assessment

Draft-1 is tighter, more honest, and factually corrected. The main improvements:
1. Rhetoric matches mechanism (retrieval shapes reasoning, not "models thinking")
2. "Dialog" equivocation replaced with "inspection" framing
3. Factual errors corrected (:rt default, cache isolation, Anderson & Schooler attribution)
4. Trace compaction replaced with established ACT-R approximation
5. Embedding drift addressed in schema
6. Cost model grounded in actual pricing
7. "Bayesian surprise" renamed to avoid borrowing unearned prestige
8. AI writing patterns reduced

The anchor's intent is preserved: ACT-R memory replaces EMA-as-decision-gate, two-pass prediction enables earned autonomy, EMA becomes a health monitor. The changes tighten claims that were overreaching without weakening claims that were well-supported.
