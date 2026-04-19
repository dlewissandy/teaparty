# Research Pipeline

The research pipeline ingests academic literature so agents can ground decisions in published work rather than intuition. Implemented under `teaparty/learning/research/`.

Research memory is separate from episodic and procedural memory: it is external knowledge the organization consults, not knowledge it produced. The pipeline handles acquisition (fetching papers), extraction (turning PDFs into searchable text), and retrieval (indexing with source-weighted BM25).

## Fetchers

### arXiv (`fetch_arxiv.py`)

Queries the arXiv REST API for papers matching a keyword or phrase, writes structured records to an output directory, and maintains a registry (`sources.json`) for deduplication across runs.

Options include category filtering (e.g. `cs.AI`), sort order (relevance, lastUpdatedDate, submittedDate), pagination, and maximum result count. Each paper is written as a YAML-frontmattered markdown file with abstract, authors, dates, arXiv ID, and categories.

### Semantic Scholar (`fetch_semantic_scholar.py`)

Three subcommands against the Semantic Scholar Graph API:

- `search` — keyword/phrase search across the corpus
- `references` — papers cited by a given paper
- `citations` — papers that cite a given paper

Reference and citation traversal complements arXiv: once a seed paper is found, its local graph can be expanded in either direction to surface related work that keyword search would miss.

Authenticated access via `S2_API_KEY` raises rate limits above the unauthenticated ~100 req / 5 min.

## Extraction

`extract_pdf.py` downloads a PDF (or reads a local one) and extracts plain text. The primary path uses PyMuPDF (`fitz`) when available; the fallback uses a basic stdlib approach that extracts what it can from uncompressed streams.

Exit is always 0 — an empty output file signals extraction failure. The caller decides what to do. This keeps the pipeline tolerant of the one pathological PDF that would otherwise block a batch run.

## Indexing and retrieval

`indexer.py` maintains a SQLite FTS5 database over paper markdown files with YAML frontmatter. Retrieval supports:

- **BM25 scoring** via FTS5
- **Citation-count boost** — papers cited more heavily get a ranking bump
- **Source-type weighting** — different source tiers (e.g. peer-reviewed vs preprint) carry different default weights
- **Section-scoped queries** — retrieve against `abstract`, `notes`, `relevance`, or `full_text` sections
- **MMR re-ranking** for diversity, preventing near-duplicate results from dominating top-k

The database is initialized with `--init`, populated with `--source <papers_dir> --registry <sources.json>`, and queried with `--query "..." --top-k N`.

## How it connects

Research retrieval is invoked by agents during planning and by researchers during deep literature passes. It does not promote into episodic memory — a paper is not a learning, it is a source. When agents form their own conclusions from a paper, those conclusions enter the episodic system through the normal extraction path, and the paper ID can be preserved in the entry's metadata for traceability.

For the broader research approach (how topics are selected, how papers are digested, how findings feed design), see the research skills (`/research`, `/digest`, `/intake`) and the research index under `docs/research/`.
