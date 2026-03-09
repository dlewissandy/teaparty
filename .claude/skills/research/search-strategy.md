# Search Strategy Reference

Guidance on searching effectively across different sources and evaluating what you find.

---

## arXiv Search Syntax

arXiv supports field-prefix queries:

| Prefix | Field | Example |
|--------|-------|---------|
| `ti:` | Title | `ti:agent memory` |
| `abs:` | Abstract | `abs:episodic retrieval` |
| `au:` | Author | `au:park` |
| `cat:` | Category | `cat:cs.AI` |
| `all:` | All fields | `all:multi-agent coordination` |

Boolean operators: `AND`, `OR`, `ANDNOT`

Example: `ti:agent memory AND cat:cs.AI ANDNOT ti:survey`

**Common categories**: `cs.AI` (Artificial Intelligence), `cs.CL` (Computation and Language), `cs.MA` (Multi-Agent Systems), `cs.LG` (Machine Learning), `cs.HC` (Human-Computer Interaction), `cs.SE` (Software Engineering)

---

## Semantic Scholar Search

Good for:
- Citation graph traversal (references and citations endpoints)
- Finding highly-cited foundational work
- Cross-disciplinary search (broader coverage than arXiv)

The `--min-citations` flag is useful for filtering noise during broad searches. Use higher thresholds for Level 2-3 expansion (e.g., `--min-citations 20`).

The `--year-range` flag (e.g., `--year-range 2024-2026`) is useful for finding very recent work that may not have many citations yet.

**Paper ID formats accepted**: `ARXIV:2505.07087`, `DOI:10.1234/...`, or Semantic Scholar corpus ID.

---

## Cutting-Edge Sources

These sources surface work before (or outside of) formal publication:

### Reddit
- **r/MachineLearning**: Paper discussions, often with author commentary
- **r/LocalLLaMA**: Practitioner insights on LLM deployment
- **r/compsci**: Broader computer science discussions
- **Domain-specific subreddits**: e.g., r/reinforcementlearning, r/neuroscience

### Hacker News
- Search `site:news.ycombinator.com "<topic>"` via WebSearch
- Comments often contain expert insight and contrarian views

### Technical Blogs
- Lilian Weng (lilianweng.github.io): Survey-quality blog posts on ML topics
- Simon Willison (simonwillison.net): LLM tooling and practical applications
- Chip Huyen (huyenchip.com): ML engineering and systems
- Distill.pub: Interactive ML explanations (though inactive since 2021)
- Domain experts: search for `"<topic>" blog` or `"<topic>" tutorial`

### Conference Workshops
- Workshop papers are often more experimental and forward-looking than main proceedings
- Search for `"<topic>" workshop 2025 2026` to find recent workshop papers
- ICLR, NeurIPS, ICML, ACL, CHI, CSCW workshops

---

## Source Type Evaluation

| Source Type | Trust Level | What to Check |
|-------------|------------|---------------|
| **Peer-reviewed journal article** | High | Venue reputation, sample size, methodology, replication |
| **Top-tier conference paper** (NeurIPS, ICML, ICLR, ACL, CHI) | High | Same as journal; conferences in CS are equivalent to journals |
| **Workshop paper** | Medium-High | More speculative; check if main results are validated |
| **arXiv preprint** | Medium | Author track record, methodology quality, whether there's code/data |
| **Technical blog post** | Low-Medium | Author credibility, whether claims are backed by evidence, community reception |
| **Reddit/HN discussion** | Low | Useful for signals and pointers, not as primary evidence |
| **Book chapter** | High | Publisher quality, edition, whether content is dated |

### Red Flags

- Preprints with extraordinary claims and no code/data release
- Papers that cite only their own prior work
- Blog posts that make quantitative claims without methodology
- Papers with very small N and sweeping conclusions
- Work that hasn't been cited by anyone after 2+ years

### Green Flags

- Reproduced results (independent replication)
- Code and data available
- Cited by well-known researchers in the field
- Published in top-tier venues with rigorous review
- Clear limitations section

---

## Serendipity Techniques

Serendipity doesn't mean random — it means structured divergent search.

### Cross-Domain Queries
If your topic is "agent memory architectures," try:
- `"memory consolidation" sleep neuroscience` — biological memory models
- `"organizational memory" knowledge management` — how human organizations remember
- `"cache eviction" "replacement policy"` — CS systems approaches to memory
- `"spaced repetition" learning` — evidence-based memory techniques

### Citation Surprise Detection
During dependency expansion (Phase 4), watch for:
- Papers highly cited but in a **different field** — these are bridging works
- Papers that appear in 3+ reference lists but weren't in any search results — foundational work the search missed
- Very recent papers (< 6 months) citing multiple Level 0 papers — emerging synthesis

### The "Also Cited By" Pattern
When a key paper cites something unexpected, follow that thread. If a paper on "multi-agent coordination" also cites a paper on "ant colony optimization," that's a cross-pollination signal worth exploring.

### Cross-Pollination Queries (Phase 5)
During synthesis, query the index with terms that combine concepts from different thematic clusters. If your research found clusters around "episodic memory" and "multi-agent coordination," try: `episodic shared multi-agent memory transfer`.
