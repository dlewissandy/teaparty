# Claude Code Memory System

Research into the mechanics of Claude Code's built-in memory system (MEMORY.md / auto-memory), its retrieval model, scoping hierarchy, subagent memory, and the related OpenClaw project. Relevant to TeaParty's agent design because the `memory` field on TeaParty agents mirrors this architecture directly.

---

## Overview

Claude Code has two complementary persistence mechanisms that both load at session start: **CLAUDE.md files** (human-authored instructions) and **auto memory** (Claude-authored notes). Neither uses semantic retrieval; both are injected verbatim into the context window. This is a load-everything-at-startup model, not a retrieve-on-demand model.

---

## 1. CLAUDE.md Files

### How They Work

CLAUDE.md files are plain Markdown that Claude reads at session start. Their content becomes part of the context window for the entire session. There is no selective retrieval; whatever is in the file is always present.

Claude Code walks the directory tree from the current working directory upward, loading every CLAUDE.md and CLAUDE.local.md it finds. CLAUDE.md files in subdirectories below the working directory are **not** loaded at launch; they are loaded on demand when Claude reads a file in that subdirectory.

### Scope Hierarchy (highest priority first)

| Scope | Location | Shared With |
|-------|----------|-------------|
| Managed policy | `/Library/Application Support/ClaudeCode/CLAUDE.md` (macOS) | All users on the machine |
| Project | `./CLAUDE.md` or `./.claude/CLAUDE.md` | Team via version control |
| Local project | `./CLAUDE.local.md` | Just you (gitignored) |
| User | `~/.claude/CLAUDE.md` | Just you, across all projects |
| User-level rules | `~/.claude/rules/` | Just you |

More specific scopes take precedence over broader ones (project overrides user).

### .claude/rules/ — Path-Scoped Rules

Files in `.claude/rules/` can carry YAML frontmatter with a `paths` field. Rules with matching paths are loaded **only when Claude works with a matching file**, reducing noise and saving context tokens. Rules without a `paths` field load unconditionally at launch, same as CLAUDE.md.

```yaml
---
paths:
  - "src/api/**/*.ts"
---
# API Development Rules
- All endpoints must include input validation
```

### Import Syntax

CLAUDE.md files can include `@path/to/file` references. Referenced files are expanded and loaded into context at launch alongside the containing CLAUDE.md. Imports resolve to a maximum depth of five hops.

### Known Adherence Data

- Files under 200 lines: ~92% rule application rate
- Files over 400 lines: ~71% rule application rate
- Modular approach (5 files × 30 lines each): ~96% compliance

**Source:** SFEIR Institute Claude Code deep-dive; official Claude Code memory documentation.

---

## 2. Auto Memory (MEMORY.md)

### Mechanical Operation

Auto memory is the system through which Claude writes its own notes to disk and re-reads them across sessions. It is distinct from CLAUDE.md (which the human writes).

**Storage location:** `~/.claude/projects/<project>/memory/`

The `<project>` path is derived from the git repository root, so all worktrees and subdirectories of the same repo share one auto memory directory.

**Directory structure:**

```
~/.claude/projects/<project>/memory/
├── MEMORY.md          # Concise index — loaded first 200 lines every session
├── debugging.md       # Detailed notes Claude creates on demand
├── api-conventions.md # Topic-specific files Claude creates as needed
└── ...
```

### What Gets Loaded at Startup vs. On Demand

This is the critical distinction:

- **MEMORY.md**: The first 200 lines are injected verbatim into the system prompt at the start of every session. Content beyond line 200 is silently dropped.
- **Topic files** (debugging.md, api-conventions.md, etc.): These are NOT loaded at startup. Claude reads them on demand using its standard file-reading tools (Read, Write, Edit) during the session when it determines it needs that information.
- **CLAUDE.md files**: Loaded in full regardless of length (though adherence degrades above 200 lines).

The 200-line limit applies exclusively to MEMORY.md. The design intent is that MEMORY.md acts as a concise index pointing to the topic files; details live in the topic files, not in MEMORY.md itself.

### What Claude Saves

Claude decides autonomously what is worth saving. It writes to MEMORY.md when it detects:
- Recurring patterns (a correction applied multiple times)
- Build commands and test commands
- Debugging insights specific to this codebase
- Architectural decisions
- Code style preferences

Claude does not save to memory on every message; it exercises judgment about whether information would be useful in a future session.

### Activation and Control

- On by default.
- Toggle via `/memory` command inside a session, or set `autoMemoryEnabled: false` in project settings.
- Environment variable: `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` to disable.
- Auto memory is machine-local. It is not synced across machines or shared via git.

### After `/compact`

CLAUDE.md files survive compaction fully — they are re-read from disk and re-injected fresh. Auto memory survives compaction in the same way. If an instruction disappears after `/compact`, it was given only in conversation, not in a memory file.

**Sources:** Official Claude Code memory documentation (code.claude.com/docs/en/memory); Giuseppe Gurgone's technical write-up; SFEIR Institute deep-dive.

---

## 3. Subagent Persistent Memory

Added in Claude Code v2.1.33 (February 2026), the `memory` frontmatter field gives individual subagents their own persistent memory directories.

### Configuration

```yaml
---
name: code-reviewer
description: Reviews code for quality and best practices
memory: user
---
```

### Memory Scope Options

| Scope | Location | Use When |
|-------|----------|----------|
| `user` | `~/.claude/agent-memory/<name>/` | Cross-project learnings (recommended default) |
| `project` | `.claude/agent-memory/<name>/` | Project-specific, shareable via git |
| `local` | `.claude/agent-memory-local/<name>/` | Project-specific, not in git |

### How It Loads

When a subagent has memory enabled:
1. The first 200 lines of the subagent's `MEMORY.md` are injected into its system prompt at startup.
2. Read, Write, and Edit tools are automatically enabled for the subagent to manage its memory files.
3. The system prompt includes instructions for the subagent to curate MEMORY.md if it exceeds 200 lines.

The behavior is identical to the main session's auto memory — same 200-line index limit, same on-demand topic files pattern.

**Source:** Official Claude Code subagents documentation (code.claude.com/docs/en/sub-agents).

---

## 4. Known Limitations of This Retrieval Architecture

### 4.1 No Selective Retrieval — Flat Context Injection

The fundamental limitation is that there is no retrieval step. All memory content loads upfront and sits in the context window for the entire session. This contrasts with RAG-style systems where relevant content is pulled in response to queries.

Consequences:
- Memory competes with conversational content for context window tokens.
- MEMORY.md must stay under 200 lines or content is silently lost.
- Content relevance is not assessed at retrieval time; everything injected has equal prominence.

### 4.2 The 200-Line Hard Truncation

Content beyond line 200 of MEMORY.md is simply not loaded. There is no warning surfaced to the user. This happens silently. The only safeguard is that Claude is instructed to keep MEMORY.md as a concise index and push details to topic files.

### 4.3 Topic File Retrieval Depends on Agent Initiative

Topic files (the detailed notes beyond MEMORY.md) are only read if Claude decides to read them. This is a form of selective retrieval, but it is entirely dependent on Claude recognizing that a topic file might be relevant. If MEMORY.md's index entry for a topic is not salient to the current task, Claude may not read the corresponding file.

This matches the finding from Rajiv Pant's analysis: "Claude has memory tools available but doesn't invoke them automatically ... If it doesn't think to look, relevant context stays buried."

### 4.4 Token Cost

A 200-line MEMORY.md consumes approximately 1,500 tokens per session start. A 200-line CLAUDE.md consumes approximately 4,000 tokens. These are small relative to the 200,000-token context window, but they are always-on costs regardless of session relevance.

### 4.5 Machine-Local Storage

Auto memory does not sync across machines, is not committed to git, and is not shared between team members. Project-scoped subagent memory can be shared via git, but the main session's auto memory is always local.

### 4.6 No Semantic Indexing

There is no embedding, no vector database, and no similarity search. Retrieval is purely procedural: read the index at startup, then read specific topic files during the session using the Read tool. This is simpler and more auditable than vector retrieval, but it cannot surface "latently relevant" content the way semantic search would.

---

## 5. OpenClaw's Memory Architecture (Comparison)

OpenClaw is an open-source autonomous AI agent (Peter Steinberger) that uses messaging platforms (Signal, Telegram, WhatsApp, Discord) as its UI and runs Claude as its underlying model. Its memory system is explicitly influenced by Claude Code's MEMORY.md approach but adds semantic retrieval.

### File Structure

```
memory/
├── MEMORY.md          # Durable preferences, decisions, facts (human-curated or AI-curated)
├── YYYY-MM-DD.md      # Daily logs — running journal of each session
├── USER.md            # Working style and formatting preferences
└── SOUL.md            # Personality and operational rules
```

The MEMORY.md / daily-log split is architecturally similar to Claude Code's MEMORY.md / topic-files split, but with a temporal structure for daily logs.

### Retrieval Mechanism — Hybrid Search

OpenClaw goes significantly beyond Claude Code's flat injection. It implements:

1. **Chunking:** Memory files are split into approximately 400-token chunks with 80-token overlap.
2. **Embedding storage:** Chunk embeddings are stored in a local SQLite database using the `sqlite-vec` extension.
3. **Full-text search:** SQLite's FTS5 virtual tables enable keyword-style search.
4. **Hybrid retrieval:** Queries combine cosine similarity (semantic) with FTS5 (keyword) using weighted score fusion. This handles both "natural language" queries and "needle in a haystack" exact lookups.
5. **Context injection:** Only the retrieved chunks are injected into the prompt, not the full memory file.

This is closer to the Mem0 / RAG architectures in the research library than to Claude Code's approach.

### Key Differences From Claude Code

| Dimension | Claude Code | OpenClaw |
|-----------|-------------|----------|
| Retrieval model | Full injection (first 200 lines) | Hybrid semantic + keyword search |
| Storage backend | Plain Markdown files | Markdown + SQLite (embeddings + FTS5) |
| Token cost | Fixed per session | Variable, proportional to retrieval results |
| Human-editability | Full (plain Markdown) | Full (source files plain Markdown) |
| Scope | Per-project / per-user | Per-agent instance |
| Daily logs | No | Yes (YYYY-MM-DD.md) |
| Cross-session persistence | Yes (machine-local) | Yes (machine-local) |
| Multi-agent sharing | Project-scope subagent memory only | Not built-in |

### OpenClaw Limitations

- Daily notes require manual pruning to avoid noise accumulation over time.
- Semantic search quality varies with query phrasing.
- Context windows still impose hard limits on injected material.
- Security: prompt injection risk is significant (Cisco and BitSight advisories); OpenClaw is not designed for isolated/sandboxed use.

**Sources:** OpenClaw memory docs (docs.openclaw.ai/concepts/memory); Milvus memsearch blog (extracted and open-sourced OpenClaw's memory system); LumaDock OpenClaw memory tutorial; DataCamp OpenClaw vs. Claude Code comparison.

---

## 6. Implications for TeaParty

### 6.1 The TeaParty MEMORY.md Context

TeaParty agents use the same `memory` frontmatter field (`user`, `project`, `local`) that Claude Code subagents use. The mechanics documented above apply directly:

- The first 200 lines of `MEMORY.md` in the agent's memory directory are injected at session start.
- Topic files are read on demand via the agent's file tools.
- Memory is per-agent, not shared across agents by default.

### 6.2 Implication: MEMORY.md Must Be an Index, Not a Reference Manual

Because only 200 lines load automatically, TeaParty agents' MEMORY.md files should be structured as **concise indexes** that point to topic files. Putting detailed information directly in MEMORY.md risks silent truncation.

Design principle: encourage agents (via their prompts) to maintain MEMORY.md as a table of contents with one-liners and to create named topic files for detailed content.

### 6.3 Implication: Topic File Retrieval Requires Agent Awareness

Topic files only get read if the agent decides to read them. This means agents need enough context in MEMORY.md's index entries to recognize when a topic file is relevant. Terse or ambiguous index entries will cause agents to miss relevant stored knowledge.

Design principle: when agents write memory, they should be prompted to write index entries that are specific enough to be triggered by future tasks (e.g., "debugging.md: how to diagnose connection pool exhaustion in postgres" rather than just "debugging notes").

### 6.4 Implication: Shared vs. Per-Agent Memory Is a Design Choice

Claude Code only supports per-agent memory. True shared memory (where one agent's learning is immediately visible to another) requires either:
(a) writing to a shared file path that all agents read, or
(b) a higher-level memory service (as in Collaborative Memory / SEDM papers in the research library).

For TeaParty workgroups, if cross-agent knowledge sharing is needed, `project`-scoped memory directories are visible to all agents with `project` scope on the same project. But agents do not automatically merge or reconcile their memories; each agent maintains its own directory.

### 6.5 Implication: OpenClaw-Style Hybrid Retrieval Is an Upgrade Path

The Claude Code flat-injection model is simple, auditable, and works well for small corpora. As TeaParty agents accumulate more memory over time, the 200-line ceiling will become a bottleneck. The OpenClaw architecture (chunking + sqlite-vec + FTS5 hybrid search) has been extracted and open-sourced as `memsearch` (github.com/zilliztech/memsearch) and is a plausible future upgrade for agents that need larger persistent memory stores.

This also connects to the Mem0 findings in `COGARCH §2.9`: production memory systems using structured retrieval achieve 26% accuracy improvements and 90% token savings over full-context injection at scale.

---

## Sources

- [How Claude remembers your project — Official Claude Code Docs](https://code.claude.com/docs/en/memory)
- [Create custom subagents — Official Claude Code Docs](https://code.claude.com/docs/en/sub-agents)
- [Claude Code's Experimental Memory System — Giuseppe Gurgone](https://giuseppegurgone.com/claude-memory)
- [The CLAUDE.md Memory System — Deep Dive, SFEIR Institute](https://institute.sfeir.com/en/claude-code/claude-code-memory-system-claude-md/deep-dive/)
- [How Claude's Memory Actually Works — Rajiv Pant](https://rajiv.com/blog/2025/12/12/how-claude-memory-actually-works-and-why-claude-md-matters/)
- [Claude Code: Mastering Memory.md — Medium / Rigel Computer](https://medium.com/rigel-computer-com/claude-code-mastering-memory-md-avoiding-misconceptions-a-deep-dive-746a26a7f78d)
- [OpenClaw Memory — docs.openclaw.ai](https://docs.openclaw.ai/concepts/memory)
- [How OpenClaw Memory Works — LumaDock](https://lumadock.com/tutorials/openclaw-memory-explained)
- [We Extracted OpenClaw's Memory System and Open-Sourced It (memsearch) — Milvus Blog](https://milvus.io/blog/we-extracted-openclaws-memory-system-and-opensourced-it-memsearch.md)
- [OpenClaw vs. Claude Code — DataCamp](https://www.datacamp.com/blog/openclaw-vs-claude-code)
- [OpenClaw Memory Architecture — Zen van Riel](https://zenvanriel.nl/ai-engineer-blog/openclaw-memory-architecture-guide/)
- [Deep Dive: OpenClaw Memory System — Snowan Gitbook](https://snowan.gitbook.io/study-notes/ai-blogs/openclaw-memory-system-deep-dive)
- [memsearch — Zilliz / GitHub](https://github.com/zilliztech/memsearch)
