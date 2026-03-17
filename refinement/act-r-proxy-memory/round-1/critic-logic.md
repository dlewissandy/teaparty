# Logical Review — Round 1

## Contradictions

### 1. The embedding dimensions are inconsistent across documents

The root document (`act-r-proxy-memory.md`, line 148) defines MemoryChunk with four embedding dimensions: `embedding_situation`, `embedding_stimulus`, `embedding_response`, `embedding_salience`.

The mapping document (`act-r-proxy-mapping.md`, lines 37-41) defines five: `embedding_situation`, `embedding_artifact`, `embedding_stimulus`, `embedding_response`, `embedding_salience`.

The sensorium document (`act-r-proxy-sensorium.md`, lines 118-125) defines six: situation, artifact, upstream, stimulus, response, salience.

These cannot all be the canonical schema. The root document's MemoryChunk is presented as the definitive data structure for the KV cache future design, yet it omits `embedding_artifact` -- the vector that the mapping and sensorium documents treat as central to retrieval (the artifact is what Pass 2 inspects and what drives the prior-posterior delta). The sensorium document adds `upstream` as a dimension that appears in neither of the other two documents' schemas and is absent from the implementation sketch.

### 2. "Salient percepts" are stored only on surprise, but the chunk schema always includes them

The root document's session lifecycle pseudocode (lines 136-140) specifies that when `prior.action == posterior.action`, there is "no surprise, no additional calls" -- meaning no description and no salient percepts are extracted. But the mapping document's chunk schema (lines 26-27) includes `prediction_delta` and `salient_percepts` as standard fields, and the sensorium document builds its entire "learned attention" argument on accumulating salient percepts across interactions (lines 138-146). If most gates produce no surprise (the root document says so explicitly at line 184: "Most gates produce no surprise"), then most chunks have empty salience fields. The learned attention model depends on the accumulation of salience deltas, but if these are empty for the majority of interactions, the attention model is built on a minority of data. This is not acknowledged; the sensorium document describes learned attention as though every interaction contributes salience signal.

### 3. Whether the proxy can auto-approve

The root document (lines 11-13) states the proxy's job is to "proxy the behavior of the human" and that "Approval or rejection is the final act of a rich conversation, not a binary gate." It criticizes the current model for skipping dialog (line 29): "A high EMA means the proxy auto-approves without asking any questions."

The sensorium document (line 146) states: "the proxy has earned the right to auto-approve because it's attending to what the human would attend to." And again at line 181: "A proxy that auto-approves because its prior correctly anticipated the artifact would have no issues -- and the posterior confirmed it -- has demonstrated understanding."

These are in tension. The root document's argument is that the current auto-approve mechanism is fundamentally flawed because it skips the dialog that maintains quality. The sensorium document argues that a sufficiently calibrated proxy should auto-approve. The root document does not carve out an exception for "auto-approve after two-pass confirmation" -- its critique is structural: skipping the dialog is rubber-stamping. The sensorium document then reintroduces auto-approval through a different mechanism without addressing why this form of skipping dialog is acceptable when the prior form was not.

### 4. Chunk creation happens at different times in different accounts

The mapping document (lines 77-88) describes gate mode chunk creation as: proxy predicts, human responds, chunk is created with the outcome. The chunk records what happened.

The root document's session lifecycle (lines 142-149) describes the STORE step as creating a chunk "from surprise + human response + proxy error" -- but line 139 says when there is no surprise, there are "no additional calls." It does not say "no chunk is stored." Yet the chunk is defined as containing surprise fields. The question of whether a chunk is created for non-surprise interactions is left ambiguous in the root document's lifecycle but is unambiguous in the mapping document (every interaction produces a chunk). These two accounts need to agree on whether non-surprise gates produce chunks.

## Non Sequiturs

### 1. "Corrections are more informative" does not follow from "richer content"

The mapping document (line 170) argues: "Corrections are more informative than approvals, and the memory system naturally captures this because informative memories have richer associations." The reasoning is: corrections include a delta (what was wrong), therefore they have more content, therefore they have richer embeddings, therefore they are retrieved more precisely.

This does not follow. Having more text in a field makes the embedding *different*, not necessarily *more precise* for future retrieval. A long, rambling correction could produce a diffuse embedding that matches many situations weakly. A terse, pointed correction could produce a specific one. The informativeness of a correction is an empirical property of the text, not a logical consequence of the field being non-empty. The argument treats "more content" as equivalent to "more informative retrieval," which is a category error between information quantity and retrieval specificity.

### 2. The cost model conclusion does not follow from its premises

The root document (lines 239-265) concludes that two-pass with caching is "cheaper than the current single-pass model." But the cost model only counts token-equivalents for the proxy's prefix processing. It omits: (a) the actual cache-write cost, which Anthropic charges at a higher rate than standard input for the first write; (b) the output token cost, which doubles because there are two passes generating output; (c) the surprise extraction calls (2 LLM calls with their own input+output costs, not just the 500-token input estimate). The model counts input token-equivalents for prefix reuse and concludes about total cost. The conclusion is about a narrower quantity than the framing implies.

### 3. "Interaction-based time is faithful to Anderson & Schooler" overstates the mapping

The root document (line 51) and the ACT-R document (lines 50-53) claim that interaction-based time is faithful to Anderson & Schooler (1991) because their analysis was "event-based." Anderson & Schooler measured the statistical structure of environmental stimuli (newspaper headlines, email) -- the *world's* event stream, not the *agent's* decision stream. The proxy's interaction counter only advances when the proxy itself acts (gate decisions, dialog turns). It does not advance when the human acts outside the system, when other agents produce work, or when the environment changes. The proxy's event stream is a sparse, self-selected subset of the environmental event stream. The argument that d=0.5 transfers from Anderson & Schooler's analysis to this interaction counter assumes that the proxy's decision events have the same statistical structure as the broad environmental events Anderson & Schooler measured. This is not argued; it is asserted.

### 4. Multi-dimensional embedding average does not produce "low-fan spreading activation"

The mapping document (lines 51, 131-132) and sensorium document (line 132) claim that averaging cosine similarities across independent embedding dimensions is "the equivalent of low-fan spreading activation." In ACT-R, low fan means a chunk has few associations, making each association stronger (activation is divided among fewer targets). An average of cosine similarities across dimensions does not have this property -- a chunk that happens to score moderately on all five dimensions gets the same average as a chunk that scores very high on two and zero on three. The averaging operation does not penalize high-fan (broadly associated) chunks or reward low-fan (specifically associated) ones. The claimed equivalence to ACT-R's fan effect is not established by the mechanism described.

## Unstated Assumptions

### 1. The LLM can produce meaningfully different outputs between Pass 1 and Pass 2

The entire two-pass architecture depends on the assumption that an LLM, given memories and context but no artifact, will produce a prediction that is meaningfully distinct from the prediction it produces when the artifact is added. If the LLM's prior is dominated by the instruction to predict (always outputting a cautious "escalate") or by the retrieved memories (always mimicking the most-activated pattern), the prior-posterior delta carries no signal. The design assumes the LLM is capable of genuinely conditioning on the presence or absence of the artifact in a way that produces calibrated, distinct predictions. This is an empirical property of current LLMs that is not argued for.

### 2. Cosine similarity on embedded text is a valid substitute for ACT-R spreading activation

The mapping document (lines 112-116) states: "We have something better: vector embeddings." ACT-R spreading activation is a structural, graph-based mechanism where activation flows along typed associations between chunks. Cosine similarity on text embeddings is a statistical measure of surface-level semantic overlap. These are different operations with different properties. Spreading activation can capture that "rollback plan" is associated with "database migration" through a chain of typed links even if the texts share no words. Embedding similarity requires that the textual representations be close in embedding space. The substitution is assumed to be an upgrade ("something better") without argument.

### 3. The proxy processes one gate at a time, and cross-task learning is beneficial

The root document (lines 105-107) assumes serial processing is both feasible and desirable: "Gates enter a FIFO queue and the proxy processes them one at a time. This is how a human works." The argument for cross-task learning (line 107: "what the proxy learns from dispatch A's gate is available when it processes dispatch B's gate") assumes that learning from an unrelated dispatch is beneficial rather than contaminating. If dispatch A is a security review and dispatch B is a documentation update, the surprise from A's security gap has no relevance to B. The design assumes cross-task sequential processing produces useful priming rather than interference, but this is not argued -- it is stated as a feature.

### 4. The activation threshold is self-regulating

The root document (line 286) claims: "In practice, the activation threshold tau limits loading to the 20-50 most active chunks -- self-regulating as memory accumulates." This assumes that as the number of chunks grows, the distribution of activation scores will naturally spread such that only 20-50 remain above tau = -0.5. Whether this happens depends on the reinforcement rate (how often chunks are retrieved and re-traced), the interaction tempo, and the decay parameter -- none of which are analyzed for the proxy's expected usage patterns. In a system with low interaction counts and frequent reinforcement of many chunks, the threshold may admit far more than 50 chunks or far fewer.

### 5. EMA and ACT-R memory are cleanly separable into "monitoring" and "decision"

The root document (lines 17-23) separates EMA (system health) from ACT-R memory (proxy behavior). But EMA's trend signal ("approval rate at PLAN_ASSERT dropped from 0.8 to 0.4") is information about the proxy's environment that could legitimately affect its behavior -- not just its monitoring dashboard. If the proxy knows that upstream quality has degraded, it should arguably become more skeptical. The design assumes this information can be cleanly separated from decision-making, but a rational agent that ignores known environmental degradation in its decisions is not modeling the human faithfully (a human who noticed the trend would adjust their scrutiny).

## Assessment

The document set is largely coherent in its central argument: replace a scalar confidence model with activation-weighted memory retrieval to produce richer proxy behavior. The core logical structure -- ACT-R provides the forgetting curve, embeddings provide context sensitivity, two-pass prediction provides salience -- holds together as a design.

However, there are structural problems at the seams. The three documents disagree on the embedding schema (4, 5, or 6 dimensions depending on which document you read). The root document's critique of auto-approval is contradicted by the sensorium document's endorsement of it through a different mechanism, without acknowledging the tension. The cost model's conclusion is narrower than its framing suggests. Several key mechanisms -- the averaging of cosine similarities as "low-fan spreading activation," the transfer of d=0.5 from environmental event streams to agent decision streams, the claim that corrections are inherently more retrievable -- are asserted with rhetorical confidence but not logically established.

The most significant structural issue is the relationship between "most gates produce no surprise" and the learned attention model that depends on accumulated surprise deltas. If the system works as designed (most predictions are confirmed), the salience signal is sparse, and the attention model learns slowly from a minority of interactions. This is not necessarily fatal, but it is a gap between the design's claims and its own premises that should be explicitly addressed.
