# Federated Teams: A Consent-Based Contract Architecture

**Status:** Proposal · **Scope:** cross-human teams, account isolation, the membrane, CfA-as-contract

## Thesis

A team is not a process that runs somewhere. It is a **federation of
independently-accountable humans**, each running their own agents on their own
Anthropic account, coordinating through a shared repository. No node ever
executes another human's work. Collaboration happens by **negotiating
contracts** across a membrane between principals — and every such contract is
just a Conversation for Action (CfA) whose terms include not only *intent* but
*cost*, *schedule*, and *review level*.

The system is **safe and license-clean by construction**. It is deliberately
**not live by construction**: agents negotiate by consent only, deadlock is a
legal outcome, and the sole way to break a deadlock is a human. Liveness is a
human responsibility.

## Constraints and invariants

These are non-negotiable. Everything else serves them.

1. **One account, one human, local execution.** The Claude Code CLI runs on
   the owner's machine against the owner's account. Compute is permanently
   sharded by account. There is no central executor.

2. **Execution-owner invariant.** A task executes *only* on the node whose
   owner's account is authorized for it. An agent on node A that wants work in
   B's scope **posts a message**; it cannot call a function that runs on B's
   account. Cross-account dispatch is a message, never a call. This is the line
   that keeps the system on the right side of the subscription terms, and it is
   enforced at the membrane, not by convention.

3. **Consent only — no coercion.** No agent, including a project lead, can
   impose work on another principal's account. Work runs on Bob's account only
   because Bob (or his delegate, within standing authority Bob granted) accepted
   it as Bob's own job. The project lead's power is **persuasive and
   re-routing**, never coercive.

4. **Accountability.** Every action attributes to a principal. Proxy actions
   carry `on_behalf_of`. The membrane log answers "why did this account do
   this?" with "because <human> consented, here."

5. **Liveness is human.** The platform guarantees consent, isolation, and
   ToS-safety. It does **not** guarantee that a project finishes. Deadlock is a
   first-class, loudly-surfaced state whose only resolution is a human.

## Core entities

| Entity | Definition |
|---|---|
| **Principal** | One human + their implicit proxy + their node + their account. The unit of accountability and execution. |
| **Node** | A local TeaParty install for one principal. Runs only that principal's work, on that principal's account. May be a laptop or a personal always-on VM (still one human → compliant). |
| **Proxy** | The principal's implicit delegate. Acts within a learned model of the human, bounded by a **mandate**. Runs on the principal's own node/account. |
| **Team** | An agent hierarchy *within a single principal's domain*. Arbitrarily deep — it is just one person using Claude Code hard. |
| **Membrane** | The boundary between principals. Carries only requests, contracts, and artifacts. Backed by GitHub. The isolation layer. |
| **Mandate** | A team's negotiating authority: hard reservation terms (human-set) + soft tradeable defaults. The proxy negotiates within it; crossing a hard term escalates. |
| **Contract** | A mutually-signed agreement reached by a CfA. Has terms (scope, cost, schedule, review). |

## Topology: a two-tier bus

The bus stops being a data structure and becomes a **federation protocol**.
There are two tiers, and the split *is* the isolation boundary:

- **Intra-principal (local bus).** Within one node's domain — fast, synchronous,
  private SQLite, exactly what exists today (`messaging/conversations.py`).
  Carries all intra-team agent traffic, including the principal's own proxy.

- **Inter-principal (membrane).** Between principals — GitHub. Carries only what
  crosses a human boundary: requests, contracts, signed decisions, artifacts.
  **GitHub is the membrane between humans; the local bus is the tissue inside
  one human's domain.**

Never push turn-level agent chatter through the membrane. If two agents need to
talk fast, they are inside one principal's domain and use the local bus.

### What lives where

| Concern | Location | Trust |
|---|---|---|
| Agent / skill / team definitions | Repo (committed) | Shared playbook |
| Roster, scope ownership, standing agreements | Repo (PR-reviewed) | Shared, auditable |
| Membrane messages, contracts, artifacts | GitHub (issues/PRs/data branch) | Shared, auditable |
| Account token | Node only | Never leaves the machine |
| **Delegate-memory (the human's preference model)** | **Node only, private** | **Never crosses the membrane** |
| Per-node runtime (worktrees, local bus) | Node only | Private |

### GitHub channels

Split by audience:

- **Human-facing** (escalations, approvals, plan/intent review, deliverables) →
  **issues / PR comments / PRs**. The human is already there; conflict-free
  (each comment is its own append); naturally ordered; **contestable by
  design** — which is the transparency a delegate system needs anyway.
- **Machine-to-machine** (task handoffs, contract proposals) → an **orphan data
  branch** as an append-only, content-addressed event log (one file per message
  → no merge conflicts), and/or a per-node **inbox ref** each node polls with a
  conditional `ETag` GET. `repository_dispatch` can wake Actions, but NAT'd
  laptops poll a single inbox ref — that is the pragmatic transport floor.

### Identity and anti-spoof

Identity is anchored to **GitHub's native authorship**, never to claims in a
message body. Anyone with write access can *type* `execution_owner: bob`; that
claim is honored only if the GitHub identity that posted it is Bob's node.
Authorization (team membership, scope ownership) is itself version-controlled
config in the repo.

### Membrane message schema (minimum)

```
author          # GitHub identity (the trust anchor)
on_behalf_of     # principal, when a proxy acts
execution_owner  # the account/node that must run a dispatched task (ToS field)
addressed_to     # principal / scope
scope            # the lane this belongs to
provenance       # human-authored | agent-authored
kind             # request | proposal | counter | accept | reject | withdraw |
                 #   deadlock | artifact
body             # contract terms or content
```

## The proxy and its delegate-memory

A proxy that retrieves the nearest past answer is a **parrot**. A delegate
**generalizes the principal's policy to a situation it has never seen.** That
needs structure beyond a flat episodic store, all of it keyed on a **decision
signature**:

```
(domain, decision_type, stakes/reversibility, affected_scope,
 options, chosen_option, stated_reason, outcome, agreement_with_human)
```

Four layers, each with its own retrieval:

1. **Episodic** — raw interactions, append-only. Source of truth. (Exists today
   as ACT-R chunks, `proxy/memory.py`.)
2. **Distilled policy/preference layer** — named, deduplicated rules and values
   *extracted* from episodes, each with provenance, recency, confidence.
   Retrieved **by decision features, not text similarity**.
3. **Precedent index** — past decisions retrievable **by analogy on the
   signature** ("last time the signature looked like this, you chose Y
   because Z").
4. **Risk frontier** — `(domain × decision_type × stakes) → autonomy band +
   agreement history`. Structured data, not prose. This *is* the learned risk
   tolerance, per cell, not a global dial.

A gate retrieves a **triple**: applicable policies + nearest precedents + the
risk-band for this cell. That triple is what makes the proxy a delegate. The
**prediction→correction signal** writes back into all four layers: a
predicted≠actual escalation adds a precedent, may mint or revise a policy (with
the human's reason), and pushes the band toward "ask more here"; an agreement
reinforces and nudges toward autonomy.

The memory is **personal and private**. A question addressed to Bob travels the
membrane to Bob's node; his proxy reasons over *his* private memory on *his*
account; only the **decision** travels back. Preferences never leave the
machine — only choices do. So the two knowledge paths are explicitly separated:
**org/team norms promote upward and are shared (repo); the personal
delegate-model stays with the person.** (Today's promotion chain in
`learning/` is the shared path; the personal path must be carved out from it.)

### The mandate is the delegate-memory projected onto contract terms

A team's negotiating preferences are the proxy's delegate-model **projected onto
the term space** (scope / cost / schedule / review), split into:

- **Hard terms (reservation values)** — human-set, non-negotiable without
  escalation. The floor.
- **Soft terms (tradeable defaults)** — the proxy may move these during
  negotiation.

**The proxy's negotiating authority is its autonomy.** It can sign anything in
the soft zone; crossing a hard term escalates to the human. Therefore the
**reservation line is the escalation boundary** — "risk tolerance," "cost
tolerance," and "escalation threshold" are one object, the mandate.

## CfA as contract negotiation

CfA is fractal. The same protocol that runs between a human and their team runs
at the membrane between principals. A cross-membrane CfA is a contract
negotiation:

| Contract concept | CfA mechanism |
|---|---|
| Clauses | Intent / plan / cost / schedule / review terms |
| Signing | Approval gates |
| Amendment | Backtracking (already in the state machine) |
| Breach / termination | Withdraw |
| Declining to sign | Reject-at-intake |

### Two tiers of consent

Most negotiation happens **once, at the relationship level**, not per job:

1. **Standing agreement** (per team-pair, *bidirectional*): default lanes,
   budget envelopes, turnaround, auto-approve thresholds, review depth.
   Negotiated rarely, **PR-reviewed and repo-recorded**, refined over repeated
   jobs, and **bounded by both humans' mandates** — it can only settle where the
   two reservation sets overlap.
2. **Per-CfA contract** (per job, *directional*): scope/plan/cost/schedule for
   this one job, negotiated **within** the standing agreement, mutually signed.

The dynamic that keeps the membrane from drowning: per-job negotiation is
**shallow when the job fits the standing agreement** (both proxies auto-sign)
and **deep only when it does not** (escalates a term). The standing agreement
does the heavy lifting.

### Negotiation depth

Capped at **propose → counter-once → accept/reject**. No open-ended haggling, no
multi-round auctions — that is a research rabbit hole. Lean on
**backtracking-on-overrun** instead of precise up-front bargaining.

### Structure: two axes, possibly two approvers

For cross-membrane work, **correctness and cost approvals can sit with different
principals.** The *requester* owns "does this plan achieve my intent?"; the
*receiver* owns "can I afford this on my quota/time?" The plan-gate becomes
two-dimensional and possibly two-party on the same plan.

### Human-update propagation

If a human tightens a reservation, any standing agreement that now exceeds the
new mandate must **trigger renegotiation** — not silently persist. The delegate
model is the source; contracts are downstream; source changes propagate.

## Cost and schedule

Scope is one corner of the iron triangle; **cost (tokens) and schedule (time)
are the other two**, and they have been implicit. Tokens matter most because
**quota is the exact ToS-sensitive resource** — a budget is consent made
quantitative.

- **Where it attaches.** Budget *envelope* (ceiling, rate, turnaround) lives in
  the **standing agreement**. The per-job **cost gate lands after planning** —
  you cannot cost what you have not planned. Execution tracks actuals; an
  **overrun is a backtrack** to the cost gate (the cost-axis analog of
  "execution revealed the plan was wrong").
- **Estimates are learned, not guessed.** Telemetry already records tokens per
  turn (`telemetry/`). That is the corpus for **per-job-type cost priors**.
  Design for **distributions + an exploratory budget** ("spend up to 5k to
  scope it, then re-quote"), not point quotes.
- **Tokens ≠ time.** Tokens are finite-but-replenishing, personal,
  ToS-sensitive. Time is scheduling — deadlines, availability, priority. Treat
  them as separate envelope dimensions.
- **Layered enforcement.** A **hard per-principal global cap** ("at most X of my
  quota on shared work this week" — the absolute quota protector), **soft
  envelopes** per grant within it, and **soft per-job estimates with hard
  escalation on overrun**. Protects the account at the outer boundary; lets jobs
  flow without nagging.
- **Demand side.** The requester must state **value / priority / urgency**, or
  the cost gate has no denominator.
- **Who pays.** Each principal spends their own quota on their own scope. The
  membrane makes consumption **attributable and visible** so a principal can see
  the project leaning on them and throttle — not an internal billing system.

## Provenance gate (the team lead's new job)

Every inbound job is classified by **verifiable provenance**:

- **Internal** — from my own human, or a sibling team *under the same
  principal*. Already-consented scope → proceed; proxy autonomy applies.
- **External** — from a different principal. The lead **cannot start work**; it
  opens the intake CfA with the decider.

The principal boundary, not the team boundary, is the membrane: one human can
run five teams, and work flowing among them is all internal. The intake gate
fires only when the requesting principal differs. Out-of-lane external
acceptance is the costly-if-wrong direction, so it **defaults to escalate** —
the proxy auto-accepts only inside a pre-granted lane.

## Deadlock as a first-class state

Because consent is the only mechanism and only humans break ties, the worst
failure is a **silent stall**. So:

- A negotiation that cannot reach a contract emits an explicit
  **`deadlock`** outcome with the **specific clashing terms**.
- It **pages both humans** (or the project lead as a human), not a generic
  timeout.
- Leadership response options are all non-coercive: change one's own mandate,
  re-scope, reroute to a willing party, or convene the two humans.

## Worked example

Alice's project needs a change in the billing module, which Bob owns.

1. Alice's team lead plans work that touches billing. The **provenance gate**
   sees billing is external (Bob's scope) → it does not execute; it emits a
   `request` on the membrane addressed to Bob, citing the **standing agreement**
   Alice↔Bob.
2. Bob's node polls its inbox ref, picks up the request. Bob's **proxy** runs
   the intake: is this covered by an accepted lane? Budget remaining? Within
   Bob's mandate?
   - **In-lane, fits envelope, soft terms only** → proxy **auto-signs** a
     per-job contract on Bob's behalf (`on_behalf_of: bob`). Work runs on Bob's
     account.
   - **Out-of-lane or hard term touched** → proxy **escalates** to Bob with a
     one-line summary; the job **parks at the intent gate** until Bob answers.
3. Bob's team plans the change; the plan yields a **cost estimate** from
   telemetry priors. The **cost gate** checks it against the envelope. Overrun
   risk → counter back to Alice with a revised quote (counter-once).
4. Alice's side (her proxy, within her mandate) accepts the counter, or rejects
   and reroutes.
5. Execution runs on Bob's account, in Bob's worktree. The artifact returns via
   a **PR** — legible, contestable, mergeable under Bob's name.
6. If, mid-execution, the change proves larger than the agreed intent, Bob's
   team **backtracks across the membrane** to renegotiate — CfA's existing
   cross-phase backtrack, now spanning principals.
7. If Alice and Bob's mandates cannot overlap, the negotiation emits
   **`deadlock`** and pages both humans.

## Mapping to the existing codebase

**Reuse:**
- `cfa/` state machine + cross-phase backtracking → the contract protocol and
  amendment.
- `cfa/gates/` escalation/intervention → the intake gate and proxy routing; the
  policy knobs (`always` / `when_unsure` / `never`) → the mandate's autonomy
  bands.
- `messaging/conversations.py` SQLite bus → the **local** tier, unchanged.
- `proxy/memory.py` ACT-R chunks → the **episodic** layer of delegate-memory.
- `learning/` promotion chain → the **shared org-norms** path.
- `telemetry/` token records → the **cost-estimate** training corpus.
- `config/` roster + `util/role_enforcer.py` D-A-I roles → principal identity,
  scope ownership, who may sign.

**New:**
- The **membrane**: GitHub transport (inbox ref + data branch + issue/PR
  channels), the message schema, GitHub-auth identity anchoring, the
  **execution-owner invariant** as a tested property.
- **Standing agreements** and **mandates** as first-class, repo-governed,
  bounded-by-both-humans objects.
- The **distilled / precedent / risk-frontier** memory layers and the
  decision-signature key.
- The **personal vs shared** split in the learning paths (delegate-model stays
  on-node).
- The **cost gate** (post-plan), budget envelopes, the layered cap.
- The **provenance gate** at the team lead.
- **Deadlock** as an explicit, paging outcome.

## Phased build

1. **Single-node memory upgrade.** Build the decision-signature schema and the
   four-layer delegate-memory + prediction→correction loop. Provable on one
   node, no federation. (Independently valuable; de-risks the proxy.)
2. **Mandate + contract object.** Hard/soft terms, the cost gate, telemetry cost
   priors. Still single-node (the human is the "other party").
3. **Membrane v0.** Two principals, the inbox-ref transport, the
   execution-owner invariant with a conformance test, provenance gate, intake
   CfA over the membrane. Issues/PRs for human-facing, data branch for handoffs.
4. **Standing agreements + deadlock.** Repo-governed agreements, two-tier
   consent, deadlock detection + paging.
5. **Relationship learning + quota attribution.** Refine standing terms from
   outcomes; surface per-principal consumption.

## Open decisions

1. **Scope-grant attachment** — to a specific principal ("Alice may send me
   billing work") or to a project/role ("whoever owns billing-coordination
   may")? Lean **role-attached** (survives rotation, lives in the git-governed
   roster), at the cost of the "I agreed to work *for Alice*" intuition.
2. **Scope fluidity** — static-with-explicit-rehand vs. fluid per-task handoff.
   Lean **static**: fluid means a consent event per handoff and a worse ToS
   story.
3. **Budget hardness** — confirmed layered: hard global cap, soft envelopes,
   hard overrun escalation. Revisit once cost priors are trustworthy.
4. **Membrane granularity** — does multi-turn escalation *dialog* live on
   GitHub (maximally legible, rate-limit-heavy) or only the task handoff?
5. **Always-on proxy** — standardize the personal always-on node, or leave
   availability to whoever runs a daemon?
