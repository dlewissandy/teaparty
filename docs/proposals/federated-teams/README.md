# Federated Teams

A design for mixed human/AI teams that compose two hierarchical metaphors —
**vertically-integrated organizations** (internal initiatives) and **distributed
partnerships** (external engagements) — on one substrate, under a hard
constraint: each human runs the Claude Code CLI on their own account, so compute
is permanently sharded per human and no node ever runs another human's work.

The system is **safe and license-clean by construction** (consent only, no
coercion, execution-owner enforced) and **deliberately not live by construction**
(deadlock is a legal outcome; only humans break a partnership deadlock).

## Documents (reading order)

1. **[`model.md`](model.md)** — the authoritative conceptual model. Durable
   **structure** (orgs → teams → roles → memberships → standing agreements) vs.
   transient **work** (initiatives, engagements), wired by **DAI bindings** where
   only the *doer* binding carries execution. Read this first.
2. **[`design.md`](design.md)** — the implementation-grade spine: the contract
   negotiation state machine, the mandate `evaluate()` function, the membrane
   wire protocol + consistency model, the delegate-memory schema/retrieval/band
   rules, the cost gate, and the execution-owner invariant + conformance test.
3. **[`design-org.md`](design-org.md)** — completes the spec at the org layer:
   structure schemas (org-definition repo), initiatives/engagements + DAI
   bindings, the intra-org **directive** protocol (and the override/reassign/
   preempt primitives), the cross-org **engagement membrane** (partnership repo,
   bootstrap, cross-org AUTH), conflict-of-interest, quota-across-roles,
   bootstrapping, failure/recovery, and the **closed-decisions ledger** (§13).
4. **[`proposal.md`](proposal.md)** — the original sketch, superseded in part by
   `model.md`; kept for history. Its federation/contract reasoning is the
   inter-org (engagement) case.

## The spine in one paragraph

Every collaboration is a **Conversation for Action** that produces a signed
**contract** between a WHAT-decider and a team's HOW-decider. Where the decider
binding lands sets the ceremony: same principal → implicit; same org →
**directive** (pushed pre-accepted under role authority, bounded by the report's
reservations and learned risk band); another org → **negotiated** across a
git-hosted membrane that carries information freely and execution never. A
per-human **proxy** signs within a **mandate** (`personal_hard ∩ role authority`)
learned from a private, role-contextualized **delegate-memory**; autonomy is the
width of that mandate, earned per (domain, decision-type, stakes) cell with
asymmetric regret. Cost (tokens) and schedule are first-class contract terms,
estimated from telemetry, with a hard per-human quota cap.

## Build order

Phased in `design.md` §11 and `design-org.md`:

1. **Delegate-memory on one node** — decision-signature schema, four memory
   layers, prediction→correction loop, risk bands. No federation; the human is
   the other party. Independently valuable.
2. **Mandate + Contract + cost gate** — still single-node; the human↔team CfA
   becomes a signed contract.
3. **Structure layer + intra-org membrane + directive protocol** — orgs, roles,
   teams, memberships; the org-repo membrane; the execution-owner conformance
   test.
4. **Engagement membrane** — partnership repo, bootstrap, cross-org AUTH,
   standing agreements, deadlock paging, conflict-of-interest.
5. **Relationship learning + quota attribution** — refine lanes from outcomes;
   per-role consumption.

Note: the existing documentation in `docs/` is known to be out of sync with the
current code; this proposal set is self-contained and references code modules by
path where it reuses them.
