# Missing Tools

Tools referenced by built-in team agents that do not yet exist in the base toolset or the
teaparty-config MCP server. Each entry names the tool, which agents need it, what it does,
and what API or infrastructure it requires.

**Base toolset** (available now): Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch, mcp__teaparty-config__AskQuestion

**teaparty-config MCP tools** (available now): config CRUD, escalation, messaging, intervention, image_gen_openai, image_gen_flux, image_gen_stability, youtube_transcript, arxiv_search, semantic_scholar_search, pubmed_search, patent_search_uspto, patent_search_epo

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
