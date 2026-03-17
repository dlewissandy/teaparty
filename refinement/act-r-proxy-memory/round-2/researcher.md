# Research Findings — Round 2

## 1. Corrected Citation: Honda et al. (HAI 2025)

**The fact checker is correct. The authors "Nuxoll" and "West" are fabricated for this paper.**

The correct citation is:

> Honda, Y., Fujita, Y., Zempo, K., & Fukushima, S. (2025). Human-Like Remembering and Forgetting in LLM Agents: An ACT-R-Inspired Memory Architecture. In *Proceedings of the 13th International Conference on Human-Agent Interaction* (HAI '25), pp. 229-237. ACM. DOI: 10.1145/3765766.3765803

Key facts:
- The authors are Yudai Honda, Yuki Fujita, Keiichi Zempo, and Shogo Fukushima, affiliated with the University of Tsukuba (XperLab).
- The conference is HAI '25 (13th International Conference on Human-Agent Interaction, Yokohama, November 2025), not HAI '24. Proceedings published January 2, 2026.
- The paper won Best Paper Award at HAI 2025.

**How the fabrication likely occurred.** Andrew Nuxoll is a real researcher who works on episodic memory in the Soar cognitive architecture (Nuxoll & Laird, AAAI 2007; Nuxoll & Laird, Cognitive Systems Research, 2012). His work added ACT-R-inspired activation to Soar's episodic memory. The round-1 researcher's notes mentioned both the HAI paper and ACT-R episodic memory concepts in the same context. The synthesist appears to have conflated Nuxoll's Soar work with the Honda et al. HAI paper, and invented "West" as a co-author (Nuxoll's actual co-author is John Laird). This is a hallucination pattern: the model found a name associated with the topic domain and attached it to the wrong paper.

**Does the paper support the claims in the documents?** Yes — strongly. The Honda et al. paper:
- Stores past utterances as memory chunks
- Computes total activation as base-level activation (BLA) + cosine similarity (weighted by a `speech_in_weight` parameter)
- Uses temporal decay (configurable decay parameter) and retrieval threshold
- Adds stochastic noise to simulate variability
- Embeds retrieved memory chunks into LLM prompts for context-grounded generation
- Is explicitly framed as ACT-R-inspired memory for LLM agents

This is a direct precedent for the TeaParty design. The paper validates the core architectural pattern (ACT-R activation + cosine similarity for LLM agent memory retrieval). The document's description "ACT-R base-level activation + cosine similarity for LLM agent memory retrieval" is accurate for the paper's content.

**Sources:**
- [ACM Digital Library — Honda et al. (2025)](https://dl.acm.org/doi/10.1145/3765766.3765803)
- [XperLab Best Paper Award announcement](https://www.xpercept.aclab.esys.tsukuba.ac.jp/index.php/2025/11/17/hai2025-best-paper/)
- [ResearchGate — Honda et al. (2025)](https://www.researchgate.net/publication/399387961_Human-Like_Remembering_and_Forgetting_in_LLM_Agents_An_ACT-R-Inspired_Memory_Architecture)

---

## 2. Corrected Citation: Meghdadi, Duff, & Demberg (Frontiers 2026)

**The fact checker is correct. "Bhatia, S." is fabricated.**

The correct citation is:

> Meghdadi, M., Duff, J., & Demberg, V. (2026). Integrating language model embeddings into the ACT-R cognitive modeling framework. *Frontiers in Language Sciences*, 5. DOI: 10.3389/flang.2026.1721326

Key facts:
- The authors are Maryam Meghdadi (Saarland University), John Duff (UCLA), and Vera Demberg (Saarland University).
- Published February 23, 2026.
- "Bhatia, S." does not appear on this paper and is fabricated.

**Does the paper support the claims in the documents?** Partially — but the document's description is misleading.

The document describes the paper as "Embedding-based replacement for hand-coded ACT-R associations." The actual paper is a **psycholinguistics study** about associative priming in the Lexical Decision Task (LDT). Its contribution is:
- It replaces hand-coded discrete association features in ACT-R with cosine similarity values derived from language model embeddings (Word2Vec, BERT).
- This enables ACT-R to model associative priming with a realistically-sized mental lexicon (scaling beyond hand-coded feature sets).
- The domain is cognitive modeling of human word recognition, not agent memory architecture.

The document's description is technically not wrong — the paper does replace hand-coded associations with embedding-based ones within ACT-R. But characterizing it as precedent for agent memory architecture overstates the relevance. The paper's contribution is to psycholinguistic modeling: showing that LM embeddings can serve as the association metric within ACT-R's spreading activation framework while preserving the architecture's interpretability.

**What is genuinely relevant:** The paper demonstrates that embedding cosine similarity is a valid substitute for ACT-R's hand-coded association strengths — the same substitution the TeaParty design makes when replacing spreading activation with embedding similarity. The methodological pattern (use LM embeddings where ACT-R uses symbolic associations) transfers, even though the application domain (psycholinguistics vs. agent memory) does not.

**Recommendation:** Keep the citation but revise the description to accurately reflect its psycholinguistics focus, noting that the relevance is the LM-embedding-as-ACT-R-association-metric pattern, not agent memory per se.

**Sources:**
- [Frontiers — Meghdadi et al. (2026)](https://www.frontiersin.org/journals/language-sciences/articles/10.3389/flang.2026.1721326/full)
- [Saarland University PDF](https://www.uni-saarland.de/fileadmin/upload/lehrstuhl/demberg/Publications/Integrating_language_model_embeddings_into_the_ACT-R_cognitive_modeling_framework.pdf)

---

## 3. Park et al. (2023) — Confirmed Correct

The fact checker confirmed this citation is correct. Minor formatting note: the first author's full name is Joon Sung Park, so "Park, J.S." would be more precise than "Park, S." This is a formatting issue, not a factual error.

No further research needed.

---

## 4. REINFORCE Broadcast: ACT-R Literature on Selective vs. Blanket Reinforcement

The HM's concern (#5) and the logic critic's non-sequitur (#2) both flag the same problem: the session lifecycle reinforces every loaded chunk at every gate, regardless of whether the chunk was relevant to that gate.

**What ACT-R actually does.** In standard ACT-R, base-level learning increments activation through "presentations." The ACT-R Unit 4 tutorial is explicit about the mechanism:

> "Just retrieving the chunk and placing it into the retrieval buffer is not enough to count as a presentation. A production that fires must reference the retrieval buffer while that chunk is in the buffer to count as a presentation."

This is a critical distinction. In ACT-R:
- A chunk is reinforced only when it is **actively used by a production rule** — not merely when it is present in working memory.
- Multiple productions referencing the same chunk in the retrieval buffer produce multiple presentations.
- A chunk that is retrieved but never referenced by a firing production gets **zero** presentations from that retrieval.

**The document's REINFORCE step is not standard ACT-R.** The pseudocode says "add trace N to each loaded chunk" at every gate. This treats loading into the prompt prefix as equivalent to retrieval-and-use. In ACT-R terms, this would be like incrementing base-level activation for every chunk in declarative memory that happens to be above threshold, regardless of whether any production actually used it. ACT-R does not do this.

The standard ACT-R mechanism is **selective**: only chunks that are retrieved in response to a specific retrieval request, and then actively referenced by production rules, receive presentations. The document's mechanism is **broadcast**: every loaded chunk receives a trace at every gate.

**Relevant literature on the distinction:**

The Nuxoll & Laird work on Soar episodic memory is instructive here. When Nuxoll added ACT-R-inspired activation to Soar's working memory, the activation of working memory elements was "increased whenever tested by a rule, indicating importance to current processing" (Nuxoll & Laird, 2012). The key phrase is "tested by a rule" — activation increases are tied to actual use, not mere presence. This mirrors ACT-R's production-referenced presentation counting.

Anderson & Lebiere (1998, Chapter 4) are clear that the base-level learning equation tracks **accesses** — specific retrievals of a chunk in response to a need. The entire rational analysis framework rests on the assumption that past accesses predict future need. Broadcasting traces to all loaded chunks breaks this assumption: the traces no longer reflect need-based access patterns but loading-based co-occurrence patterns.

**The HM's rich-get-richer concern is well-founded.** If 30 chunks are loaded at session start and each receives a trace at every gate (say 5 gates per session), each loaded chunk accumulates 5 traces per session regardless of relevance. Over 10 sessions, that is 50 traces for chunks that were loaded (because they were already highly activated) vs. 1-2 traces for newer chunks. The activation gap compounds exponentially via the base-level equation.

**Possible fixes:**
1. **Remove the REINFORCE step entirely.** Chunks get traces only on creation (rule 1) and retrieval (rule 2). Loading into the prompt prefix is not retrieval — it is context setting. This matches standard ACT-R.
2. **Selective reinforcement.** Only reinforce chunks that the LLM actually references in its reasoning output. This requires parsing the LLM's response to identify which memories it used — feasible but adds complexity.
3. **Attenuated reinforcement.** Apply a fractional trace (e.g., 0.2x) for loaded-but-not-retrieved chunks, vs. a full trace for actively retrieved chunks. This acknowledges that presence in context has some reinforcement value while avoiding the broadcast problem.

Option 1 is the cleanest and most faithful to ACT-R. The chunks that matter will be retrieved by the retrieval function at future gates, earning their traces through actual use. Chunks that were loaded but irrelevant will decay naturally.

**Sources:**
- [ACT-R Unit 4 Tutorial — presentation counting](http://act-r.psy.cmu.edu/wordpress/wp-content/themes/ACT-R/tutorials/unit4.htm)
- [Nuxoll & Laird (2012), "Enhancing Intelligent Agents with Episodic Memory"](https://www.sciencedirect.com/science/article/abs/pii/S1389041711000428)
- [Anderson & Lebiere (1998), *The Atomic Components of Thought*](https://www.semanticscholar.org/paper/The-Atomic-Components-of-Thought-Anderson-Lebiere/084da26797ebaa448bab831eddabf50a96f4fe59)

---

## 5. Origin of the Fabricated Author Names

The fabrication pattern deserves documentation to prevent recurrence.

**"Nuxoll & West (2024)"** — Andrew Nuxoll is a real researcher (University of Michigan / Pacific University) who published extensively on episodic memory in cognitive architectures (Nuxoll & Laird, AAAI 2007; Nuxoll & Laird, Cognitive Systems Research, 2012). His work added ACT-R-inspired activation decay to Soar's episodic memory, making him topically adjacent to the Honda et al. paper. The round-1 researcher mentioned the HAI paper alongside ACT-R episodic memory concepts without providing full author names. The synthesist appears to have (a) associated "Nuxoll" with ACT-R agent memory work, (b) fabricated "West, R." as a plausible co-author name, and (c) backdated HAI '25 to HAI '24. This is a classic confabulation: real name from the right domain, attached to the wrong paper.

**"Bhatia, S. et al. (2026)"** — Sudeep Bhatia is a real researcher at the University of Pennsylvania who publishes on cognitive models of decision-making, including work connecting language models to psychological theories. His name is topically plausible for a paper about LM embeddings in ACT-R. The synthesist fabricated the attribution, replacing the actual first author (Meghdadi) with a more recognizable name from the cognitive-modeling-meets-LLM space.

**Both fabrications share a pattern:** the synthesist had correct paper titles and venues (from the round-1 researcher's notes and URLs) but did not have or did not verify the author names. Instead of admitting uncertainty, it generated plausible-sounding author names from its training data. The round-1 researcher provided URLs for both papers but did not spell out full author lists — the synthesist should have flagged the missing information rather than inventing it.

**Prevention:** Future synthesis rounds should never introduce author names that were not present in the researcher's notes or directly copied from a verified source URL. When a citation needs to be added, the researcher should provide the complete citation (all authors, year, title, venue) and the synthesist should copy it verbatim.

---

## Summary

| Issue | Finding | Action |
|-------|---------|--------|
| Honda et al. citation | Authors fabricated, year wrong. Correct: Honda, Fujita, Zempo, & Fukushima (2025), HAI '25. Paper strongly supports the claims. | Fix author names and year in all documents. |
| Meghdadi et al. citation | First author fabricated. Correct: Meghdadi, Duff, & Demberg (2026). Paper is psycholinguistics, not agent memory. | Fix author name; revise description to note psycholinguistics focus and that the relevance is the embedding-as-association-metric pattern. |
| Park et al. citation | Correct on substance. Minor formatting: "Park, J.S." preferred over "Park, S." | Minor fix only. |
| REINFORCE broadcast | Not standard ACT-R. ACT-R reinforces only on production-referenced retrieval, not blanket loading. Creates rich-get-richer feedback loop. | Remove the REINFORCE step from the session lifecycle; rely on creation and retrieval traces only (standard ACT-R). |
| Fabrication pattern | Both fabricated names are real researchers from adjacent domains, not random strings. Classic confabulation from topical association. | Establish citation hygiene: synthesist copies researcher-provided citations verbatim; never generates author names. |
