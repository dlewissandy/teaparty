# Missing Tools

Tools referenced by built-in team agents that do not yet exist in the base toolset or the
teaparty-config MCP server. Each entry names the tool, which agents need it, what it does,
and what API or infrastructure it requires.

**Base toolset** (available now): Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch, AskQuestion

**teaparty-config MCP tools** (available now): config CRUD, escalation, messaging, intervention

---

## Image generation

Agents affected: `png-artist`

PNG generation from a text prompt cannot be done with any current tool. Three providers are
candidates; each requires its own API key and should be its own MCP tool so key scope can be
controlled independently.

| Tool | Provider | Key required | Notes |
|------|----------|--------------|-------|
| `image-gen-openai` | OpenAI (gpt-image-1 or dall-e-3) | `OPENAI_API_KEY` | Single tool; model selected via parameter |
| `image-gen-flux` | Black Forest Labs Flux | `BFL_API_KEY` | |
| `image-gen-stability` | Stability AI | `STABILITY_API_KEY` | |

Each tool takes a prompt, optional size/style parameters, and returns a path to the saved image
file. Only one needs to be wired per deployment; the agent.md for `png-artist` should list
whichever tools are available.

---

## YouTube transcript retrieval

Agents affected: `video-researcher`

WebFetch cannot retrieve YouTube transcripts. The agent needs a dedicated tool that accepts a
YouTube URL and returns the transcript text (with optional timestamps). Two implementation
paths:

| Tool | Mechanism | Notes |
|------|-----------|-------|
| `youtube-transcript` | `youtube-transcript-api` Python library | No API key; uses YouTube's internal caption endpoint |
| `youtube-dl-transcript` | `yt-dlp --write-auto-subs` | More robust; handles non-English auto-captions |

`youtube-transcript` via `youtube-transcript-api` is the simpler path. Neither requires a
paid API key but both require the library to be installed in the environment.

---

## Academic literature databases

Agents affected: `literature-researcher`

WebSearch finds academic papers approximately. Dedicated API tools return structured metadata
(authors, DOI, citation counts, abstracts) and support programmatic filtering that general web
search cannot. These are high-value for any serious research workload.

| Tool | Database | Key required | Notes |
|------|----------|--------------|-------|
| `arxiv-search` | arXiv | None | REST API; returns papers, abstracts, PDF links |
| `semantic-scholar-search` | Semantic Scholar | None (rate-limited) or `S2_API_KEY` | Returns citation graphs, influence scores |
| `pubmed-search` | PubMed / NCBI | `NCBI_API_KEY` (optional, raises rate limit) | Entrez E-utilities; biomedical focus |

---

## Patent search

Agents affected: `patent-researcher`

Patent databases expose structured APIs that go well beyond what WebSearch returns — claim
text, citation trees, filing dates, assignee history. Each jurisdiction has its own API.

| Tool | Database | Key required |
|------|----------|--------------|
| `patent-search-uspto` | USPTO PatentsView | None (public API) |
| `patent-search-epo` | EPO Open Patent Services | `EPO_OPS_KEY` |
| `patent-search-google` | Google Patents (scrape) | None; fragile |

USPTO PatentsView is the most accessible starting point.

---

## Browser automation

Agents affected: `acceptance-tester`

Testing user-facing web interfaces requires a browser. Bash + curl covers API-level checks
but cannot simulate user interaction. Playwright is the standard tool and has an official MCP
server.

| Tool | Mechanism | Key required |
|------|-----------|--------------|
| `playwright` (MCP) | Microsoft Playwright MCP server | None |

Enables `acceptance-tester` to navigate pages, click, fill forms, and assert on rendered
output — the full behavioral acceptance loop.

---

## Environment dependencies

Not missing MCP tools — binaries that must be present in the agent execution environment.

| Agent | Dependency | Purpose |
|-------|-----------|---------|
| `latex-writer` | `pdflatex` or `tectonic` | Compile and verify LaTeX source |
| `tikz-artist` | `pdflatex` or `tectonic` | Compile TikZ figures |
| `pdf-writer` | `pandoc` or `weasyprint` | Render Markdown/HTML to PDF |
| `graphviz-artist` | `graphviz` (`dot` command) | Render DOT files to image |
