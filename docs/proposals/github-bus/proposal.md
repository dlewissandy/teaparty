# Proposal: GitHub-backed Message Bus + Proxy-as-Subscriber

**Status:** Draft for review
**Supersedes:** the per-agent SQLite bus, Unix-socket dispatch, JSONL session
injection, the CfA state machine, and the hand-rolled hierarchical runner.

---

## 1. Why this exists

TeaParty grew a large runtime back when the Claude Code harness gave you very
little. That is no longer the situation. Two of TeaParty's four pillars are now
provided natively by the harness:

- **Hierarchical dispatch** — the Agent/subagent tool, the Workflow tool,
  worktree isolation, and background tasks already give you "an uber team
  coordinates, subteams execute in parallel, each in its own context window."
  `teaparty/runners/`, `messaging/listener.py`, `messaging/dispatcher.py`, and
  the fan-in/orphan-recovery plumbing are a reimplementation of native
  primitives.
- **Conversation for Action** — Intent → Plan → Execute with backtracking is a
  *process*. It is a `SKILL.md` (plus an optional Workflow call for the fan-out
  parts), not a Python state machine with actors and gates.

What the harness gives you is all **intra-unit-of-work**: ephemeral,
hierarchical, in-process, dead when the task finishes. What it gives you
*nothing* for is **across people, agents, and time**: my agent talking to your
agent, durably, threaded by issue, readable and writable by a human without
spawning an agent. And it has no notion of *"act as this specific human
would."*

Those two gaps are the only things genuinely worth owning:

1. **A message bus** — persistent, multi-user, distributed, partitioned by
   project, threaded by issue, and directly accessible without `claude -p`.
2. **A proxy** — an agent that responds to tasks on your behalf and executes
   them the way you would.

This proposal builds the bus on **GitHub issues** and rebuilds the proxy as a
**subscriber on that bus**.

---

## 2. The two-axis model

The governing constraint: **projects and organizations do not share a
hierarchy.** We honor it structurally by putting the two axes on two
substrates that *cannot* be conflated.

| Axis | What it models | Substrate | Shape |
|------|----------------|-----------|-------|
| **Org (people)** | who exists, who leads, who reports to whom, which proxy represents which human | `.teaparty/` roster YAML (already exists) | a tree of orgs → teams/workgroups → members |
| **Project (work)** | what is being worked on and discussed | GitHub issues | repo → issue → comments |

The two axes meet at exactly **one** point: a *member* (named in the roster
YAML) authors a *comment* (in a GitHub issue). There is no shared tree, no
enum that mixes `office_manager` with `task`, no conversation-type hierarchy
spanning both. This is the entire constraint, satisfied by construction.

```
  ORG AXIS (people)                         PROJECT AXIS (work)
  .teaparty/ roster YAML                    GitHub
  ─────────────────────                     ──────────────────
  org                                       repo  (= project)
   └─ workgroup (lead, decider, agents)      └─ issue  (= thread)
       └─ member  ──── authors ───────────────►  comment  (= message)
           └─ proxy (represents a human)
```

---

## 3. Bus ↔ GitHub mapping

| Bus concept | GitHub primitive |
|-------------|------------------|
| Project / partition | repository |
| Thread | issue |
| Sub-thread / decomposition | sub-issue (native) or `reply_to` envelope link |
| Message | issue comment |
| Org-level / cross-project thread | issue in a designated **coordination repo** |
| Routing label (workgroup, kind) | issue label |
| Decider / owner of a thread | issue assignee |
| Human notification | native `@mention` |
| Read cursor | last-seen `(comment timestamp, comment id)` |
| Direct human access (no `claude -p`) | GitHub web UI, mobile app, `gh` CLI, email reply, API |

A "project" is preferably one repo. Lightweight projects that do not warrant
their own repo can be a **label within the coordination repo** instead.

---

## 4. Message envelope

Issue comments are flat and carry only a GitHub author. The bus needs sender
identity, addressing, message kind, and logical threading on top. Each
**agent-authored** comment carries a machine-readable header (an HTML comment,
invisible in rendered Markdown) followed by a human-readable byline and body:

```markdown
<!-- tp {"v":1,"from":"coding-agent","to":["proxy:dlewis"],"kind":"question","reply_to":"c_8841","thread":"acme/widgets#42"} -->
**coding-agent → proxy(dlewis):** Bump minor or major for this API change?
```

Envelope fields:

| Field | Meaning |
|-------|---------|
| `v` | envelope schema version |
| `from` | authoring member (roster name); for a proxy, `proxy:<human>` |
| `to` | addressees — member names and/or `proxy:<human>` |
| `kind` | `question` \| `answer` \| `task` \| `status` \| `escalation` \| `note` |
| `reply_to` | comment id this replies to (logical sub-threading) |
| `thread` | canonical thread id (`owner/repo#issue`) |

**Humans need no envelope.** A comment authored by a real GitHub user with no
`tp` header is treated as a human message from that user. This is what makes
the bus "directly accessible without `claude -p`" — you just type a comment.

---

## 5. Identity model

| Who | Posts as | Marker |
|-----|----------|--------|
| **Human** | their own GitHub account | none (bare comment) |
| **Proxy** (for human X) | **X's GitHub account** | comment body **starts with `@proxy`** + envelope `from: proxy:X` |
| **Worker agent** (coding-agent, …) | one shared `teaparty-bot` GitHub App | envelope `from: <agent>` |

The proxy keeps its human's native identity — avatar, notifications, thread
participation all work — while the leading `@proxy` makes proxy-authored
comments instantly distinguishable from things the human actually wrote.
`@proxy` is a **display marker**, not a required GitHub handle; the structured
envelope underneath is the source of truth for machine parsing.

Audit trail: every comment is attributable. Bare comment from a user → that
human. `@proxy …` from a user → that human's proxy. Envelope `from` from the
bot → that worker agent.

---

## 6. Addressing, subscription, notification

- **A message is "for" an agent** when the agent's name (or `proxy:<human>`)
  appears in the envelope `to`, or the issue carries the agent's routing label
  / assignment. Agents filter their inbox on these.
- **Humans are reached natively** via `@mention`. The proxy escalates by
  `@mention`-ing the real human, which triggers GitHub's own push/email — no
  separate notification system.
- **Delivery is pull-based.** An agent is invoked, reads its inbox via the MCP
  adapter `since` a cursor, acts, posts replies, exits. Re-invocation re-reads.
  The bus is passive storage + notification; it does **not** own process
  lifecycle.
- **Wake-up** is webhook-driven (`issue_comment`, `issues` events) with
  `since`-cursor polling as catch-up fallback. The harness already supports
  GitHub webhook activity subscriptions, so the push half is largely in place.

---

## 7. The proxy as a subscriber

The proxy stops being infrastructure and becomes one bus participant:

1. **Watch** issues where its human is the decider/assignee, or where a comment
   is addressed `to: proxy:<human>`.
2. **Wake** on a webhook (or scheduled poll).
3. **Read** the thread since its cursor.
4. **Consult** the human's preference store (today: `proxy.md` + memory).
5. **Decide:**
   - confident → **post an answer as the human, prefixed `@proxy`**;
   - not confident → **escalate by `@mention`-ing the human** and wait.
6. **Learn** from the human's eventual reply (the delta between its prediction
   and the human's actual answer remains the highest-value signal).

The approval-gate apparatus collapses into "post to thread; proxy-or-human
replies." The ACT-R / two-pass / confidence-calibration machinery becomes an
*internal detail of this one subscriber* — keep, trim, or rebuild later without
touching the bus.

---

## 8. What gets deleted

Once the adapter + proxy-subscriber work:

- `teaparty/messaging/listener.py`, `dispatcher.py`, `child_dispatch.py` — Unix-socket dispatch.
- `teaparty/runners/` — the hand-rolled subprocess runner/launcher (replaced by harness subagents/Workflow).
- `teaparty/cfa/` state machine, actors, gates — CfA becomes a skill.
- `inject_composite_into_history` and JSONL session surgery in `conversations.py`.
- Per-agent SQLite DBs and the `agent_contexts` fan-in tables.
- Orphan recovery, PID/worktree tracking tied to the runner.

What gets kept (trimmed):

- `.teaparty/` roster YAML and `config/roster.py` — the org axis.
- The proxy's preference/memory store — internal to the subscriber.
- The `MessageBusAdapter` Protocol — the new `GitHubMessageBus` implements it.
- The bridge/dashboard, repointed to read GitHub instead of SQLite (optional).

---

## 9. Open questions / risks

- **Rate limits.** GitHub caps content creation (secondary limits) and 5000
  req/hr authenticated. The bus is for **coordination-grained** messages, not
  token-level streaming — live stream output stays local/ephemeral. Agents
  should batch. Need to validate real chatter volume against limits.
- **Latency.** Webhook + poll is seconds, not milliseconds. Fine for team
  coordination; not for tight inner loops (which stay in-process anyway).
- **Private repos / access.** Every participant (human and bot) needs repo
  access. Cross-org work needs the bot installed per org.
- **Secret hygiene.** Envelopes and bodies are posted publicly within the repo
  — never put credentials in messages; the adapter should scrub.
- **Ordering / consistency.** Comment timestamps + ids give a stable total
  order per issue (reuse the existing `receive_since_cursor` cursor design).
- **Non-GitHub humans.** Anyone who must participate needs a GitHub account, or
  an email-in bridge.
- **Org-axis source of truth.** Roster YAML stays authoritative; GitHub teams
  are *not* used for the people tree (they cannot express
  "agent X represents human Y").

---

## 10. Phased plan

- **Phase 0 — this doc.** Lock the model.
- **Phase 1 — bus core.** `GitHubMessageBus` adapter (behind the existing
  `MessageBusAdapter` Protocol) + envelope codec + a `tp` CLI
  (`post` / `read` / `threads`) + an MCP server exposing
  `post_message` / `read_thread` / `list_threads` / `subscribe`.
- **Phase 2 — proxy subscriber.** Reimplement the proxy as a watcher that wakes
  on webhook, reads a thread, consults the preference store, and answers-as-you
  (`@proxy`) or escalates (`@mention`). Reuse the existing memory internals.
- **Phase 3 — teardown.** Delete the claude-coupled runtime (§8). Repoint the
  dashboard if kept.
- **Phase 4 — CfA as a skill.** Port Intent → Plan → Execute (with
  backtracking) to a `SKILL.md`; fan-out via the Workflow/Agent tools.

---

## 11. Acceptance criteria

- A human can post and read a thread from the GitHub UI / `gh` with no agent
  running.
- An agent can post to and read from the same thread via MCP, with correct
  sender attribution via the envelope.
- A question addressed `to: proxy:<human>` is answered by the proxy as that
  human, prefixed `@proxy`, or escalated by `@mention` — with no per-agent
  SQLite DB and no Unix socket involved.
- Two different humans' agents exchange messages on one issue, each correctly
  attributed.
- The org axis (roster YAML) and project axis (issues) share no data structure.
