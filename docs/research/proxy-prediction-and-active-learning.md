# Research: Proxy Prediction, Active Learning, and Preference Calibration

This file documents peer-reviewed and authoritative research on systems where an agent learns to predict human responses, uses prediction errors as a learning signal, and calibrates its confidence to determine when to ask versus when to predict. The design problem is: a proxy agent forms explicit predictions about how a human will answer intake questions, compares those predictions against actual answers, and uses the delta (prediction error) as its primary learning signal — gradually asking fewer questions as predictions improve.

This is distinct from the existing `human-proxy-agent-design.md`, which covers EMA confidence tracking, escalation thresholds, and dialog pattern learning. This file focuses on the prediction-formation and calibration layer.

---

## Scope

Five research areas are covered, roughly in order of implementation tractability for the TeaParty use case:

1. Bayesian Preference Models (most directly applicable, small-data capable)
2. Active Learning / Uncertainty Sampling (question-selection strategies)
3. Instance-Based and Cognitive Architectures (learn-from-episodes approaches)
4. Preference Learning and RLHF (large-scale approaches with relevant concepts)
5. Calibrated Uncertainty Quantification (conformal and Bayesian methods)
6. Practical Systems: Generative Agent Simulation and Personalized LLMs

---

## 1. Bayesian Preference Models

### Gaussian Process Preference Learning (Chu & Ghahramani, 2005)

- **Venue:** Proceedings of the 22nd International Conference on Machine Learning (ICML 2005)
- **URL:** https://dl.acm.org/doi/10.1145/1102351.1102369
- **PDF:** https://icml.cc/Conferences/2005/proceedings/papers/018_Preference_ChuGhahramani.pdf
- **Key findings:**
  - Foundational method for learning a latent utility function from pairwise preference comparisons using Gaussian processes.
  - GPs provide principled uncertainty estimates at every point — high variance where data is sparse, low variance where data is dense.
  - This is the critical property: uncertainty quantification is built into the model, not bolted on. Cold start = high uncertainty = ask. Warm model = low uncertainty = predict.
  - The GP posterior automatically narrows as observations accumulate — no manual recalibration required.
  - O(N^3) complexity is manageable at the 5-50 observation scale targeted by TeaParty.
- **Implications for TeaParty:** The GP provides exactly the mathematical structure the proxy needs: a model that represents what it knows and how confident it is, with confidence derived directly from how many similar observations it has seen. With zero observations on a question type, variance is at prior level (escalate). After 10-20 consistent observations, variance has narrowed enough to predict reliably. The pairwise framing can be adapted to scalar predictions.
- **Evidence strength:** Foundational paper, heavily cited, well-established. Not just theoretical — implementations exist (PrefGP Python library).

---

### A Tutorial on Learning from Preferences and Choices with Gaussian Processes (Benavoli et al., 2024)

- **Venue:** arXiv preprint (2024). Peer-reviewed versions of constituent methods are published.
- **URL:** https://arxiv.org/html/2403.11782v1
- **Key findings:**
  - GPs have "a small number of tunable hyperparameters (and so they can be trained on small datasets)."
  - The nonparametric nature allows model complexity to "automatically grow as more data are observed" — sample-efficient by design.
  - Nine distinct preference learning models are covered; includes the linear elliptical slice sampler for rejection-free Bayesian inference.
  - GPs achieve "exact interpolation, essential for modelling the utility function of a rational subject" — this matters for individual preference learning where you want to interpolate specific past answers, not average over a population.
  - PrefGP Python library implements all nine models.
- **Implications for TeaParty:** This is the practical implementation guide for GP preference learning. The exact interpolation property means the proxy will correctly reproduce known answers and interpolate on adjacent question types. The small-hyperparameter-count property means the model can fit from 5-20 observations without overfitting.
- **Evidence strength:** Pre-print tutorial, but the underlying methods are peer-reviewed. PrefGP exists as a working implementation.

---

### Active Preference-Based Gaussian Process Regression for Reward Learning (Biyik, Huynh, Kochenderfer & Sadigh, 2024)

- **Venue:** The International Journal of Robotics Research, 2024 (originally arXiv:2005.02575, 2020)
- **URL:** https://journals.sagepub.com/doi/10.1177/02783649231208729
- **ResearchGate PDF:** https://www.researchgate.net/publication/375481888_Active_preference-based_Gaussian_process_regression_for_reward_learning_and_optimization
- **Key findings:**
  - Combines GP preference learning with active query selection: the system asks the most informative question next, not a random one.
  - The active query strategy uses the GP's posterior uncertainty to identify which question would most reduce overall uncertainty — analogous to BALD (see section 2) but operating directly on the preference space.
  - Pairwise comparisons provide at most 1 bit per query, making active selection critical for sample efficiency.
  - Extends to batch-active methods, choice queries (not just pairwise), and online interactive settings.
  - Has been demonstrated in robotics (learning human driving preferences, physical assistance preferences) with small query counts — typically 10-30 queries to reach reliable predictions.
- **Implications for TeaParty:** This paper shows the GP + active query selection combination has been implemented and validated in real human-facing systems. The 10-30 query count to reach reliable predictions aligns with the 5-50 observation budget. The query selection criterion — pick the question with highest predictive uncertainty — directly implements the "ask when uncertain, predict when confident" behavior the proxy needs.
- **Evidence strength:** High. Peer-reviewed in a top robotics journal; demonstrated on real human subjects.

---

### Beta-Bernoulli Bayesian Updating (classical statistical method)

- **Primary reference:** Greg Gundersen's tutorial: https://gregorygundersen.com/blog/2020/08/19/bernoulli-beta/
- **Key findings:**
  - For binary predictions (yes/no, agrees/disagrees), the Beta-Bernoulli conjugate pair is the simplest Bayesian model.
  - Prior: Beta(alpha, beta) where alpha and beta are pseudo-counts of successes and failures.
  - Update rule: after observing a success, new prior is Beta(alpha+1, beta). After a failure: Beta(alpha, beta+1).
  - Posterior mean (best prediction): alpha / (alpha + beta). Posterior variance (uncertainty): decreases with every observation.
  - Cold start = Beta(1,1) (uniform, maximum uncertainty). After 5 correct predictions: Beta(6,1), mean=0.86, much narrower interval.
  - The update rule is just addition — trivially implementable with no libraries.
- **Implications for TeaParty:** For binary or categorical questions, Beta-Bernoulli is the lowest-complexity Bayesian approach. Each question type gets its own (alpha, beta) pair. When posterior variance is above a threshold, ask. When below, predict. This requires no ML infrastructure and works immediately from the first observation. It does not generalize across question types (no shared latent structure), but it is the right tool for isolated binary questions where generalization is not needed.
- **Evidence strength:** Classical statistical method, mathematically proven, implemented in every statistics library.

---

## 2. Active Learning / Uncertainty Sampling

### Active Learning Literature Survey (Settles, 2009)

- **Venue:** University of Wisconsin–Madison Technical Report 1648. Widely cited as the canonical survey.
- **URL:** https://burrsettles.com/pub/settles.activelearning.pdf
- **Key findings:**
  - **Uncertainty sampling:** Query the example where the model is least confident. For binary predictions, this means querying when P(answer) is closest to 0.5. Implementation: track posterior probability of each answer; ask when it falls below a confidence threshold.
  - **Query-by-committee (QBC):** Maintain multiple hypotheses consistent with observed data; ask when the committee disagrees most. Disagreement = epistemic uncertainty = the question is still open.
  - **Expected model change:** Ask the question that would, if answered, change the model's predictions most. Related to BALD and EPIG (see below).
  - **Information gain:** Ask the question that maximally reduces entropy of the model's belief state.
  - All four strategies collapse to the same intuition: ask when uncertain, skip when confident.
- **Implications for TeaParty:** Settles provides the vocabulary and taxonomy for the proxy's question-selection logic. The simplest implementable version is uncertainty sampling with a threshold: if the proxy's predicted probability for a question is > 0.85, skip asking; if <= 0.85, ask. QBC is more robust but requires maintaining a committee (e.g., 5 plausible preference profiles), which may be the right approach as the model grows.
- **Evidence strength:** Canonical survey, written by the field's primary authority. The strategies are well-validated across many domains.

---

### Understanding Uncertainty Sampling (Nguyen & Huynh, 2023)

- **Venue:** arXiv:2307.02719 (2023). Under review at ICML.
- **URL:** https://arxiv.org/abs/2307.02719
- **Key findings:**
  - Provides theoretical generalization bounds for uncertainty sampling — the first formal guarantee that uncertainty sampling leads to better generalization than random sampling.
  - Shows uncertainty sampling achieves near-optimal label complexity: the number of labels needed to reach a target accuracy is provably sublinear compared to passive learning.
  - Works with calibrated models (where confidence scores match true accuracy). Miscalibration (common in neural networks) degrades the guarantees.
- **Implications for TeaParty:** This provides the theoretical grounding that asking uncertain questions is not just heuristically sensible — it is provably optimal for sample efficiency. The calibration requirement is important: the proxy must track actual accuracy of predictions, not just reported confidence. In practice, for the small-N regime, Bayesian methods (GPs, Beta-Bernoulli) are naturally well-calibrated, while neural network-based approaches may require explicit calibration.
- **Evidence strength:** Recent peer-reviewed preprint at a top venue. Single paper, not a meta-analysis, but formal guarantees are meaningful.

---

### BALD: Bayesian Active Learning by Disagreement (Houlsby et al., 2011; reviewed 2023)

- **Venue:** arXiv:1112.5745 (2011); extensively cited since.
- **URL:** https://arxiv.org/pdf/1112.5745
- **Accessible review:** https://ozanciga.wordpress.com/2023/10/29/bald-bayesian-active-learning-by-disagreements-simplified/
- **Key findings:**
  - BALD selects queries that maximize mutual information between the answer and the model parameters: I(y; theta | x, D).
  - Operationally: query the input where the overall prediction entropy is high but individual model samples are confident — meaning the model has strong but conflicting hypotheses.
  - Two entropy measures: H[y|x,D] (total uncertainty) minus E[H[y|x,theta,D]] (aleatoric uncertainty). The difference is epistemic uncertainty — what the model could resolve by seeing more data.
  - BALD naturally handles cold start: with no data, all queries have high epistemic uncertainty. As data accumulates, epistemic uncertainty drops and BALD stops querying.
- **Implications for TeaParty:** BALD gives a principled information-theoretic criterion for the ask/skip decision. Questions with high BALD score have high expected information value — answering them would significantly update the proxy's model. Questions with low BALD score are already well-predicted — no need to ask. This is a mathematically grounded version of the intuition the proxy needs. The implementation requires a probabilistic model (GP or Bayesian neural network), but the criterion itself is model-agnostic.
- **Evidence strength:** Established method, widely implemented. Significant body of applied work shows it works in practice.

---

### Expected Predictive Information Gain (EPIG) (Bickford Smith et al., 2023)

- **Venue:** AISTATS 2023
- **URL:** https://proceedings.mlr.press/v206/bickfordsmith23a/bickfordsmith23a.pdf
- **Overview:** https://www.emergentmind.com/topics/expected-predictive-information-gain-epig
- **Key findings:**
  - EPIG improves on BALD by conditioning on the actual deployment distribution rather than maximizing global parameter uncertainty.
  - BALD can select "outlier" questions that are informative about the model globally but irrelevant for the types of questions the proxy will actually encounter.
  - EPIG asks: "How much does this question's answer reduce uncertainty about the *specific* questions I will need to answer in the future?"
  - Empirically demonstrated to yield superior predictive performance compared to BALD on non-curated query pools.
- **Implications for TeaParty:** EPIG is the more practically useful criterion when the proxy has a known distribution of future questions. For intake dialogs, the proxy knows roughly what question types will appear — so it can optimize queries specifically for those question types. This is strictly better than BALD for the proxy use case. However, EPIG requires knowing the future query distribution; simpler uncertainty sampling or BALD may be adequate for initial implementation.
- **Evidence strength:** Single AISTATS 2023 paper. Recent but peer-reviewed at a top venue. Implementation details are available.

---

### A Comprehensive Benchmark of Active Learning for Small-Sample Regression (Dunn et al., 2025)

- **Venue:** Scientific Reports (Nature portfolio), 2025
- **URL:** https://www.nature.com/articles/s41598-025-24613-4
- **Key findings:**
  - Benchmarks multiple active learning strategies on small-sample regression tasks (10-100 initial samples).
  - Uncertainty sampling (entropy or margin) consistently outperforms random selection in the small-sample regime.
  - QBC with committee size 4 and initial sample size of 50 was empirically optimal for a regression application.
  - Committees initialized on fewer than 15 samples exhibited poor performance throughout — this is the empirical cold-start floor.
  - Key practical finding: active learning advantages are largest in the 10-50 observation range, exactly the regime targeted by TeaParty.
- **Implications for TeaParty:** Provides empirical evidence that active learning advantages are real and significant in the 5-50 observation range. The finding that committees need at least 15 samples before becoming useful aligns with a cold-start threshold around n=15 for committee-based approaches (while simpler Bayesian approaches like Beta-Bernoulli work immediately from n=1).
- **Evidence strength:** Peer-reviewed in Scientific Reports. Single study on one domain; general principles likely transfer but specific numbers may not.

---

## 3. Instance-Based Learning and Cognitive Architectures

### Instance-Based Learning in Dynamic Decision Making (Gonzalez, Lerch & Lebiere, 2003)

- **Venue:** Cognitive Science, 27(4), 591–635, 2003
- **URL:** https://onlinelibrary.wiley.com/doi/abs/10.1207/s15516709cog2704_2
- **ResearchGate:** https://www.researchgate.net/publication/222556226_Instance-based_learning_in_dynamic_decision_making
- **Key findings:**
  - Instance-Based Learning Theory (IBLT) proposes that humans make decisions by storing (situation, decision, utility) triplets and retrieving the most similar past instance when facing a new decision.
  - Memory retrieval is governed by an activation function from ACT-R: activation increases with recency and frequency, decays over time, and is boosted by similarity to the current situation.
  - The "blending" mechanism averages the utilities of retrieved instances weighted by activation — producing a graded prediction rather than a binary lookup.
  - Cold start in IBLT: no instances = rely on a "default" action or random exploration. First few instances = high variance predictions. After 5-10 instances = predictions stabilize.
  - Computationally validated against human decision-making data in multiple experimental paradigms.
- **Implications for TeaParty:** IBLT describes exactly the cognitive mechanism the proxy is implementing: store observed (question, human-answer) pairs and retrieve them by similarity when predicting future answers. The activation function provides a principled weighting of instances — recent answers about a particular topic outweigh older ones, consistent with preference drift. The blending mechanism gives a continuous prediction (not just nearest-neighbor lookup) and naturally expresses uncertainty when retrieved instances disagree. This is a cognitively-grounded, small-data-compatible approach that requires no ML infrastructure.
- **Evidence strength:** High. Published in a top cognitive science journal; validated experimentally; implemented in SpeedyIBL (see below).

---

### SpeedyIBL: A Comprehensive, Precise, and Fast Implementation of Instance-Based Learning Theory (Nguyen et al., 2022)

- **Venue:** Behavior Research Methods, 2022
- **URL:** https://link.springer.com/article/10.3758/s13428-022-01848-x
- **arXiv version:** https://arxiv.org/abs/2111.10268
- **Key findings:**
  - Python library implementing the full IBLT mechanism: activation, blending, noise, decay.
  - Handles both individual and multi-agent decision-making scenarios.
  - Demonstrated to be "very successful in explaining and predicting human decisions in multiple decision-making contexts."
  - Provides prediction power "without a heavy reliance on data" — IBL models can generalize from small N.
  - Key parameter: decay rate (d) controls how quickly old instances lose influence. High d = recent instances dominate (good for volatile preferences). Low d = long memory (good for stable preferences).
- **Implications for TeaParty:** SpeedyIBL is an off-the-shelf Python implementation of IBLT that the proxy could use directly. The decay parameter allows tuning how quickly old observations are discounted — a natural fit for preference drift. The library handles the blending computation automatically, producing predictions with associated confidence (variance of blended utilities).
- **Evidence strength:** Peer-reviewed in a methods journal; library is publicly available on GitHub.

---

## 4. Preference Learning and RLHF (Large-Scale Approaches with Relevant Principles)

### RLHF Deciphered: A Critical Analysis of RLHF for LLMs (Casper et al., 2023)

- **Venue:** ACM Computing Surveys, 2023
- **URL:** https://dl.acm.org/doi/full/10.1145/3743127
- **Key findings:**
  - RLHF reward models are trained on pairwise preference data. Each comparison gives a noisy sample of an underlying latent preference structure.
  - Critical limitation for TeaParty: reward models average over annotators, producing "rewards inconsistent with any single human's preferences." RLHF is designed for population-level preference learning, not individual-level.
  - Uncertainty-aware reward models that abstain or give conservative estimates when far from training data are an active research direction.
  - Cold start is a known problem: reward models need hundreds to thousands of comparisons to be reliable.
- **Implications for TeaParty:** RLHF is explicitly NOT the right approach for single-individual preference learning. It requires too much data, averages over individuals, and does not naturally produce calibrated uncertainty for individual questions. However, the RLHF framing clarifies what the proxy is doing differently: it is learning a single person's reward function (not a population's), requiring far fewer observations, and it needs individual-level rather than population-level calibration.
- **Evidence strength:** High. ACM Computing Surveys is a premier review venue.

---

### Direct Preference Optimization (Rafailov et al., 2023)

- **Venue:** NeurIPS 2023
- **URL:** https://arxiv.org/abs/2305.18290
- **Key findings:**
  - DPO eliminates the explicit reward model by reparameterizing preference learning directly in the LLM weights via a classification loss over (chosen, rejected) response pairs.
  - Significantly simpler than RLHF; demonstrated on summarization and dialogue.
  - Requires large datasets (thousands of pairs). Not a small-data approach.
  - Cal-DPO (NeurIPS 2024) extends DPO with explicit calibration, addressing the known miscalibration issue in standard DPO.
- **Implications for TeaParty:** DPO is architecturally incompatible with the proxy's design — the proxy is not fine-tuning an LLM; it is building an explicit prediction model per question type. However, DPO confirms the trend toward calibration as a first-class concern in preference learning, validating the proxy's emphasis on confidence tracking.
- **Evidence strength:** High for DPO itself (NeurIPS 2023). Cal-DPO is a recent extension.

---

### Deep Bayesian Active Learning for Preference Modeling in LLMs (Cao et al., NeurIPS 2024)

- **Venue:** NeurIPS 2024
- **URL:** https://neurips.cc/virtual/2024/poster/96611
- **PDF:** https://proceedings.neurips.cc/paper_files/paper/2024/file/d5e256c988bdee59a0f4d7a9bc1dd6d9-Paper-Conference.pdf
- **Key findings:**
  - Combines Bayesian active learning (BALD-style query selection) with preference modeling for LLM alignment.
  - The Bayesian approach tracks uncertainty over the preference model and queries for the most informative next comparison.
  - Demonstrates that principled uncertainty-based query selection significantly reduces the number of human feedback examples needed.
  - Explicitly addresses the cold-start problem by initializing from a broad prior over possible preference functions.
- **Implications for TeaParty:** This is the most recent demonstration (NeurIPS 2024) that Bayesian active learning for preference models is practical and outperforms passive collection. The proxy is doing a simpler version of this: rather than learning a preference model for LLM outputs, it is learning a preference model for intake question answers. The core principle — Bayesian uncertainty + active query selection — transfers directly.
- **Evidence strength:** Single NeurIPS 2024 paper. Recent, peer-reviewed, directly relevant.

---

## 5. Calibrated Uncertainty Quantification

### A Gentle Introduction to Conformal Prediction and Distribution-Free Uncertainty Quantification (Angelopoulos & Bates, 2021)

- **Venue:** arXiv:2107.07511. A revised version appeared in Journal of Machine Learning Research.
- **URL:** https://arxiv.org/abs/2107.07511
- **Key findings:**
  - Conformal prediction produces uncertainty intervals (prediction sets) with guaranteed coverage — if the true confidence level is set to 90%, the interval will contain the true answer 90% of the time, regardless of the underlying model.
  - Crucially, this guarantee is distribution-free and non-asymptotic: it holds with any sample size, not just in the large-N limit.
  - The only requirement is exchangeability of the calibration data — a very mild assumption.
  - Works with any base predictor (neural network, GP, simple heuristic) as a wrapper.
- **Implications for TeaParty:** Conformal prediction is the right tool for the proxy's calibration layer if it needs to provide *guaranteed* confidence bounds rather than estimated ones. The proxy can wrap any prediction model (even a simple frequency estimate) with conformal prediction to get calibrated intervals. In the cold-start regime, conformal intervals will be wide (appropriately uncertain). As observations accumulate, intervals narrow. The non-asymptotic property means this is valid even at n=5, unlike frequentist confidence intervals which require large N for coverage guarantees.
- **Evidence strength:** High. This is a foundational reference for the conformal prediction field; widely cited and the method is mathematically proven.

---

### Conformal Prediction for Natural Language Processing: A Survey (Giovannotti, 2024)

- **Venue:** Transactions of the Association for Computational Linguistics (TACL), 2024
- **URL:** https://aclanthology.org/2024.tacl-1.82.pdf
- **Key findings:**
  - Surveys applications of conformal prediction to NLP tasks including text classification, question answering, and dialogue.
  - Shows conformal prediction can be applied to any model that produces a probability or confidence score.
  - "Inductive conformal prediction" (split conformal) is the practically efficient variant: calibrate on a held-out split, not on every test point.
  - The NLP context is directly relevant: the proxy's predictions about how a human will answer a question are NLP-adjacent tasks where conformal coverage guarantees are valuable.
- **Implications for TeaParty:** This is the most directly applicable survey for the proxy's setting. If the proxy formulates predictions using an LLM (asking the LLM to predict the human's answer), conformal prediction provides a way to convert the LLM's softmax probabilities into calibrated intervals that *actually* have the claimed coverage. This gives the proxy's confidence estimates statistical validity, not just intuitive plausibility.
- **Evidence strength:** Peer-reviewed survey in TACL, a top ACL venue.

---

## 6. Practical Systems: Generative Agent Simulation and Personalized LLMs

### Generative Agent Simulations of 1,000 People (Park et al., 2024)

- **Venue:** arXiv:2411.10109 (2024). Led by Joon Sung Park (Stanford); collaborators from Northwestern, UW, Google DeepMind.
- **URL:** https://arxiv.org/abs/2411.10109
- **Key findings:**
  - Built AI agents representing 1,052 real individuals using qualitative interviews as the sole data source.
  - Two-hour qualitative interviews with pre-specified and adaptive follow-up questions were the data collection mechanism.
  - Agents replicated survey responses with 85% accuracy compared to participants' own test-retest reliability.
  - Matched personality assessments with 80% accuracy; economic game behavior with 66% accuracy.
  - Key design insight: using interview content rather than demographic labels as the representation significantly reduced accuracy biases across racial and ideological groups.
  - The interview-to-agent pipeline does not involve explicit prediction training — it uses the interview transcript as in-context memory for the LLM.
- **Implications for TeaParty:** This is the most direct empirical demonstration that (a) a single structured interview can produce a model that predicts human responses with ~85% accuracy, and (b) the interview content is more valuable than demographic proxies. The proxy's intake dialog is performing the same function. However, the Park et al. approach uses LLM in-context reasoning, not an explicit prediction model — the proxy is doing something more structured. The 85% accuracy figure sets a realistic target and confirms that individual-level response prediction is achievable from conversational data.
- **Evidence strength:** Pre-print (November 2024), not yet peer-reviewed. High visibility; Stanford/Google DeepMind. Treat as strong preliminary evidence.

---

### PersonalLLM: Tailoring LLMs to Individual Preferences (Kumar et al., ICLR 2025)

- **Venue:** ICLR 2025
- **URL:** https://openreview.net/forum?id=2R7498e2Tx
- **PDF:** https://proceedings.iclr.cc/paper_files/paper/2025/file/a730abbcd6cf4a371ca9545db5922442-Paper-Conference.pdf
- **Key findings:**
  - Introduces a benchmark for adapting LLMs to individual user preferences, explicitly acknowledging that "users display heterogeneous latent preferences."
  - The benchmark tests personalization algorithms under "continual data sparsity — few relevant feedback from the particular user."
  - PREF method (in related work): models each user's personalized reward function as a linear combination of shared base reward functions learned via matrix factorization. Can infer a new user's weights with ~10 feedback examples.
  - Uses historical data from similar users to bootstrap cold start — a population prior that narrows as individual data accumulates.
  - In-context learning baselines show that even without fine-tuning, retrieval of past user examples improves alignment.
- **Implications for TeaParty:** PersonalLLM makes cold start manageable by initializing from population-level patterns. The proxy could do the same: learn a prior distribution over preference profiles from past users (or from similar question types), then update toward the specific individual's profile as intake answers arrive. The PREF method's ~10 example requirement aligns well with the 5-50 target range.
- **Evidence strength:** ICLR 2025 (peer-reviewed, top venue). Single paper on a benchmark; specific PREF numbers need independent replication.

---

### Few-Shot Personalization of LLMs with Mis-aligned Responses — Fermi (Salemi et al., 2024)

- **Venue:** arXiv:2406.18678 (2024). Under review.
- **URL:** https://arxiv.org/abs/2406.18678
- **Key findings:**
  - Fermi learns personalized prompts by iteratively improving them using LLMs, based on user profile and a few examples of previous opinions.
  - Key insight: misaligned responses (where the LLM predicted incorrectly) are "especially crucial for effective personalization." The delta / prediction error is the most informative training signal — not just the correct cases.
  - The approach uses a small number of examples ("few-shot") and explicitly leverages failure cases.
  - Addresses cold start via demographic information as an initial proxy.
- **Implications for TeaParty:** Fermi directly validates the design premise that prediction errors are the primary learning signal. The paper confirms empirically what the proxy's architecture assumes: misaligned predictions (high delta) drive learning more efficiently than correct predictions. The proxy's delta-based learning is aligned with current best practices in personalization research.
- **Evidence strength:** Pre-print (2024). Under review. Single study; treat as preliminary confirmation of the delta-as-learning-signal principle.

---

### Training Proactive and Personalized LLM Agents — PPP (Sun et al., 2025)

- **Venue:** arXiv:2511.02208 (2025)
- **URL:** https://arxiv.org/abs/2511.02208
- **Key findings:**
  - PPP (Productivity, Proactivity, Personalization) jointly optimizes three objectives for LLM agents, including asking strategic clarifying questions and adapting to unseen user preferences.
  - "Ask strategic clarifying questions" is trained as an explicit behavior — the system learns when asking is more valuable than acting.
  - UserVille simulation environment with configurable user preference profiles used for training.
  - Key finding: explicitly optimizing for proactive questioning (knowing when to ask vs. predict) is critical for practical agent performance. Systems not trained on this objective ask too often or too rarely.
- **Implications for TeaParty:** This confirms that the act-or-ask decision is non-trivial and needs to be trained or calibrated, not just hardcoded. The proxy's threshold-based ask/predict logic is the right architectural pattern; the PPP findings suggest the threshold should be learned from interaction, not set statically.
- **Evidence strength:** Pre-print (2025). Related work, not a direct implementation reference.

---

## 7. Synthesis: Selecting Approaches for TeaParty's Proxy

The design problem has three sub-problems:
1. **Forming predictions:** What will the human answer?
2. **Calibrating confidence:** How confident is the prediction?
3. **Regulating questions:** When to ask vs. predict?

The table below maps research to each sub-problem and assesses fit for the 5-50 observation regime:

| Approach | Forms Predictions | Calibrated Confidence | Small Data (5-50) | Implementation Complexity | Demonstrated in Practice |
|----------|------------------|-----------------------|-------------------|-----------------------------|--------------------------|
| GP Preference Learning (Chu 2005; Benavoli 2024) | Yes (latent utility function) | Yes (posterior variance) | Yes — designed for this | Medium (GP inference, Python library available) | Yes (Biyik 2024 with real humans) |
| Beta-Bernoulli Bayesian Updating | Yes (binary/categorical) | Yes (posterior variance) | Yes — works at n=1 | Very low (no library needed) | Yes (classical statistics) |
| Instance-Based Learning / SpeedyIBL | Yes (blending of past instances) | Partially (variance of blended utilities) | Yes — designed for this | Low (library available) | Yes (Gonzalez 2003; multiple cognitive science studies) |
| BALD / Uncertainty Sampling | No (query selection only) | N/A | Yes | Low-medium | Yes (many applied domains) |
| Conformal Prediction | No (wrapper for calibration) | Yes (guaranteed coverage) | Yes — non-asymptotic | Low (wraps any predictor) | Yes (NLP survey, TACL 2024) |
| RLHF / DPO | Yes | Partially | No — needs thousands | High | Yes (LLM training) |
| QBC | Partially | Yes (committee disagreement) | Partially — needs ~15+ initial samples | Medium | Yes (many domains) |
| LLM in-context (Park 2024) | Yes | Partially | Yes (works from N=1 interview) | Low (uses existing LLM) | Yes (85% accuracy in practice) |

### Recommended architecture for TeaParty

The proxy's prediction-calibration system most naturally combines three elements:

1. **Beta-Bernoulli per question type** for cold start and simple binary/categorical questions. Works from the first observation. No infrastructure required. The posterior variance directly drives the ask/predict threshold.

2. **GP preference learning** once 10+ observations per question type are available and when the proxy needs to generalize across related question types (e.g., "how does this person's answer to question A predict their answer to question B?"). Use PrefGP Python library. GP posterior uncertainty drives the threshold.

3. **Uncertainty sampling threshold** (from Settles 2009 / Nguyen 2023) as the ask/predict decision rule. Ask when posterior predictive variance exceeds threshold_var; predict when below. The threshold can start conservative (lower variance required before predicting) and become permissive as calibration accuracy is confirmed.

The delta (prediction error) on each observed answer is the update signal for both Beta-Bernoulli (update pseudo-counts) and GP (add data point, recompute posterior). The key design requirement is that large deltas cause larger updates — which is automatic in Bayesian models (unexpected observations have high likelihood ratio, so they move the posterior more).

---

## References for Future Follow-Up

- **Bayesian audiometry using active learning** (Shen et al., 2021, PubMed): a medical domain where GP + BALD is used to learn individual auditory thresholds from ~15-20 questions. The closest structural analogy to the proxy's intake dialog. URL: https://pubmed.ncbi.nlm.nih.gov/34713188/
- **Ordered preference elicitation strategies** (Katz et al., 2018): strategies for ordering preference queries to maximize information while respecting cognitive load. arXiv:1802.07606.
- **Thompson Sampling for preference elicitation** (various): bandit algorithm naturally balances exploration (asking) vs. exploitation (predicting) without a fixed threshold. Tutorial: https://arxiv.org/abs/1707.02038.
