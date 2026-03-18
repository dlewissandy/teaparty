# Drift Evaluation — Round 2

## Verdict: PASS

Draft-2 maintains fidelity to the anchor's core intent across all major sections. The changes are corrective (cost calculation), clarifying (EMA coupling, chunk serialization, bootstrapping), and structural (Phase 0 addition) — none of which dilute the design's ambition or voice. The economic argument is actually strengthened by the corrected cost model.

---

## Drift Flags

### The Proxy's Job (act-r-proxy-memory.md)

**Anchor says:** The proxy's job is to model how the human *thinks*, capturing attention, reasoning, concerns, and tradeoffs — not just binary decisions.

**Draft says:** The proxy requires modeling what the human would retrieve and attend to in a given context. The LLM reasons over those memories to generate contextually appropriate questions and concerns.

**Assessment:** Recharacterized, but preserved in intent.

**Justified:** Yes. Draft-2 explicitly names "memory accessibility" and "retrieval" as the mechanism by which thinking is modeled. This is more precise than anchor's abstract "model how the human thinks." The mechanism is ACT-R retrieval — which is the whole point of the design.

---

### Two Systems, Two Roles (act-r-proxy-memory.md, Session Lifecycle section)

**Anchor says:** ACT-R memory drives proxy behavior, EMA observes outcomes and reports on system health. They are separated.

**Draft says:** EMA and the memory system operate on separate data paths. EMA tracks approval rates. The memory system records interaction chunks. When upstream quality degrades, the memory system responds through its normal operation (more correction chunks accumulate), not through EMA influencing retrieval.

**Assessment:** Preserved and clarified.

**Justified:** Yes. Anchor's claim of "separation" was rhetorically cleaner but functionally ambiguous. Draft-2 is more honest: EMA doesn't influence retrieval *state*, but the effects of degraded quality flow through the memory system's normal operation (accumulated correction chunks shift retrieval toward skeptical patterns). This is the coupling pointed out in proponent concession #8 and is now acknowledged explicitly rather than glossed.

---

### What Changes in the Current Model (act-r-proxy-memory.md)

**Anchor says:** EMA skips the dialog; lacks context sensitivity; can't distinguish habitual from episodic patterns; has no connection to discovery mode.

**Draft says:** EMA skips inspection (the artifact is never read). Two-pass prediction ensures inspection through explicit prior-posterior comparison. (Other criticisms preserved.)

**Assessment:** Recharacterized, stronger.

**Justified:** Yes. Anchor's language "skips the dialog" is abstract. Draft-2 makes it concrete: "auto-approves without reading the artifact." The addition of "two-pass prediction ensures inspection" directly connects the problem to the solution, which wasn't explicit in anchor.

---

### Autonomous Proxy Action (act-r-proxy-memory.md, "What Changes" section)

**Anchor says:** The proxy earns autonomy when it has demonstrably inspected via two-pass prediction and prior-posterior agreement reflects genuine understanding.

**Draft says:** The proxy has earned the right to act autonomously by demonstrating consistent inspection with accurate predictions, not by demonstrating "understanding" (with quotes around understanding).

**Assessment:** Softened but preserved in mechanism.

**Justified:** Yes. Anchor's use of "genuine understanding" was overconfident (as logic critic noted). Draft-2 explicitly rejects the claim and replaces it with "accurate predictions," which is more defensible and operationalizable.

---

### Cost Model (act-r-proxy-memory.md, Cache Economics / Worked Example)

**Anchor says:** Two-pass with caching costs ~$0.47 per session, making it roughly 35% more expensive than current design.

**Draft says:** Corrected to ~$0.33 per session (cost write: $0.02625, cached reads: $0.0399, new content: $0.12, surprise output: $0.015, output: $0.15), making it roughly 6% cheaper than current design (~$0.35).

**Assessment:** Corrected (error was 1000x unit conversion).

**Justified:** Yes. This is a critical correction with profound implications for the economic argument. Anchor's version made caching look like overhead; draft-2 shows it as a net win. The economic viability is *strengthened*, not weakened. The design's ambition is preserved and its cost-effectiveness is improved.

---

### Phase 0: Specification Checklist (act-r-proxy-memory.md)

**Anchor says:** Nothing — this section is new in draft-2.

**Draft says:** Before Phase 1 begins, six design decisions must be made explicitly (embedding model, chunk serialization, prompt templates, output parsing, confidence extraction, concurrency control).

**Assessment:** Addition, not drift.

**Justified:** Yes. This is a structural change that addresses engineering gaps identified in Round 2 feedback. It adds rigor and explicitness without removing or weakening any anchor claims. The checklist distinguishes design decisions (Phase 0) from parameter tuning (Phase 1), which was implicit in anchor but now explicit.

---

### KV Cache Verification (act-r-proxy-memory.md, Verification Needed section)

**Anchor says:** Cache behavior is unknown; verification needed.

**Draft says:** Verification needed with explicit 1-2 week Phase 0 gate. If caching fails, cost rises to ~$0.50 and a cost-benefit analysis determines whether to proceed with single-pass design instead.

**Assessment:** Clarified with gating.

**Justified:** Yes. Anchor left verification as an open question. Draft-2 makes it a blocking pre-Phase-1 requirement with explicit cost consequences, which is the right way to handle an unknown risk factor.

---

### EMA Coupling Clarification (act-r-proxy-memory.md, Session Lifecycle section)

**Anchor says:** EMA "remains as a system health monitor" and is "separate from the memory system."

**Draft says:** EMA and memory operate on separate data paths, but when quality degrades, the memory system responds through accumulated correction chunks, not through EMA influencing retrieval decisions.

**Assessment:** Preserved with honest coupling acknowledgment.

**Justified:** Yes. Anchor's "separate" claim was technically true but functionally misleading. They share causal paths: degraded upstream quality produces correction chunks, which shift retrieval patterns. Draft-2 acknowledges this coupling explicitly while maintaining the architectural separation (EMA doesn't directly control retrieval logic). This is more honest than anchor's implicit claim of true independence.

---

### Chunk Serialization (act-r-proxy-mapping.md, "How Does the Proxy Use Retrieved Chunks?")

**Anchor says:** Nothing specific — section exists but provides no detail.

**Draft says:** Chunks are serialized to Markdown (headings per chunk ID, subheadings for field types, prose inline). Each chunk ~400-600 tokens (~500 average). Context limited to ~10 chunks at 5000 tokens. Embeddings are not included (binary noise).

**Assessment:** Addition, not drift.

**Justified:** Yes. Anchor left serialization format unspecified. Draft-2 provides concrete detail without mandating exact format (still Phase 0 decision). This addresses engineering critic's gap #5.

---

### Bootstrapping the Learned Attention Model (act-r-proxy-sensorium.md)

**Anchor says:** Nothing — this section is new in draft-2.

**Draft says:** With ~15% surprise rate and 50 minimum interactions, the model starts from ~7-8 surprise examples. This creates a bootstrapping challenge with an inverted-U learning curve. Phase 1 requires surprise rate monitoring with a fallback to binary surprise extraction if confidence-based surprise proves too noisy.

**Assessment:** Addition, not drift.

**Justified:** Yes. This section directly addresses the visionary critic's concern about sparse signal. Rather than pretending the problem doesn't exist, draft-2 acknowledges it, names the learning curve shape, and provides monitoring + fallback strategy. This strengthens credibility and operational clarity.

---

### Autonomy Criteria (act-r-proxy-sensorium.md, Learned Attention Over Time)

**Anchor says:** The proxy earns autonomy when prior and posterior no longer diverge and the proxy has demonstrated understanding.

**Draft says:** When the prior becomes specific enough and posterior rarely diverges, the proxy has earned the right to act autonomously. But the criteria for granting and revoking autonomy are not specified here; they require operational specification before Phase 3 and must be derived from shadow mode data.

**Assessment:** Softened and deferred.

**Justified:** Yes. Anchor framed autonomy as achievable-by-demonstration. Draft-2 makes clear that autonomy criteria are a high-stakes design decision requiring Phase 1 data. This is more conservative and appropriately cautious given the stakes.

---

### Voice and Tone

**Anchor says:** The proxy proxies human behavior; this is a rich, dialog-driven system.

**Draft says:** Same voice, reduced em-dash density by ~50%, clearer causal language.

**Assessment:** Preserved with improved readability.

**Justified:** Yes. Draft-2 reduces em-dashes (per AI critic feedback) while maintaining the conceptual clarity and rigor. The voice remains appropriately technical and precise.

---

## Overall

Draft-2 maintains the anchor's core design intent across all sections. The major changes are: (1) a critical corrected cost calculation that *strengthens* the economic argument rather than weakening it, (2) honest acknowledgment of EMA-memory coupling rather than overstating separation, (3) explicit Phase 0 specification checklist addressing engineering gaps, and (4) concrete bootstrapping section replacing aspirational language with realistic challenges and fallbacks. No core claims are removed, the ambition is preserved, and the voice is intact. The design is more rigorous, more honest about constraints, and more operationally specific. All changes are justified by the feedback incorporated.

Drift: MINIMAL. Design integrity: PRESERVED. Credibility: IMPROVED.
