---
name: research
description: Deep multi-level academic and technical research. Use when asked to research a topic, conduct a literature review, survey a field, or gather background material for a paper.
argument-hint: [topic or research question]
user-invocable: true
---

# Deep Research

You are conducting deep, multi-level research suitable as background material for a research paper, design decision, or literature review. This skill provides the protocol; you provide the judgment.

The research scripts are in `scripts/research/`. The output goes to `docs/research/<project-slug>/`.

## Phase 1: Scope & Strategy

**Goal**: Know what you are researching, why, and how you will search.

1. Parse the research topic. Identify the core question and 2-4 adjacent areas worth exploring (these are your serendipity vectors — fields that might yield unexpected connections).
2. Create the project directory:
   ```bash
   mkdir -p docs/research/<project-slug>/papers docs/research/<project-slug>/analysis
   ```
3. Write `docs/research/<project-slug>/README.md` with: research question, scope (what is in, what is out), target depth, and initial search strategy.
4. Initialize `sources.json` as an empty JSON array:
   ```bash
   echo '[]' > docs/research/<project-slug>/sources.json
   ```
5. Initialize the research index:
   ```bash
   python3 scripts/research/research_indexer.py \
     --db docs/research/<project-slug>/.research.db \
     --init
   ```
6. Identify 5-8 seed search queries spanning:
   - 3-4 **core queries**: the research question phrased different ways, key terminology
   - 1-2 **methodology queries**: the methods or approaches relevant to the topic
   - 1-2 **serendipity seeds**: deliberately broad or cross-domain queries (e.g., if researching "agent memory," a serendipity seed might be "biological memory consolidation" or "organizational knowledge management")

**Output**: `README.md` written, empty `sources.json`, database initialized, seed queries listed.

## Phase 2: Broad Search (Level 0)

**Goal**: Cast a wide net. Find the landscape of existing work.

**Budget**: Up to 30 papers.

1. **arXiv search** — run for each relevant seed query:
   ```bash
   python3 scripts/research/fetch_arxiv.py \
     --query "<seed query>" \
     --max-results 20 \
     --output docs/research/<slug>/papers/ \
     --registry docs/research/<slug>/sources.json
   ```
2. **Semantic Scholar search** — run for each relevant seed query:
   ```bash
   python3 scripts/research/fetch_semantic_scholar.py \
     search --query "<seed query>" \
     --min-citations 5 \
     --max-results 20 \
     --output docs/research/<slug>/papers/ \
     --registry docs/research/<slug>/sources.json
   ```
3. **Cutting-edge sources** — use WebSearch to find:
   - Reddit discussions (r/MachineLearning, r/LocalLLaMA, r/compsci, or domain-specific subreddits)
   - Hacker News threads
   - Technical blogs (Lilian Weng, Simon Willison, Chip Huyen, or domain experts)
   - For each relevant find, use WebFetch to read the content, then create a paper entry markdown file with `source_type: "informal"`.
4. **Index the corpus**:
   ```bash
   python3 scripts/research/research_indexer.py \
     --db docs/research/<slug>/.research.db \
     --source docs/research/<slug>/papers/ \
     --registry docs/research/<slug>/sources.json
   ```
5. **Triage**: Read the abstracts (they're in the paper .md files). Identify thematic clusters. Note which papers appear most relevant, most cited, and most surprising.
6. Write `analysis/level-0-survey.md`: thematic clusters, most-cited papers, surprising finds, clear gaps, and which papers to deep-read.

**Output**: 20-30 papers indexed, `level-0-survey.md` written.

## Phase 3: Deep Reading

**Goal**: Engage deeply with the best papers from Level 0.

Select 8-12 papers for deep reading based on: relevance to research question, citation count, recency, and coverage of different themes.

For each selected paper:

1. **Get full text** — if PDF is available:
   ```bash
   python3 scripts/research/extract_pdf.py \
     --url <pdf_url> \
     --output docs/research/<slug>/papers/<paper-id>-full.txt
   ```
   If no PDF, use WebFetch on the abstract page or HTML version.
2. **Update the paper's markdown file** (`papers/<paper-id>.md`):
   - Fill in the `## Notes` section: key findings, methods, limitations
   - Fill in the `## Relevance` section using the analysis framework (see [analysis-framework.md](analysis-framework.md)):
     - **Alignment**: How does this paper support or validate the research topic?
     - **Differences**: Where does it challenge or take a different approach?
     - **Extensions**: Ideas that could extend the research in new directions?
     - **Follow-ups**: Promising references or future work worth pursuing?
   - Note which references look promising for citation expansion.
3. **Re-index** after all updates:
   ```bash
   python3 scripts/research/research_indexer.py \
     --db docs/research/<slug>/.research.db \
     --source docs/research/<slug>/papers/ \
     --registry docs/research/<slug>/sources.json
   ```

**Output**: 8-12 papers deeply read with filled Notes and Relevance sections.

## Phase 4: Dependency Expansion (3 Levels)

**Goal**: Follow the citation graph outward, with decreasing budget at each level.

The key to avoiding exponential blowup: at each level, select a small number of the most promising papers to expand, not all.

### Level 1 (budget: 20 papers)

1. From the 8-12 deeply-read papers, identify the 5-6 most-cited references and the 3-4 most relevant citing papers.
2. Fetch their details:
   ```bash
   python3 scripts/research/fetch_semantic_scholar.py \
     references --paper-id <id> \
     --limit 50 \
     --discovery-level 1 \
     --output docs/research/<slug>/papers/ \
     --registry docs/research/<slug>/sources.json
   ```
   ```bash
   python3 scripts/research/fetch_semantic_scholar.py \
     citations --paper-id <id> \
     --limit 50 \
     --discovery-level 1 \
     --output docs/research/<slug>/papers/ \
     --registry docs/research/<slug>/sources.json
   ```
3. From the combined pool, select up to 20 new papers by relevance. Read abstracts and make a judgment call.
4. Write brief notes for selected papers. Write `analysis/level-1-expansion.md`.

### Level 2 (budget: 15 papers)

1. From Level 1's top papers, pick the 3-4 with the most informative reference lists.
2. Fetch references and citations as above (with `--discovery-level 2`).
3. Select up to 15 new papers. Focus on:
   - **Foundational work**: High citation count, older papers that define the field
   - **Very recent work**: Last 12 months, may not have many citations yet
4. Write `analysis/level-2-expansion.md`.

### Level 3 (budget: 10 papers)

1. From Level 2, pick the 2-3 papers that opened genuinely new directions.
2. Fetch and select up to 10 papers (with `--discovery-level 3`).
3. At this depth, the **serendipity mechanism** activates strongly:
   - Look for papers highly cited but in a **different field** than expected
   - Look for papers that cite your Level 0 papers alongside something unexpected
   - Look for convergence: papers that appear in multiple citation chains independently
4. Write `analysis/level-3-expansion.md`.

### After all levels

Re-index the full corpus:
```bash
python3 scripts/research/research_indexer.py \
  --db docs/research/<slug>/.research.db \
  --source docs/research/<slug>/papers/ \
  --registry docs/research/<slug>/sources.json
```

Check corpus stats:
```bash
python3 scripts/research/research_indexer.py \
  --db docs/research/<slug>/.research.db \
  --stats
```

**Output**: 45-75 papers indexed across 4 levels, level analysis files written.

## Phase 5: Synthesis & Analysis

**Goal**: Produce actionable research output.

1. **Thematic retrieval** — query the index for cross-cutting themes:
   ```bash
   python3 scripts/research/research_indexer.py \
     --db docs/research/<slug>/.research.db \
     --query "<theme>" \
     --top-k 10
   ```
2. Write `synthesis.md` containing:
   - **Thematic clusters**: Group papers by approach, finding, or methodology
   - **Alignment**: Which papers directly support the research question — and how?
   - **Differences**: Which papers challenge or contradict the thesis — and what can we learn?
   - **Extensions**: Ideas that extend the research in new directions — ranked by promise
   - **Gaps**: What the literature does NOT cover — these are opportunities
   - **Follow-up opportunities**: Specific next steps worth pursuing
   - **Serendipitous connections**: Unexpected links between fields or ideas
3. Write `bibliography.md` with formatted citations for all papers, organized by theme. This is direct input to the [write-paper skill](../write-paper/SKILL.md).
4. Update `docs/research/INDEX.md` with an entry for this research project.

**Output**: Complete research package ready for paper writing or design decisions.

## Principles

- **Judgment over exhaustiveness.** You are not trying to find every paper — you are trying to find the right ones. 75 well-chosen papers beat 500 unread ones.
- **Serendipity is structural, not random.** The skill deliberately includes cross-domain search terms, adjacent-field citation following, and a serendipity log. This isn't chance — it's designed divergent thinking.
- **The index outlives the session.** Everything persists to disk: the SQLite index, the paper markdown files, the analysis. Future sessions can query the index and build on the research.
- **Source quality matters.** See [search-strategy.md](search-strategy.md) for how to evaluate different source types. Peer-reviewed > preprint > blog post, but a timely blog post can be more valuable than an outdated journal article.
- **Don't summarize — analyze.** The Notes and Relevance sections should be analytical, not just summaries. What does this paper mean for the research question?
