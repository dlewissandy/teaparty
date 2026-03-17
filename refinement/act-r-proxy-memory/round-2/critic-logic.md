# Logical Review -- Round 2

## Contradictions

### 1. Threshold tau is applied to a combined score, not to activation

The ACT-R theory document (act-r.md, lines 111-117) defines the retrieval threshold tau as a minimum activation level: "A chunk is retrieved if its activation exceeds the retrieval threshold tau." The probability-of-retrieval equation (line 122) uses tau against A (activation). The parameter table (line 143) describes tau's role as "Minimum activation for retrieval."

The mapping document's `retrieve()` function (lines 357-363) applies tau to the combined score (normalized activation + semantic similarity + noise), not to raw activation B. The combined score is a different quantity on a different scale -- it is the weighted sum of a [0,1]-normalized activation, a [-1,1] cosine similarity, and unbounded logistic noise. A tau of -0.5 means something entirely different when applied to this composite than when applied to raw activation.

The theory document defines tau as an activation threshold. The implementation uses it as a composite-score threshold. These are two different operations sharing the same symbol and the same numeric value (-0.5) without acknowledgment that the semantics changed.

### 2. The retrieval score formula contradicts the probability-of-retrieval equation

The theory document (act-r.md, lines 119-123) presents the soft-threshold retrieval probability: `P(retrieve) = 1 / (1 + exp(-(A - tau) / s))`. This equation uses activation A, threshold tau, and noise scale s as a sigmoid gating mechanism. The noise parameter s governs the softness of the threshold.

The mapping document (lines 129-141) defines a completely different scoring mechanism: `score = activation_weight * normalize(B) + semantic_weight * cosine(...) + noise`. Here noise is additive to the score, not a sigmoid parameter. The retrieval probability equation from act-r.md is never referenced in the mapping document's retrieval pipeline -- instead, a hard threshold (`if score > tau`) is applied at line 362.

The theory document presents noise as controlling probabilistic retrieval via a sigmoid. The implementation adds noise as a random offset to a deterministic score and then applies a hard cutoff. These are different retrieval mechanisms. The theory document's soft-threshold equation is presented as the governing retrieval model but is not implemented; the implementation uses a mechanism the theory document does not describe.

### 3. Chunks store "salient_percepts" as a list but the schema has no field for it

The sensorium document (line 109) and the mapping document's chunk example (line 26) both show `"salient_percepts": ["no rollback strategy", "database migration risk"]` as a list field in the chunk. But the MemoryChunk dataclass (mapping document, lines 208-229) has no `salient_percepts` field. The SQL schema (lines 234-255) has no `salient_percepts` column. The `record_interaction()` function (lines 367-417) has no `salient_percepts` parameter. The example JSON shows a field that the implementation does not store or retrieve. This was not raised in round 1 because the embedding schema inconsistency was the focus; this is a different issue -- a field that appears in examples but is absent from the data model.

## Non Sequiturs

### 1. Multi-dimensional cosine average does not produce the claimed intersection effect

The mapping document (lines 305-306) states: "The semantic score is the average cosine across matched dimensions -- chunks matching on more dimensions score higher (intersection effect)." This does not follow from the implementation. The `retrieval_score()` function (lines 319-323) computes `sem = sum(similarities) / len(similarities)` -- an average. A chunk matching on 2 of 5 dimensions with cosines of 0.9 and 0.8 gets sem = 0.85. A chunk matching on 5 of 5 dimensions with cosines of 0.5, 0.4, 0.3, 0.2, 0.1 gets sem = 0.30. The chunk matching fewer dimensions scores higher. Averaging penalizes breadth when additional dimensions have lower similarity; it does not reward matching on more dimensions. The intersection effect the document claims requires an aggregation function (sum, product, or weighted sum with dimensionality bonus) that the averaging function does not provide.

Round 1 addressed the "low-fan spreading activation" analogy by removing it, but the replacement claim -- that averaging produces an "intersection effect" -- is a new assertion introduced in draft-1 that is equally unsupported by the arithmetic.

### 2. The REINFORCE step inflates activation of irrelevant chunks

The session lifecycle (act-r-proxy-memory.md, lines 169-170) specifies: "REINFORCE: add trace N to each loaded chunk." This means every chunk loaded into the session prefix receives a new trace at every gate, regardless of whether the chunk was relevant to that gate's retrieval. A chunk about documentation formatting loaded at session start gets reinforced when the proxy processes a security gate, a database gate, and a deployment gate -- accumulating traces for interactions where it contributed nothing.

The mapping document (line 73) states: "Memories that are useful stay active; memories that are never retrieved decay." But the REINFORCE step violates this principle: memories that were loaded (because they were above threshold at session start) stay active regardless of usefulness, because they are reinforced at every gate. This creates a self-reinforcing loop: highly-activated chunks get loaded, get reinforced by every gate, and remain highly activated for the next session. The round 1 review removed "explicit reinforcement by outcome similarity" (trace rule 3) because the proponent called it "a bias bomb." The REINFORCE step has an analogous feedback structure -- it reinforces chunks based on loading rather than retrieval relevance.

This concern is distinct from round 1's HM #11 (which was about implicit reinforcement by outcome similarity). The REINFORCE step is different: it reinforces by session-loading, which creates a popularity bias rather than an outcome bias.

### 3. The cold start argument proves too much

The mapping document (lines 164-168) argues: "With zero chunks in memory, retrieval returns nothing. The proxy's LLM receives no memories and must reason from the system prompt and artifact alone. This is equivalent to the proxy escalating every gate to the human -- the correct cold-start behavior."

Then: "The new system's conservatism is more informative because it generates interaction data that builds the memory from the first session onward."

The second claim does not follow from the first. The current EMA system also generates interaction data from the first session onward -- every gate outcome updates the EMA scalar. The argument that the new system's cold start is "more informative" assumes that chunk-based interaction data is inherently more valuable than scalar updates. This may be true, but it is the conclusion the document set is trying to establish, not a premise available for the cold-start argument. The cold-start section uses its own conclusion as evidence.

## Unstated Assumptions

### 1. Min-max normalization over the candidate set makes activation meaningful

The mapping document (lines 136-142) normalizes B via min-max scaling over the candidate set returned by structural filtering. This means activation's contribution to the score depends entirely on what other chunks happen to be in the candidate set. If 9 chunks have B near 2.0 and one chunk has B of -1.0, the outlier gets normalized to 0 while the 9 others are compressed into the top of [0,1]. If the query returns a different set of candidates, the same chunk's normalized B changes. The normalization is relative, not absolute -- a chunk's activation score is not a property of the chunk but of the query that retrieved it.

This has a concrete consequence: the activation_weight / semantic_weight balance (0.5 / 0.5) means different things for different queries. A query that returns chunks with a wide activation spread gives activation strong discriminating power. A query that returns chunks with similar activations (common when many chunks were reinforced in the same session) makes activation nearly uniform, and the score becomes dominated by semantic similarity. The "starting point: 0.5 / 0.5" is not a stable configuration -- it is a different weighting for every query.

### 2. The LLM will use retrieved memories rather than override them

The mapping document (lines 158-159) describes step 5 of retrieval: "The proxy's LLM prompt receives the retrieved chunks as context: 'Here are your relevant memories of working with this human...' The LLM reasons over them to produce a prediction."

The design assumes the LLM will treat the retrieved memories as primary evidence for its predictions. But LLMs have their own priors from pretraining. If retrieved memories say "this human always approves documentation tasks" but the LLM's general knowledge says "documentation plans should be reviewed carefully," the LLM may override the memories. The proxy's behavior then reflects the LLM's pretrained disposition rather than the human's learned patterns. The entire memory architecture depends on the LLM faithfully conditioning on the injected memories rather than falling back to its own judgment. This is not argued for; the design implicitly treats the LLM as a transparent reasoner over the provided context.

### 3. Five independent embeddings of short text fragments produce useful semantic vectors

The `record_interaction()` function (mapping document, lines 410-414) embeds individual fields: `embed(f'{state} {task_type}')` for situation, `embed(human_response)` for response, `embed(prediction_delta)` for salience. The situation embedding is generated from text like "PLAN_ASSERT security" -- two tokens. The salience embedding comes from text like "Missing rollback section changed prediction" -- one sentence.

Embedding models are trained on documents and passages, not on two-word labels or single sentences. The semantic geometry of the embedding space may not be meaningful for inputs this short. Two-token inputs like "PLAN_ASSERT security" and "PLAN_ASSERT documentation" may be closer together in embedding space than their semantic difference warrants, or farther apart than intended, because the model has little signal to work with. The design assumes that embedding short text fragments produces vectors with useful cosine-similarity geometry. This is an empirical property of the embedding model that is not discussed.

### 4. The surprise confidence threshold (0.3) is meaningful for LLM-generated confidence scores

The sensorium document (line 81) triggers moderate surprise when `|posterior_confidence - prior_confidence| > 0.3`. This assumes that the confidence values the LLM generates are calibrated -- that a 0.3 difference in self-reported confidence reflects a genuine 0.3 change in the LLM's internal certainty about the prediction. LLMs are well-documented to produce poorly calibrated confidence scores, especially when asked to self-assess. A threshold of 0.3 on uncalibrated scores may trigger on noise (the LLM happened to say 0.7 instead of 0.4) or miss real shifts (the LLM consistently reports confidence near 0.8 regardless of its actual uncertainty). The graded surprise mechanism introduced in draft-1 depends on a quantity whose reliability is not established.

## Assessment

The document set is more logically coherent than round 1. The embedding schema is harmonized, the auto-approval tension is resolved, the chunk creation ambiguity is gone, and the parameter provenance claims are corrected. The round 1 review was effective.

The remaining issues fall into two categories. First, there are internal contradictions between the theory document and the implementation: tau means different things in different places, the soft-threshold retrieval equation is presented but not implemented, and the `salient_percepts` field appears in examples but not in the data model. These are consistency bugs that would surface during implementation and are straightforward to fix.

Second, there are structural assumptions that the round 1 revisions introduced or left unexamined. The REINFORCE step creates a popularity bias analogous to the "explicit reinforcement" rule that round 1 removed. The min-max normalization makes the activation/similarity balance query-dependent. The confidence threshold for graded surprise depends on LLM calibration that is not established. The multi-dimensional average still does not produce the intersection effect the prose claims. These are not fatal to the design, but they are places where the document's claims exceed what its mechanisms deliver.
