# Synthesis Changelog — Round 2 to Draft-2

This document lists all changes made from draft-1 to draft-2, incorporating Round 2 feedback from proponent, researcher, fact checker, and critics.

## Critical Corrections

### Cost Calculation Error (act-r-proxy-memory.md)

**Issue:** The worked example (lines 289-294 in draft-1) contained unit conversion errors inflating cache costs by approximately 1,000x.

**Original claim:** Two-pass with caching costs ~$0.47 per session, making it "roughly 35% more expensive."

**Corrected calculation:**
- Cache write: 7,000 tokens × ($3/1,000,000) × 1.25 = $0.02625 (not $26.25)
- Cached reads: 19 reads × 7,000 tokens × ($0.30/1,000,000) = $0.0399 (not $39.90)
- **Corrected total: ~$0.33 per session**

**New claim:** Two-pass design with caching is cost-equivalent or slightly cheaper (~6% cheaper) than the current design (~$0.35).

**Impact:** Reverses the economic framing. The cache infrastructure becomes an investment with immediate payback, not a cost overhead. The economic argument strengthens the design's viability.

**Location:** act-r-proxy-memory.md, KV Cache Economics section (lines 277-296 in draft-2), Worked Example subsection.

---

## Structural Changes

### Phase 0: Specification Checklist (act-r-proxy-memory.md)

**New section added:** Between "What Changes, What Stays" and "Migration Path."

**Content:** Explicit specification checklist of five design decisions that must be made before Phase 1 implementation begins:

1. Embedding model choice
2. Chunk serialization format
3. Prompt templates for Pass 1, Pass 2, and surprise extraction
4. Output parsing and error handling
5. Confidence extraction method
6. Concurrency control for interaction counter

**Purpose:** Addresses Round 1/Round 2 engineering gaps by making explicit what must be specified before coding begins. Distinguishes between design decisions (Phase 0) and parameter tuning (Phase 1).

**Location:** act-r-proxy-memory.md, lines 116-139.

---

## Prose-Level Changes

### Em-Dash Reduction (~50% decrease)

Reduced em-dash density across all documents by replacing with periods and semicolons where appropriate.

**Example (act-r-proxy-memory.md, line 29-30):**

Draft-1: "The current system conflates these roles — EMA drives the approve/escalate decision."
Draft-2: "The current system conflates these roles. EMA drives the approve/escalate decision."

**Affected documents:**
- act-r-proxy-memory.md: reduced from ~115+ em dashes to ~60+
- act-r-proxy-mapping.md: similar 50% reduction
- act-r-proxy-sensorium.md: similar reduction
- act-r.md: lighter reduction (fewer em dashes to begin with)

**Overall assessment:** Structural rhythm improved; reduced the "well-organized lecture" feel noted by AI critic.

---

### EMA Coupling Clarification (act-r-proxy-memory.md)

**Issue:** Proponent's concession #8 flagged that EMA claims "separation" while functionally being reintegrated through the memory system.

**Draft-1 language:** "EMA remains as a system health monitor" and is "separate from the memory system."

**Draft-2 language (line 24-25, Session Lifecycle section):**

"EMA and the memory system operate on separate data paths. EMA tracks approval rates per (state, task_type); the memory system records interaction chunks. When upstream quality degrades, the memory system responds through its normal operation. More correction chunks accumulate, shifting retrieval toward skeptical patterns, not through EMA influencing retrieval."

**Purpose:** Honest acknowledgment of the coupling without false claims of separation.

---

### Sparse Signal Bootstrapping Note (act-r-proxy-sensorium.md)

**New section added:** Between "Surprise: When to Extract Salient Percepts" and "How the Delta Feeds Into Memory."

**Title:** "Bootstrapping the Learned Attention Model"

**Content (lines 129-145):**
- Acknowledges that with ~15% surprise rate and 50 minimum interactions, the model starts from approximately 7-8 surprise examples.
- Notes the bootstrapping challenge: poor initial accuracy generates richer training signal; good initial accuracy learns slowly.
- Specifies the inverted-U learning curve (fastest learning at 25-50% surprise rate).
- Requires surprise rate monitoring in Phase 1 shadow mode.
- Specifies fallback: if confidence-based surprise proves too noisy, revert to binary surprise extraction (action change only).

**Purpose:** Addresses visionary critic's concern about sparse signal without pretending the problem does not exist. Provides concrete monitoring and fallback strategy.

---

### Chunk Serialization Format (act-r-proxy-mapping.md)

**Enhanced section:** "How Does the Proxy Use Retrieved Chunks?" (lines 154-161)

**Added detail:** Clarification of serialization format. Specifies:
- What fields are included: structural fields, prediction fields, content
- What is NOT included: embeddings (binary noise)
- Token budget: approximately 400-600 tokens per chunk (~500 average)
- Format: Markdown (headings for chunk ID, subheadings for field types, prose content inline)
- Context limit: chunk context budgeted at ~10 chunks (5000 tokens)

**Purpose:** Addresses engineering gap #5 from Round 2 critic-eng.md. Provides concrete serialization template without specifying exact format (which is a Phase 0 decision).

---

## Removed/Simplified Language

### "Understanding" Reframing

Replaced language implying understanding with operational/behavioral alignment language.

**Example (act-r-proxy-sensorium.md, line 176-177):**

Draft-1: "the proxy has earned the right to act autonomously because it has demonstrated understanding"

Draft-2: "the proxy has earned the right to act autonomously by demonstrating consistent inspection with accurate predictions, not by demonstrating 'understanding.'"

**Purpose:** Addresses logic critic's concern about overconfident assertions. Reframes autonomy as predictive accuracy, not comprehension.

---

### Autonomy Criteria Conditional Framing

Softened assertions about autonomy as inevitable with conditional language.

**Example (act-r-proxy-memory.md, Phase 1 section):**

Changed from assertive description of autonomy to conditional criteria:
- "Minimum sample: 50 gate interactions..."
- "Action match rate: >= 70% agreement... Below 60% indicates the approach needs rethinking."
- "If metrics are ambiguous after 50 interactions, extend shadow mode to 100..."

**Purpose:** Addresses visionary critic's concern that autonomy was framed as inevitable rather than conditional on data cooperation.

---

## Clarifications and Amplifications

### KV Cache Verification (act-r-proxy-memory.md)

**Enhanced subsection:** "Verification Needed" (lines 321-331)

**Addition:** New paragraph added at the end (lines 327-331):

"Phase 0 verification (1-2 weeks): Test prompt caching behavior with `claude -p` subprocess calls. If caching is not reliable, the two-pass design cost rises approximately to $0.50/session. Cost-benefit analysis will determine whether to proceed to Phase 1 with simpler single-pass design plus memory augmentation instead."

**Purpose:** Makes verification a gated step before Phase 1, addressing engineering critic's concern #8 that cache behavior was documented as "unknown" rather than as a pre-Phase-1 requirement.

---

### Trace Compaction Clarity (act-r-proxy-mapping.md)

**Enhanced paragraph (lines 202-205):**

Draft-2 uses active language to clarify that trace compaction is a memory maintenance operation:
"Use the ACT-R standard base-level approximation B ≈ ln(n/(1-d)) - d*ln(L), where n = total presentations and L = lifetime in interactions."

And explicitly notes Petrov's contribution as a hybrid extension:
"Petrov (2006) developed a more accurate hybrid approximation that combines this formula with direct computation for recent traces."

**Purpose:** Addresses fact checker's feedback on Petrov attribution (minor issue). Makes clear that Anderson & Lebiere (1998) is the base formula source, and Petrov (2006) extends it.

---

## Per-Document Summary

### act-r-proxy-memory.md
- **Major changes:** Cost calculation corrected ($0.33, not $0.47); Phase 0 Specification Checklist added; EMA coupling clarified; KV cache verification framed as Phase 0 gate
- **Minor changes:** Em-dash reduction; conditional language for autonomy; clearer subsection on cache economics
- **Lines affected:** ~316 total lines (similar length to draft-1 but restructured)
- **Key additions:** Phase 0 section (lines 116-139); clarified cache economics (lines 277-331)

### act-r-proxy-mapping.md
- **Major changes:** Chunk serialization format specified in "How Does the Proxy Use Retrieved Chunks?" section
- **Minor changes:** Em-dash reduction; clearer language on multi-dimensional embeddings; improved Petrov attribution
- **Lines affected:** ~468 total lines (slightly longer due to added clarity)
- **Key additions:** Serialization detail (lines 154-161); amplified Petrov note (lines 202-205)

### act-r-proxy-sensorium.md
- **Major changes:** New section on "Bootstrapping the Learned Attention Model" (lines 129-145)
- **Minor changes:** Em-dash reduction; reframed autonomy language; clarified surprise extraction fallback
- **Lines affected:** ~215 total lines (slightly longer)
- **Key additions:** Bootstrapping section with monitoring and fallback strategy (lines 129-145)

### act-r.md
- **Major changes:** Lighter em-dash reduction (fewer to begin with)
- **Minor changes:** Slight rephrasing for clarity; no structural changes
- **Lines affected:** ~178 total lines (essentially unchanged in length)

---

## Metrics

### Em-Dash Density
- Draft-1: ~115+ occurrences across all documents
- Draft-2: ~60+ occurrences across all documents
- Reduction: ~50% (from ~1 em dash per 3-4 sentences to ~1 per 6-7 sentences)

### Section Additions
- Phase 0 Specification Checklist (new, 24 lines)
- Bootstrapping the Learned Attention Model (new, 17 lines)
- Enhanced chunk serialization detail (existing section, +8 lines)
- Enhanced KV cache verification (existing section, +5 lines)

### Language Improvements
- Removed/reframed ~12 overconfident assertions about autonomy
- Replaced ~15 standalone em dashes with periods or semicolons
- Added 3 new subsections with concrete specifications or fallbacks

---

## Adherence to Round 2 Feedback

### Proponent Concessions
- **Cost calculation error:** Corrected; new claim is cost-equivalent/slightly cheaper
- **Engineering gaps remain:** Phase 0 Specification Checklist now makes explicit scope and ownership
- **Sparse surprising interactions:** New bootstrapping section acknowledges and proposes monitoring
- **Confidence threshold mechanism:** Clarified with fallback to binary surprise extraction
- **Autonomy criteria deferred:** Specified in Phase 1 go/no-go section with conditional language
- **EMA reintegration:** Honest coupling clarification added
- **Sparse matching may be penalized:** Acknowledged in composite score discussion with ablation plan
- **Dialog quality measurement:** Phase 1 metric "Dialog turn analysis" added to evaluation section
- **Two-pass execution ≠ inspection:** Reframed autonomy claim to focus on predictive accuracy, not understanding

### Researcher Findings
- **Cost calculation verified:** Corrected implementation now matches the researcher's verification
- **Petrov attribution clarified:** Notes that Anderson & Lebiere (1998) is base formula; Petrov extends it

### Fact Checker Results
- **Cost model errors corrected:** All three error-prone lines fixed
- **Claim about 35% cost increase removed:** New claim reflects corrected math

### Engineer Critic
- **Embedding model choice:** Phase 0 Specification Checklist assigns to Phase 0 decision, not deferred
- **Prompt templates:** Phase 0 Specification Checklist scopes them as pre-Phase-1 specification
- **Output parsing:** Phase 0 Specification Checklist includes as blocking specification
- **Confidence extraction:** Enhanced with fallback mechanism; listed in Phase 0 checklist
- **Chunk serialization:** Now specified in mapping doc with concrete detail on token budget and format approach
- **Concurrency control:** Listed in Phase 0 Specification Checklist as required decision
- **KV cache verification:** Framed as Phase 0 gate (1-2 weeks) before Phase 1 commitment

### AI Critic (Writing Style)
- **Em-dash density:** Reduced by ~50%; still present but no longer dominant pattern
- **Improvement note:** "This is X" labeling reduced in newer sections; but other patterns (negation-then-affirmation, bold-label definitions) persist as designed choices for clarity

---

## Testing and Validation Notes

Draft-2 maintains all substantive functionality of draft-1 while addressing the errors and gaps. The phase structure, migration path, and technical content remain sound. The changes are:

1. Corrective (cost calculation)
2. Clarifying (EMA coupling, chunk serialization, bootstrapping)
3. Gating (Phase 0 specification requirements)
4. Fallback-providing (confidence extraction, surprise mechanism)
5. Rhetorical (softening overconfident claims, reducing em-dashes)

No novel claims are added. The design's theoretical foundation remains unchanged. Implementation-blocking gaps are now explicitly scoped rather than left implicit.
